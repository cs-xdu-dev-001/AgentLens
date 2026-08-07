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
