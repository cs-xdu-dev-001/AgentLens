from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any


QUEUE_PRIORITIES = {"now": 0, "next": 1, "later": 2}


@dataclass(frozen=True)
class QueuedPrompt:
    text: str
    display_text: str
    priority: str = "next"
    sequence: int = 0


class PromptHistoryStore:
    def __init__(self, path: Path, *, limit: int = 500) -> None:
        self.path = path.expanduser().resolve()
        self.limit = max(1, int(limit))

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name != "nt":
            path.chmod(mode)

    def load(self) -> list[str]:
        if not self.path.is_file():
            return []
        values: list[str] = []
        try:
            for raw_line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                text = str(payload.get("text") or "") if isinstance(payload, dict) else ""
                if text:
                    values.append(text)
        except (OSError, UnicodeError):
            return []
        return values[-self.limit :]

    def append(self, text: str) -> bool:
        value = text.strip()
        if not value:
            return True
        history = self.load()
        if history and history[-1] == value:
            return True
        history.append(value[:10_000])
        history = history[-self.limit :]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._chmod(self.path.parent, 0o700)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                "".join(
                    json.dumps({"text": item}, ensure_ascii=False) + "\n"
                    for item in history
                ),
                encoding="utf-8",
            )
            self._chmod(temporary, 0o600)
            temporary.replace(self.path)
            self._chmod(self.path, 0o600)
        except OSError:
            return False
        return True

    def clear(self) -> bool:
        try:
            if self.path.is_file():
                self.path.unlink()
        except OSError:
            return False
        return True


class PromptQueueStore:
    """Crash-safe, workspace-scoped queue storage for the Ink client."""

    def __init__(self, path: Path, *, limit: int = 20) -> None:
        self.path = path.expanduser().resolve()
        self.limit = max(1, int(limit))

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name != "nt":
            path.chmod(mode)

    @staticmethod
    def _text(value: Any, limit: int) -> str:
        return str(value or "").replace("\x00", "")[:limit]

    def _normalize_item(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        identifier = self._text(value.get("id"), 100).strip()
        text = self._text(value.get("text"), 10_000).strip()
        if not identifier or not text:
            return None
        priority = self._text(value.get("priority"), 16).lower()
        if priority not in QUEUE_PRIORITIES:
            priority = "next"
        lifecycle = self._text(value.get("lifecycle"), 16).lower()
        if lifecycle not in {"queued", "started"}:
            lifecycle = "queued"
        raw_paths = value.get("attachmentPaths")
        attachment_paths = [
            self._text(path, 1_000)
            for path in (raw_paths if isinstance(raw_paths, list) else [])
            if self._text(path, 1_000).strip()
        ][:20]
        try:
            sequence = max(0, int(value.get("sequence") or 0))
        except (TypeError, ValueError):
            sequence = 0
        return {
            "id": identifier,
            "text": text,
            "displayText": self._text(value.get("displayText") or text, 10_000),
            "priority": priority,
            "sequence": sequence,
            "mode": "shell" if value.get("mode") == "shell" else "prompt",
            "reasoningEffort": self._text(
                value.get("reasoningEffort") or "default", 40
            ),
            "permissionMode": self._text(
                value.get("permissionMode") or "ask", 40
            ),
            "attachmentPaths": attachment_paths,
            "lifecycle": lifecycle,
            "requestId": self._text(value.get("requestId"), 100),
        }

    def _load(self) -> tuple[dict[str, Any], bool]:
        fallback = {"version": 1, "paused": False, "items": []}
        if not self.path.is_file():
            return fallback, True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return fallback, False
        if not isinstance(raw, dict):
            return fallback, False
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in raw.get("items") if isinstance(raw.get("items"), list) else []:
            item = self._normalize_item(value)
            if item is None or item["id"] in seen:
                continue
            seen.add(item["id"])
            items.append(item)
            if len(items) >= self.limit:
                break
        return (
            {
                "version": 1,
                "paused": bool(raw.get("paused")),
                "items": items,
            },
            True,
        )

    def load(self) -> dict[str, Any]:
        snapshot, _readable = self._load()
        return snapshot

    def save(self, snapshot: dict[str, Any]) -> bool:
        items = [
            item
            for value in snapshot.get("items", [])
            if (item := self._normalize_item(value)) is not None
        ][: self.limit]
        payload = {
            "version": 1,
            "paused": bool(snapshot.get("paused")),
            "items": items,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._chmod(self.path.parent, 0o700)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            self._chmod(temporary, 0o600)
            temporary.replace(self.path)
            self._chmod(self.path, 0o600)
        except OSError:
            return False
        return True

    def sync(self, items: Any, *, paused: bool) -> bool:
        current = self.load()
        started = [
            item for item in current["items"] if item.get("lifecycle") == "started"
        ]
        incoming = items if isinstance(items, list) else []
        started_ids = {item["id"] for item in started}
        queued = [
            item
            for value in incoming
            if (item := self._normalize_item(value)) is not None
            and item["id"] not in started_ids
        ]
        return self.save({"paused": paused, "items": [*started, *queued]})

    def claim(
        self,
        item_id: str,
        request_id: str,
        *,
        fallback_item: Any = None,
    ) -> bool:
        snapshot = self.load()
        matched = False
        for item in snapshot["items"]:
            if item["id"] != item_id:
                continue
            item["lifecycle"] = "started"
            item["requestId"] = self._text(request_id, 100)
            matched = True
            break
        if not matched:
            item = self._normalize_item(fallback_item)
            if item is not None and item["id"] == self._text(item_id, 100):
                item["lifecycle"] = "started"
                item["requestId"] = self._text(request_id, 100)
                snapshot["items"].append(item)
                matched = True
        return matched and self.save(snapshot)

    def resolve(self, request_id: str) -> bool:
        normalized = self._text(request_id, 100)
        if not normalized:
            return True
        snapshot = self.load()
        remaining = [
            item
            for item in snapshot["items"]
            if not (
                item.get("lifecycle") == "started"
                and item.get("requestId") == normalized
            )
        ]
        if len(remaining) == len(snapshot["items"]):
            return True
        snapshot["items"] = remaining
        return self.save(snapshot)

    def restore(self) -> dict[str, Any]:
        snapshot, durable = self._load()
        recovered = 0
        for item in snapshot["items"]:
            if item.get("lifecycle") != "started":
                continue
            item["lifecycle"] = "queued"
            item["requestId"] = ""
            recovered += 1
        if recovered:
            snapshot["paused"] = True
            durable = self.save(snapshot)
        return {**snapshot, "recovered": recovered, "durable": durable}


@dataclass
class TuiSessionState:
    prompt_queue: list[QueuedPrompt] = field(default_factory=list)
    session_approvals: dict[str, str] = field(default_factory=dict)
    tool_calls: int = 0
    seen_tool_calls: set[str] = field(default_factory=set)
    cancel_requested: bool = False
    queue_paused: bool = False
    stashed_prompt: str = ""
    last_prompt: QueuedPrompt | None = None
    permission_mode: str = "ask"
    permission_rules: dict[str, set[str]] = field(
        default_factory=lambda: {
            "allow": set(),
            "ask": set(),
            "deny": set(),
        }
    )
    _queue_sequence: int = 0

    @property
    def queued_questions(self) -> list[str]:
        return [item.display_text for item in self.ordered_queue()]

    def ordered_queue(self) -> list[QueuedPrompt]:
        return sorted(
            self.prompt_queue,
            key=lambda item: (
                QUEUE_PRIORITIES.get(item.priority, 1),
                item.sequence,
            ),
        )

    def enqueue(
        self,
        text: str,
        *,
        display_text: str | None = None,
        priority: str = "next",
    ) -> QueuedPrompt:
        normalized_priority = priority if priority in QUEUE_PRIORITIES else "next"
        self._queue_sequence += 1
        item = QueuedPrompt(
            text=text,
            display_text=display_text or text,
            priority=normalized_priority,
            sequence=self._queue_sequence,
        )
        self.prompt_queue.append(item)
        return item

    def dequeue(self) -> QueuedPrompt | None:
        ordered = self.ordered_queue()
        if not ordered:
            return None
        item = ordered[0]
        self.prompt_queue.remove(item)
        return item

    def remove_queued(self, index: int) -> QueuedPrompt | None:
        ordered = self.ordered_queue()
        if index < 0 or index >= len(ordered):
            return None
        item = ordered[index]
        self.prompt_queue.remove(item)
        return item

    def reprioritize_queued(
        self,
        index: int,
        priority: str,
    ) -> QueuedPrompt | None:
        ordered = self.ordered_queue()
        if (
            index < 0
            or index >= len(ordered)
            or priority not in QUEUE_PRIORITIES
        ):
            return None
        item = ordered[index]
        updated = QueuedPrompt(
            text=item.text,
            display_text=item.display_text,
            priority=priority,
            sequence=item.sequence,
        )
        self.prompt_queue[self.prompt_queue.index(item)] = updated
        return updated

    def reset_run(self) -> None:
        self.tool_calls = 0
        self.seen_tool_calls.clear()
        self.cancel_requested = False

    def record_tool(self, event: dict[str, Any]) -> None:
        name = str(
            event.get("toolName")
            or event.get("tool_name")
            or event.get("name")
            or "tool"
        )
        identifier = str(
            event.get("toolCallId")
            or event.get("callId")
            or event.get("id")
            or name
        )
        if identifier not in self.seen_tool_calls:
            self.seen_tool_calls.add(identifier)
            self.tool_calls += 1

    def reset_session(self) -> None:
        self.prompt_queue.clear()
        self.session_approvals.clear()
        self.queue_paused = False
        self.stashed_prompt = ""
        self.last_prompt = None
        self.permission_mode = "ask"
        for rules in self.permission_rules.values():
            rules.clear()
        self.reset_run()

    def permission_behavior(self, tool_name: str) -> str | None:
        normalized = tool_name.strip().lower()
        if not normalized:
            return None
        for behavior in ("deny", "ask", "allow"):
            rules = self.permission_rules.get(behavior, set())
            if "*" in rules or normalized in rules:
                return behavior
        return None

    def set_permission_rule(self, behavior: str, tool_name: str) -> bool:
        normalized = tool_name.strip().lower()
        if behavior not in self.permission_rules or not normalized:
            return False
        for rules in self.permission_rules.values():
            rules.discard(normalized)
        self.permission_rules[behavior].add(normalized)
        return True

    def remove_permission_rule(self, behavior: str, tool_name: str) -> bool:
        if behavior not in self.permission_rules:
            return False
        normalized = tool_name.strip().lower()
        if normalized not in self.permission_rules[behavior]:
            return False
        self.permission_rules[behavior].remove(normalized)
        return True
