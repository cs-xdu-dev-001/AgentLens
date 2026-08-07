from __future__ import annotations

import re
from time import monotonic
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static, TextArea

from .commands import SlashCommand, match_commands


SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
    "cookie",
    "api_key",
    "apikey",
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|token|secret|password|authorization|cookie|"
    r"private[_-]?key|key)[\"']?\s*[:=]\s*[\"']?)([^\"',;\s}]+)"
)
OPENAI_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def redact_public_detail(value: Any, *, limit: int = 180) -> str:
    def render(item: Any, depth: int = 0) -> str:
        if depth > 4:
            return "…"
        if isinstance(item, dict):
            values = []
            for key, child in item.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized == "key" or any(
                    part in normalized for part in SENSITIVE_KEY_PARTS
                ):
                    values.append(f"{key}=[已隐藏]")
                else:
                    values.append(f"{key}={render(child, depth + 1)}")
            return ", ".join(values)
        if isinstance(item, (list, tuple)):
            return ", ".join(render(child, depth + 1) for child in item[:8])
        text = str(item)
        text = OPENAI_KEY_PATTERN.sub("[已隐藏]", text)
        return SENSITIVE_VALUE_PATTERN.sub(r"\1[已隐藏]", text)

    text = " ".join(render(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class CommandMenu(Vertical):
    """Keyboard-driven slash command suggestions kept near the composer."""

    def __init__(self) -> None:
        super().__init__(id="command-menu")
        self.matches: list[SlashCommand] = []
        self.selected = 0

    async def update_query(self, value: str) -> None:
        query = value.lstrip().lower()
        self.matches = match_commands(query)
        self.selected = min(self.selected, max(0, len(self.matches) - 1))
        await self._render_matches()

    async def _render_matches(self) -> None:
        await self.remove_children()
        self.set_class(bool(self.matches), "visible")
        for index, command in enumerate(self.matches):
            row = Text()
            row.append(f"{command.value:<18}", style="bold cyan")
            row.append(command.description, style="dim")
            item = Static(row, classes="command-option")
            item.set_class(index == self.selected, "selected")
            await self.mount(item)

    async def move(self, delta: int) -> None:
        if not self.matches:
            return
        self.selected = (self.selected + delta) % len(self.matches)
        await self._render_matches()

    async def hide(self) -> None:
        self.matches = []
        self.selected = 0
        await self._render_matches()

    @property
    def selected_value(self) -> str | None:
        if not self.matches:
            return None
        return self.matches[self.selected].value

    @property
    def selected_command(self) -> SlashCommand | None:
        if not self.matches:
            return None
        return self.matches[self.selected]


class RunActivity(Vertical):
    """Public, sanitized Agent progress for one turn."""

    STATUS_LABELS = {
        "running": "运行中",
        "waiting": "等待确认",
        "pending": "等待中",
        "success": "已完成",
        "succeeded": "已完成",
        "completed": "已完成",
        "failed": "失败",
        "error": "失败",
        "cancelled": "已取消",
    }

    def __init__(self) -> None:
        super().__init__(classes="run-activity")
        self.started_at = monotonic()
        self.finished = False
        self._rows: dict[str, Static] = {}
        self._statuses: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._details: dict[str, str] = {}
        self.expanded = True
        self._tool_sequence = 0

    def compose(self):
        yield Static("正在处理 · 0.0s", classes="activity-header")
        yield Vertical(classes="activity-steps")

    async def begin(self) -> None:
        await self.upsert("model", "分析任务", "running")

    async def upsert(
        self,
        key: str,
        title: str,
        status: str,
        detail: str = "",
    ) -> None:
        normalized = status.lower() or "running"
        label = self.STATUS_LABELS.get(normalized, normalized)
        value = Text()
        marker = "×" if normalized in {"failed", "error"} else (
            "•" if normalized in {"running", "waiting"} else "✓"
        )
        value.append(f"  {marker} ", style="red" if marker == "×" else "cyan")
        value.append(title or "Agent步骤")
        value.append(f"  {label}", style="dim")
        if detail:
            self._details[key] = detail
            if self.expanded:
                value.append(f"  {detail}", style="dim")
        row = self._rows.get(key)
        if row is None:
            row = Static(value, classes="activity-step")
            self._rows[key] = row
            await self.query_one(".activity-steps", Vertical).mount(row)
        else:
            row.update(value)
        self._statuses[key] = normalized
        self._titles[key] = title
        row.set_class(normalized in {"failed", "error"}, "failed")
        row.set_class(normalized in {"running", "waiting"}, "active")

    @staticmethod
    def _safe_detail(value: Any, *, limit: int = 180) -> str:
        return redact_public_detail(value, limit=limit)

    async def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        for key in tuple(self._rows):
            await self.upsert(
                key,
                self._titles.get(key, "Agent步骤"),
                self._statuses.get(key, "running"),
                self._details.get(key, ""),
            )

    async def update_event(self, event: dict) -> None:
        event_type = str(event.get("type") or "")
        if event_type in {"text_delta", "answer", "message", "model_event"}:
            await self.upsert("model", "模型生成回答", "running")
            return
        if event_type == "agent_step":
            step = event.get("step") if isinstance(event.get("step"), dict) else event
            kind = str(step.get("kind") or "")
            name = str(step.get("name") or "")
            key = (
                "model"
                if kind == "model"
                else str(
                    step.get("stepId")
                    or step.get("id")
                    or f"{kind}:{name}"
                )
            )
            title = name or str(step.get("title") or "Agent步骤")
            duration = step.get("durationMs")
            detail = (
                f"{int(duration)}ms"
                if isinstance(duration, (int, float))
                else ""
            )
            await self.upsert(
                key,
                title,
                str(step.get("status") or "running"),
                detail,
            )
            return
        if event_type in {"tool", "tool_result"}:
            latency = event.get("latencyMs")
            fragments = []
            if isinstance(latency, (int, float)):
                fragments.append(f"{int(latency)}ms")
            payload = (
                event.get("arguments")
                or event.get("input")
            )
            safe = self._safe_detail(payload)
            if safe:
                fragments.append(safe)
            detail = " · ".join(fragments)
            name = str(
                event.get("toolName")
                or event.get("tool_name")
                or event.get("name")
                or "工具调用"
            )
            call_id = str(
                event.get("toolCallId")
                or event.get("callId")
                or event.get("id")
                or ""
            )
            if not call_id:
                self._tool_sequence += 1
                call_id = str(self._tool_sequence)
            await self.upsert(
                f"tool:{call_id}",
                name,
                str(event.get("status") or "completed"),
                detail,
            )
            return
        if event_type in {
            "run_snapshot",
            "plan_created",
            "run_updated",
            "step_updated",
        }:
            run = event.get("run")
            if not isinstance(run, dict):
                return
            steps = run.get("steps")
            if isinstance(steps, list):
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        continue
                    await self.upsert(
                        str(step.get("id") or step.get("stepId") or f"plan:{index}"),
                        str(step.get("title") or step.get("name") or f"步骤{index + 1}"),
                        str(step.get("status") or "pending"),
                    )
            return
        if event_type == "approval_required":
            await self.upsert(
                "approval",
                str(event.get("toolName") or "工具调用"),
                "waiting",
            )

    def tick(self, elapsed: float | None = None) -> None:
        if self.finished:
            return
        value = monotonic() - self.started_at if elapsed is None else elapsed
        self.query_one(".activity-header", Static).update(
            f"正在处理 · {value:.1f}s"
        )

    async def finish(self, *, failed: bool = False) -> None:
        self.finished = True
        for key, status in tuple(self._statuses.items()):
            if status == "running":
                await self.upsert(
                    key,
                    self._titles[key],
                    "failed" if failed else "completed",
                )
        elapsed = monotonic() - self.started_at
        self.query_one(".activity-header", Static).update(
            f"{'执行失败' if failed else '执行完成'} · {elapsed:.1f}s"
        )
        self.set_class(failed, "failed")


class TranscriptView(VerticalScroll):
    """Conversation transcript with one mutable streaming response."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: Static | None = None
        self._assistant_text = ""
        self._activity: RunActivity | None = None

    async def show_welcome(
        self,
        *,
        version: str,
        model: str,
        workspace: str,
    ) -> None:
        heading = Text()
        heading.append(">_ ", style="dim")
        heading.append("KnowFlow", style="bold")
        heading.append(f"  (v{version})", style="dim")
        summary = Text()
        summary.append("model:      ", style="dim")
        summary.append(model)
        summary.append("    /model查看或修改\n", style="cyan")
        summary.append("directory:  ", style="dim")
        summary.append(workspace)
        await self.mount(Static(heading, classes="welcome-heading"))
        await self.mount(Static(summary, classes="welcome-summary"))
        await self.mount(
            Static(
                "提示：输入 / 查看命令；Ctrl+O展开执行过程；Ctrl+C中断任务。",
                classes="welcome-tip",
            )
        )

    async def add_user(self, content: str) -> None:
        value = Text()
        value.append("› ", style="bold cyan")
        value.append(content, style="bold")
        await self.mount(Static(value, classes="message user-message"))
        self._assistant = None
        self._assistant_text = ""
        self.scroll_end(animate=False)

    async def begin_run(self) -> None:
        self._activity = RunActivity()
        await self.mount(self._activity)
        await self._activity.begin()
        self.scroll_end(animate=False)

    async def update_activity(self, event: dict) -> None:
        if self._activity is not None:
            await self._activity.update_event(event)
            self.scroll_end(animate=False)

    async def finish_run(self, *, failed: bool = False) -> None:
        if self._activity is not None:
            await self._activity.finish(failed=failed)
            self.scroll_end(animate=False)

    def tick_run(self, elapsed: float) -> None:
        if self._activity is not None:
            self._activity.tick(elapsed)

    async def append_assistant(self, content: str) -> None:
        if not content:
            return
        if self._assistant is None:
            self._assistant = Static(classes="message assistant-message")
            await self.mount(self._assistant)
        self._assistant_text += content
        self._assistant.update(RichMarkdown(self._assistant_text))
        self.scroll_end(animate=False)

    async def add_notice(self, content: str, *, error: bool = False) -> None:
        await self.mount(
            Static(
                content,
                classes="notice error-notice" if error else "notice",
            )
        )
        self.scroll_end(animate=False)

    async def clear_transcript(self) -> None:
        await self.remove_children()
        self._assistant = None
        self._assistant_text = ""
        self._activity = None

    async def set_activity_expanded(self, expanded: bool) -> None:
        if self._activity is not None:
            await self._activity.set_expanded(expanded)


class Composer(TextArea):
    class Submitted(Message):
        pass

    class CommandQuery(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class CommandMove(Message):
        def __init__(self, delta: int) -> None:
            self.delta = delta
            super().__init__()

    class CommandAccepted(Message):
        pass

    class CommandDismissed(Message):
        pass

    def __init__(self) -> None:
        super().__init__(
            "",
            id="composer",
            soft_wrap=True,
            show_line_numbers=False,
            highlight_cursor_line=False,
            placeholder="输入任务，/help查看命令",
        )
        self.command_menu_open = False
        self.prompt_history: list[str] = []
        self.history_index: int | None = None
        self.history_draft = ""

    def remember(self, value: str) -> None:
        text = value.strip()
        if text and (
            not self.prompt_history or self.prompt_history[-1] != text
        ):
            self.prompt_history.append(text)
            self.prompt_history = self.prompt_history[-100:]
        self.history_index = None
        self.history_draft = ""

    def _move_history(self, delta: int) -> bool:
        if not self.prompt_history:
            return False
        if self.history_index is None:
            if delta > 0:
                return False
            self.history_draft = self.text
            self.history_index = len(self.prompt_history)
        self.history_index = max(
            0,
            min(len(self.prompt_history), self.history_index + delta),
        )
        value = (
            self.history_draft
            if self.history_index == len(self.prompt_history)
            else self.prompt_history[self.history_index]
        )
        self.load_text(value)
        return True

    def on_text_area_changed(self) -> None:
        self.post_message(self.CommandQuery(self.text))

    async def _on_key(self, event: events.Key) -> None:
        if self.command_menu_open:
            if event.key in {"up", "down"}:
                event.prevent_default()
                event.stop()
                self.post_message(
                    self.CommandMove(-1 if event.key == "up" else 1)
                )
                return
            if event.key in {"tab", "enter"}:
                event.prevent_default()
                event.stop()
                self.post_message(self.CommandAccepted())
                return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self.post_message(self.CommandDismissed())
                return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted())
            return
        if event.key in {"up", "down"} and "\n" not in self.text:
            if self._move_history(-1 if event.key == "up" else 1):
                event.prevent_default()
                event.stop()
                return
        if event.key == "ctrl+r" and self.prompt_history:
            event.prevent_default()
            event.stop()
            query = self.text.strip().lower()
            match = next(
                (
                    item
                    for item in reversed(self.prompt_history)
                    if not query or query in item.lower()
                ),
                self.prompt_history[-1],
            )
            self.load_text(match)
            return
        await super()._on_key(event)


class StatusBar(Static):
    def update_status(
        self,
        *,
        model: str,
        workspace: str,
        phase: str,
        queue_size: int,
        tool_calls: int,
        permissions: int,
    ) -> None:
        parts = [model, workspace, phase]
        if tool_calls:
            parts.append(f"工具 {tool_calls}")
        if queue_size:
            parts.append(f"队列 {queue_size}")
        parts.append(
            f"会话授权 {permissions}" if permissions else "按需确认"
        )
        self.update("  ·  ".join(parts))
