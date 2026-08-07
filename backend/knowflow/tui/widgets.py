from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import events
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static, TextArea


@dataclass(frozen=True)
class SlashCommand:
    value: str
    description: str


SLASH_COMMANDS = (
    SlashCommand("/help", "查看命令与快捷键"),
    SlashCommand("/new", "开始新会话"),
    SlashCommand("/clear", "清空当前显示"),
    SlashCommand("/model", "查看当前模型"),
    SlashCommand("/exit", "退出KnowFlow"),
)


class CommandMenu(Vertical):
    """Keyboard-driven slash command suggestions kept near the composer."""

    def __init__(self) -> None:
        super().__init__(id="command-menu")
        self.matches: list[SlashCommand] = []
        self.selected = 0

    async def update_query(self, value: str) -> None:
        query = value.strip().lower()
        self.matches = [
            command
            for command in SLASH_COMMANDS
            if command.value.startswith(query)
        ] if query.startswith("/") and " " not in query else []
        self.selected = min(self.selected, max(0, len(self.matches) - 1))
        await self._render_matches()

    async def _render_matches(self) -> None:
        await self.remove_children()
        self.set_class(bool(self.matches), "visible")
        for index, command in enumerate(self.matches):
            row = Text()
            row.append(command.value, style="bold")
            row.append(f"  {command.description}", style="dim")
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

    def compose(self):
        yield Static("Agent运行 · 0.0s", classes="activity-header")
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
        value.append(title or "Agent步骤", style="bold")
        value.append(f"  {label}", style="dim")
        if detail:
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
            detail = f"{int(latency)}ms" if isinstance(latency, (int, float)) else ""
            name = str(
                event.get("toolName")
                or event.get("tool_name")
                or event.get("name")
                or "工具调用"
            )
            await self.upsert(
                f"tool:{name}",
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
            f"Agent运行 · {value:.1f}s"
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

    async def add_user(self, content: str) -> None:
        await self.mount(Static(content, classes="message user-message"))
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
        await super()._on_key(event)
