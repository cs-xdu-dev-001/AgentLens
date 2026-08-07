from __future__ import annotations

import re
from time import monotonic
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import events, on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Collapsible, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from .commands import COMMANDS, SlashCommand, match_commands


ACCENT = "#d97757"
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
BEARER_PATTERN = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)
CLI_SECRET_PATTERN = re.compile(
    r"(?i)(--(?:api[-_]?key|token|secret|password|authorization|cookie)"
    r"(?:=|\s+)[\"']?)([^\"'\s,;]+)"
)


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
        text = BEARER_PATTERN.sub("Bearer [已隐藏]", text)
        text = JWT_PATTERN.sub("[已隐藏]", text)
        text = CLI_SECRET_PATTERN.sub(r"\1[已隐藏]", text)
        return SENSITIVE_VALUE_PATTERN.sub(r"\1[已隐藏]", text)

    text = " ".join(render(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


class CommandMenu(Vertical):
    """Keyboard-driven slash command suggestions kept near the composer."""

    def __init__(self) -> None:
        super().__init__(id="command-menu")
        self.matches: list[SlashCommand] = []
        self.selected = 0
        self.commands: tuple[SlashCommand, ...] = COMMANDS

    def compose(self):
        yield Static("命令", classes="command-menu-title")
        yield OptionList(id="command-options", compact=True)

    @staticmethod
    def _render_option(command: SlashCommand) -> Text:
        row = Text()
        row.append(command.value, style="bold")
        if command.argument_hint:
            row.append(f" {command.argument_hint}", style="dim")
        if command.source != "builtin":
            row.append(f"  [{command.source}]", style=ACCENT)
        if command.is_group:
            row.append("  ›", style=ACCENT)
        return row

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self.commands = commands

    async def update_query(self, value: str) -> None:
        query = value.lstrip().lower()
        self.matches = [
            item for item in match_commands(query, self.commands) if not item.hidden
        ]
        self.selected = min(self.selected, max(0, len(self.matches) - 1))
        await self._render_matches()

    async def _render_matches(self) -> None:
        self.set_class(bool(self.matches), "visible")
        options = self.query_one("#command-options", OptionList)
        options.clear_options()
        if self.matches:
            options.add_options(
                [
                    Option(self._render_option(command), id=command.value)
                    for command in self.matches
                ]
            )
            options.highlighted = self.selected
        self._update_title()

    def _update_title(self) -> None:
        title = self.query_one(".command-menu-title", Static)
        parent = (
            self.matches[0].value.rsplit(" ", 1)[0]
            if self.matches and " " in self.matches[0].value
            else ""
        )
        selected = self.matches[self.selected] if self.matches else None
        description = selected.description if selected else ""
        prefix = f"{parent}  子命令" if parent else "命令"
        if self.size.width and self.size.width < 70:
            title.update(f"{prefix} · {description} · ↑↓更多")
        else:
            title.update(f"{prefix} · {description}  ↑↓选择  Enter确认  Esc关闭")

    async def move(self, delta: int) -> None:
        if not self.matches:
            return
        self.selected = (self.selected + delta) % len(self.matches)
        self.query_one("#command-options", OptionList).highlighted = self.selected

    @on(OptionList.OptionHighlighted)
    def handle_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        self.selected = event.option_index
        self._update_title()

    @on(OptionList.OptionSelected)
    def handle_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        self.selected = event.option_index
        self.post_message(Composer.CommandAccepted())

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
        self._rows: dict[str, Collapsible] = {}
        self._statuses: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._details: dict[str, str] = {}
        self.expanded = False
        self._tool_sequence = 0
        self._hidden_steps = 0

    def compose(self):
        yield Static("✻ 正在处理… (0.0s)", classes="activity-header")
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
            "·" if normalized in {"running", "waiting"} else "✓"
        )
        value.append(f"  {marker} ", style="red" if marker == "×" else ACCENT)
        value.append(title or "Agent步骤")
        value.append(f"  {label}", style="dim")
        if detail:
            self._details[key] = detail
        row = self._rows.get(key)
        if row is None:
            if len(self._rows) >= 100:
                oldest_key = next(iter(self._rows))
                row = self._rows.pop(oldest_key)
                self._statuses.pop(oldest_key, None)
                self._titles.pop(oldest_key, None)
                self._details.pop(oldest_key, None)
                row.title = value
                row.query_one(".activity-detail", Static).update(
                    detail or "暂无公开详情"
                )
                row.collapsed = not self.expanded or not bool(detail)
                self.query_one(".activity-steps", Vertical).move_child(
                    row,
                    after=-1,
                )
                self._hidden_steps += 1
            else:
                row = Collapsible(
                    Static(detail or "暂无公开详情", classes="activity-detail"),
                    title=value,
                    collapsed=not self.expanded or not bool(detail),
                    classes="activity-step",
                )
                await self.query_one(".activity-steps", Vertical).mount(row)
            self._rows[key] = row
        else:
            row.title = value
            row.query_one(".activity-detail", Static).update(
                detail or self._details.get(key) or "暂无公开详情"
            )
        self._statuses[key] = normalized
        self._titles[key] = title
        row.set_class(normalized in {"failed", "error"}, "failed")
        row.set_class(normalized in {"running", "waiting"}, "active")

    @staticmethod
    def _safe_detail(value: Any, *, limit: int = 180) -> str:
        return redact_public_detail(value, limit=limit)

    async def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        for key, row in self._rows.items():
            row.collapsed = not expanded or not bool(self._details.get(key))

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
            arguments = (
                event.get("arguments")
                or event.get("input")
            )
            safe_arguments = self._safe_detail(arguments, limit=96)
            if safe_arguments:
                fragments.append(f"输入 {safe_arguments}")
            output = event.get("output") or event.get("result")
            safe_output = self._safe_detail(output, limit=120)
            if safe_output:
                fragments.append(f"结果 {safe_output}")
            error_message = self._safe_detail(
                event.get("errorMessage") or event.get("error"),
                limit=120,
            )
            if error_message:
                fragments.append(f"错误 {error_message}")
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
        frames = ("✻", "✽", "✶", "✢")
        frame = frames[int(value * 4) % len(frames)]
        self.query_one(".activity-header", Static).update(
            f"{frame} 正在处理… ({value:.1f}s)"
            + (f" · +{self._hidden_steps}早期步骤" if self._hidden_steps else "")
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
            f"{'× 执行失败' if failed else '✓ 执行完成'} ({elapsed:.1f}s)"
            + (f" · +{self._hidden_steps}早期步骤" if self._hidden_steps else "")
        )
        self.set_class(failed, "failed")


class TranscriptView(VerticalScroll):
    """Conversation transcript with one mutable streaming response."""

    MAX_VISIBLE_BLOCKS = 200
    TRIM_TO_BLOCKS = 160

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: Static | None = None
        self._assistant_text = ""
        self._activity: RunActivity | None = None
        self._assistant_render_scheduled = False
        self._message_widgets: list[Static] = []
        self._records: dict[int, tuple[str, str, bool]] = {}
        self._archived_records: list[tuple[str, str, bool]] = []
        self._archive_widgets: list[Static] = []
        self._archive_summary: Static | None = None
        self.archive_expanded = False

    async def _register_block(
        self,
        widget: Static,
        kind: str,
        content: str,
        error: bool = False,
    ) -> None:
        self._message_widgets.append(widget)
        self._records[id(widget)] = (kind, content, error)
        await self._enforce_render_cap()

    async def _enforce_render_cap(self) -> None:
        if len(self._message_widgets) <= self.MAX_VISIBLE_BLOCKS:
            return
        count = len(self._message_widgets) - self.TRIM_TO_BLOCKS
        outgoing = self._message_widgets[:count]
        self._message_widgets = self._message_widgets[count:]
        for widget in outgoing:
            record = self._records.pop(id(widget), None)
            if record is not None:
                self._archived_records.append(record)
            await widget.remove()
        await self._render_archive_summary()

    async def _render_archive_summary(self) -> None:
        if not self._archived_records:
            return
        label = (
            f"已展开{len(self._archived_records)}条历史 · Ctrl+O收起"
            if self.archive_expanded
            else f"已折叠{len(self._archived_records)}条历史 · Ctrl+O展开"
        )
        if self._archive_summary is None:
            self._archive_summary = Static(label, classes="archive-summary")
            await self.mount(self._archive_summary, before=0)
        else:
            self._archive_summary.update(label)

    @staticmethod
    def _record_widget(record: tuple[str, str, bool]) -> Static:
        kind, content, error = record
        if kind == "user":
            value = Text()
            value.append("❯ ", style=f"bold {ACCENT}")
            value.append(content, style="bold")
            return Static(value, classes="message user-message archived-message")
        if kind == "assistant":
            return Static(
                RichMarkdown(content),
                classes="message assistant-message archived-message",
            )
        return Static(
            content,
            classes=(
                "notice error-notice archived-message"
                if error
                else "notice archived-message"
            ),
        )

    async def set_archive_expanded(self, expanded: bool) -> None:
        self.archive_expanded = expanded
        for widget in self._archive_widgets:
            await widget.remove()
        self._archive_widgets = []
        if expanded and self._archived_records and self._archive_summary is not None:
            for record in self._archived_records:
                widget = self._record_widget(record)
                self._archive_widgets.append(widget)
                await self.mount(widget, before=self._archive_summary)
        await self._render_archive_summary()

    async def show_welcome(
        self,
        *,
        version: str,
        model: str,
        workspace: str,
    ) -> None:
        panel = Vertical(classes="welcome-panel")
        panel.border_title = f" KnowFlow v{version} "
        await self.mount(panel)

        brand = Text(justify="center")
        brand.append("●──────●  ", style=ACCENT)
        brand.append("KNOW", style=f"bold {ACCENT}")
        brand.append("FLOW\n", style="bold")
        brand.append("│╲    ╱   ", style=ACCENT)
        brand.append("Agent CLI\n", style="dim")
        brand.append("│ ╲  ╱\n", style=ACCENT)
        brand.append("│  ╲╱\n", style=ACCENT)
        brand.append("●   ●", style=ACCENT)
        await panel.mount(Static(brand, classes="welcome-brand"))

        context = Text(justify="center")
        model_label = model if len(model) <= 22 else f"{model[:19]}…"
        workspace_label = (
            workspace
            if len(workspace) <= 38
            else f"{workspace[:10]}…{workspace[-27:]}"
        )
        context.append(model_label, style=ACCENT)
        context.append("  ·  ", style="dim")
        context.append(workspace_label, style="dim")
        await panel.mount(Static(context, classes="welcome-context"))

        hint = Text(justify="center")
        hint.append("输入 ", style="dim")
        hint.append("/", style=f"bold {ACCENT}")
        hint.append(" 查看命令", style="dim")
        await panel.mount(Static(hint, classes="welcome-tip"))

    async def add_user(self, content: str) -> None:
        value = Text()
        value.append("❯ ", style=f"bold {ACCENT}")
        value.append(content, style="bold")
        widget = Static(value, classes="message user-message")
        await self.mount(widget)
        await self._register_block(widget, "user", content)
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
            await self._register_block(self._assistant, "assistant", "")
        self._assistant_text += content
        if not self._assistant_render_scheduled:
            self._assistant_render_scheduled = True
            self.set_timer(0.04, self._flush_streaming_assistant)

    def _flush_streaming_assistant(self) -> None:
        if not self._assistant_render_scheduled:
            return
        self._assistant_render_scheduled = False
        if self._assistant is not None:
            self._assistant.update(self._assistant_text)
            self.scroll_end(animate=False)

    def finalize_assistant(self) -> None:
        self._assistant_render_scheduled = False
        if self._assistant is not None and self._assistant_text:
            self._assistant.update(RichMarkdown(self._assistant_text))
            self._records[id(self._assistant)] = (
                "assistant",
                self._assistant_text,
                False,
            )
            self.scroll_end(animate=False)

    async def add_notice(self, content: str, *, error: bool = False) -> None:
        widget = Static(
            content,
            classes="notice error-notice" if error else "notice",
        )
        await self.mount(widget)
        await self._register_block(widget, "notice", content, error)
        self.scroll_end(animate=False)

    async def clear_transcript(self) -> None:
        await self.remove_children()
        self._assistant = None
        self._assistant_text = ""
        self._activity = None
        self._assistant_render_scheduled = False
        self._message_widgets = []
        self._records = {}
        self._archived_records = []
        self._archive_widgets = []
        self._archive_summary = None
        self.archive_expanded = False

    async def set_activity_expanded(self, expanded: bool) -> None:
        if self._activity is not None:
            await self._activity.set_expanded(expanded)
        await self.set_archive_expanded(expanded)


class HistorySearchBar(Horizontal):
    class Preview(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class Accepted(Message):
        pass

    class Cancelled(Message):
        pass

    def __init__(self) -> None:
        super().__init__(id="history-search")
        self.history: list[str] = []
        self.original = ""
        self.match = ""

    def compose(self):
        yield Static("搜索历史：", id="history-search-label")
        yield Input(placeholder="输入关键词", id="history-search-input")

    def open(self, history: list[str], original: str) -> None:
        self.history = list(history)
        self.original = original
        self.match = original
        self.add_class("visible")
        search = self.query_one("#history-search-input", Input)
        search.value = ""
        search.focus()

    def close(self) -> None:
        self.remove_class("visible")

    @on(Input.Changed)
    def handle_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        self.match = next(
            (
                item
                for item in reversed(self.history)
                if not query or query in item.lower()
            ),
            "",
        )
        label = self.query_one("#history-search-label", Static)
        label.update("搜索历史：" if self.match else "没有匹配：")
        self.post_message(self.Preview(self.match or self.original))

    @on(Input.Submitted)
    def handle_submitted(self) -> None:
        self.post_message(self.Accepted())

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.Cancelled())
            return
        await super()._on_key(event)


PASTE_THRESHOLD = 10_000
PASTE_PREVIEW = 500
PASTE_REFERENCE_PATTERN = re.compile(
    r"\n?\[粘贴内容 #(\d+)：已折叠 \d+ 字符\]\n?"
)


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

    class HistoryRequested(Message):
        pass

    def __init__(self) -> None:
        super().__init__(
            "",
            id="composer",
            soft_wrap=True,
            show_line_numbers=False,
            highlight_cursor_line=False,
            placeholder="输入任务，/查看命令",
        )
        self.command_menu_open = False
        self.prompt_history: list[str] = []
        self.history_index: int | None = None
        self.history_draft = ""
        self.pasted_contents: dict[int, str] = {}
        self._paste_sequence = 0

    def set_history(self, values: list[str]) -> None:
        self.prompt_history = list(values[-500:])
        self.history_index = None
        self.history_draft = ""

    def clear_history(self) -> None:
        self.set_history([])

    def expanded_text(self) -> str:
        def replace(match: re.Match[str]) -> str:
            return self.pasted_contents.get(int(match.group(1)), match.group(0))

        return PASTE_REFERENCE_PATTERN.sub(replace, self.text)

    def _paste_preview(self, value: str) -> str:
        if len(value) <= PASTE_THRESHOLD:
            return value
        self._paste_sequence += 1
        reference = self._paste_sequence
        hidden_content = value[PASTE_PREVIEW:-PASTE_PREVIEW]
        self.pasted_contents[reference] = hidden_content
        hidden = len(hidden_content)
        return (
            value[:PASTE_PREVIEW]
            + f"\n[粘贴内容 #{reference}：已折叠 {hidden} 字符]\n"
            + value[-PASTE_PREVIEW:]
        )

    def on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()
        self.insert(self._paste_preview(event.text))

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
            self.post_message(self.HistoryRequested())
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
        short_workspace = workspace.rstrip("/\\").split("/")[-1].split("\\")[-1]
        parts = [model, short_workspace or workspace]
        if tool_calls:
            parts.append(f"工具 {tool_calls}")
        if queue_size:
            parts.append(f"队列 {queue_size}")
        if permissions:
            parts.append(f"授权 {permissions}")
        self.update("  ·  ".join(parts))
