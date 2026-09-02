from __future__ import annotations

import asyncio
from datetime import datetime
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
from time import monotonic
from typing import Any

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from ..services.agent_execution import AgentExecution
from ..services.agent_event_protocol import agent_event_name
from ..services.local_cli_runtime import local_data_dir
from .backend import TuiBackend
from .commands import (
    COMMANDS,
    SlashCommand,
    canonical_command,
    find_command,
    merge_commands,
    parse_command,
)
from .state import PromptHistoryStore, QueuedPrompt, TuiSessionState
from .widgets import (
    CommandMenu,
    Composer,
    HistorySearchBar,
    QueuePreview,
    StatusBar,
    TranscriptView,
    error_recovery_message,
    redact_public_detail,
    tool_activity_title,
)


def _cli_release() -> str:
    """Read the checkout version during development, package metadata when installed."""
    project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if project_file.is_file():
        for line in project_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("version = "):
                return line.split("=", 1)[1].strip().strip('"')
    try:
        return version("knowflow-ai")
    except PackageNotFoundError:
        return "dev"


PERMISSION_MODE_OPTIONS = (
    (
        "ask",
        "请求批准",
        "写入、命令和外部操作都需要确认",
        "按需确认",
    ),
    (
        "auto_edit",
        "仅危险操作确认",
        "普通写入自动批准；删除、命令和未知风险仍询问",
        "普通写入自动",
    ),
    (
        "full_access",
        "完全访问",
        "本会话自动批准工具请求，不突破现有沙箱和系统权限",
        "完全访问",
    ),
)
PERMISSION_MODE_BY_ID = {
    mode: (title, description, short_label)
    for mode, title, description, short_label in PERMISSION_MODE_OPTIONS
}


class AgentEventMessage(Message):
    def __init__(self, event: dict[str, Any]) -> None:
        self.event = dict(event)
        super().__init__()


class TurnCompleted(Message):
    def __init__(self, execution: AgentExecution) -> None:
        self.execution = execution
        super().__init__()


class TurnPaused(Message):
    def __init__(self, execution: AgentExecution) -> None:
        self.execution = execution
        super().__init__()


class TurnFailed(Message):
    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__()


class CancelRequested(Message):
    def __init__(self, sent: bool, error: Exception | None = None) -> None:
        self.sent = sent
        self.error = error
        super().__init__()


class CommandCatalogLoaded(Message):
    def __init__(self, items: list[dict[str, str]]) -> None:
        self.items = items
        super().__init__()


class SessionPickerLoaded(Message):
    def __init__(
        self,
        sessions: list[dict[str, Any]],
        error: str = "",
    ) -> None:
        self.sessions = sessions
        self.error = error
        super().__init__()


class SessionRestored(Message):
    def __init__(
        self,
        execution: AgentExecution,
        selection: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> None:
        self.execution = execution
        self.selection = selection
        self.events = events
        super().__init__()


class SessionRestoreFailed(Message):
    def __init__(self, selection: dict[str, Any], error: Exception) -> None:
        self.selection = selection
        self.error = error
        super().__init__()


class CommandBrowserScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("left", "previous_tab", "上一类", show=False),
        Binding("right", "next_tab", "下一类", show=False),
        Binding("escape", "close", "关闭", show=False),
    ]

    def __init__(self, commands: tuple[SlashCommand, ...]) -> None:
        self.commands = commands
        self.tab = 0
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="command-browser-dialog"):
            yield Static(id="command-browser-tabs")
            yield OptionList(id="command-browser-options", compact=True)
            yield Static(
                "←→切换分类 · ↑↓浏览 · Esc关闭",
                classes="command-browser-footer",
            )

    def on_mount(self) -> None:
        self._render_tab()
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    def _render_tab(self) -> None:
        tabs = Text()
        for index, label in enumerate(("默认命令", "自定义命令")):
            tabs.append(f" {label} ", style="reverse bold" if index == self.tab else "dim")
            if index == 0:
                tabs.append("  ")
        self.query_one("#command-browser-tabs", Static).update(tabs)
        values = [
            command
            for command in self.commands
            if (command.source == "builtin") == (self.tab == 0) and not command.hidden
        ]
        values.sort(key=lambda command: command.value)
        options = self.query_one("#command-browser-options", OptionList)
        options.clear_options()
        if not values:
            options.add_option(Option("当前没有自定义命令", disabled=True))
        else:
            options.add_options(
                [
                    Option(
                        Text.assemble(
                            (command.value, "bold"),
                            (f" {command.argument_hint}" if command.argument_hint else "", "dim"),
                            (f"  {command.description}", "dim"),
                            (
                                f"  [{command.source_label}]" if command.source != "builtin" else "",
                                "#d97757",
                            ),
                        ),
                        id=command.value,
                    )
                    for command in values
                ]
            )
            options.highlighted = 0
        options.focus()

    def action_previous_tab(self) -> None:
        self.tab = (self.tab - 1) % 2
        self._render_tab()

    def action_next_tab(self) -> None:
        self.tab = (self.tab + 1) % 2
        self._render_tab()

    def action_close(self) -> None:
        self.dismiss(None)


class SessionPickerScreen(ModalScreen[dict[str, Any] | None]):
    """Small, keyboard-first session switcher for the Textual fallback."""

    BINDINGS = [
        Binding("down", "focus_options", "选择会话", show=False, priority=True),
        Binding("escape", "close", "关闭", show=False),
    ]

    STATUS_LABELS = {
        "completed": "已完成",
        "cancelled": "已取消",
        "failed": "失败",
        "interrupted": "已中断",
        "running": "运行中",
        "planning": "规划中",
        "waiting": "等待中",
        "waiting_approval": "待确认",
        "waiting_input": "待回答",
        "waiting_start": "准备中",
        "cancelling": "停止中",
    }

    def __init__(self, backend: TuiBackend, *, query: str = "") -> None:
        self.backend = backend
        self.initial_query = str(query or "").strip()
        self._search_query = self.initial_query.lower()
        self.sessions: list[dict[str, Any]] = []
        self.filtered: list[dict[str, Any]] = []
        self._loading = True
        self._selection_by_id: dict[str, dict[str, Any]] = {}
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="session-picker-dialog"):
            yield Static("恢复会话", classes="session-picker-title")
            yield Input(
                value=self.initial_query,
                placeholder="搜索标题、内容或状态…",
                id="session-picker-search",
            )
            yield Static(id="session-picker-summary")
            yield OptionList(id="session-picker-options", compact=True)
            yield Static(
                "输入关键词筛选 · ↓进入列表 · Enter打开 · Esc关闭",
                classes="session-picker-footer",
            )

    def on_mount(self) -> None:
        self._render_options()
        self.query_one("#session-picker-search", Input).focus()
        self.set_class(self.size.width < 64, "narrow")
        self.load_sessions()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    @staticmethod
    def _format_time(value: Any) -> str:
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1_000
            return datetime.fromtimestamp(timestamp).strftime("%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            text = str(value or "").replace("T", " ")
            return text[:16]

    @classmethod
    def _status_label(cls, value: Any) -> str:
        status = str(value or "completed").strip().lower()
        return cls.STATUS_LABELS.get(status, status or "已完成")

    def _render_options(self) -> None:
        try:
            summary = self.query_one("#session-picker-summary", Static)
            options = self.query_one("#session-picker-options", OptionList)
        except NoMatches:
            return
        query = self.query_one("#session-picker-search", Input).value.strip().lower()
        self._search_query = query
        if query:
            self.filtered = [
                session
                for session in self.sessions
                if query
                in " ".join(
                    str(session.get(key) or "")
                    for key in ("title", "answer", "status", "cwd", "projectRoot")
                ).lower()
            ]
        else:
            self.filtered = list(self.sessions)
        self._selection_by_id = {}
        options.clear_options()
        if self._loading:
            summary.update("正在读取当前工作区的会话…")
            options.add_option(Option("正在读取会话…", disabled=True))
            return
        if not self.filtered:
            summary.update("没有匹配的历史会话")
            options.add_option(
                Option(
                    "没有可恢复的会话；输入新的要求即可开始。",
                    disabled=True,
                )
            )
            return
        summary.update(
            f"{len(self.filtered)}个会话 · 当前工作区优先展示最近使用"
        )
        rendered: list[Option] = []
        for index, session in enumerate(self.filtered):
            run_id = str(
                session.get("runId") or session.get("sessionId") or ""
            ).strip()
            if not run_id:
                continue
            option_id = f"session:{index}:{run_id}"
            self._selection_by_id[option_id] = dict(session)
            title = redact_public_detail(
                session.get("title") or session.get("answer") or "未命名会话",
                limit=140,
            ) or "未命名会话"
            answer = redact_public_detail(session.get("answer") or "", limit=120)
            status = self._status_label(session.get("status"))
            timestamp = self._format_time(session.get("updatedAt"))
            pin = "★ " if session.get("pinned") else ""
            detail = f"{status} · {timestamp}" if timestamp else status
            if answer and answer != title:
                detail += f" · {answer}"
            rendered.append(
                Option(
                    Text.assemble(
                        (f"{pin}{title}", "bold"),
                        (f"  {detail}", "dim"),
                    ),
                    id=option_id,
                )
            )
        if not rendered:
            summary.update("没有可恢复的会话")
            options.add_option(Option("没有可恢复的会话。", disabled=True))
            return
        options.add_options(rendered)
        options.highlighted = 0

    @work(exclusive=True, thread=True, group="session-picker")
    def load_sessions(self) -> None:
        try:
            try:
                sessions = self.backend.list_sessions(limit=100, archived=False)
            except TypeError as exc:
                if "archived" not in str(exc):
                    raise
                sessions = self.backend.list_sessions(limit=100)
            values = [dict(item) for item in (sessions or []) if isinstance(item, dict)]
            self.post_message(SessionPickerLoaded(values))
        except Exception as exc:
            self.post_message(SessionPickerLoaded([], redact_public_detail(exc, limit=240)))

    def on_session_picker_loaded(self, message: SessionPickerLoaded) -> None:
        if not self.is_mounted:
            return
        self._loading = False
        self.sessions = message.sessions
        if message.error:
            self.query_one("#session-picker-summary", Static).update(
                f"读取失败：{message.error}"
            )
            options = self.query_one("#session-picker-options", OptionList)
            options.clear_options()
            options.add_option(Option("无法读取历史会话，请关闭后重试。", disabled=True))
            return
        self._render_options()

    @on(Input.Changed, "#session-picker-search")
    def handle_query(self, event: Input.Changed) -> None:
        self._search_query = event.value.strip().lower()
        self._render_options()

    @on(Input.Submitted, "#session-picker-search")
    def handle_query_submitted(self, event: Input.Submitted) -> None:
        selection = next(
            (
                session
                for session in self.filtered
                if str(session.get("runId") or session.get("sessionId") or "").strip()
            ),
            None,
        )
        if selection is not None:
            self.dismiss(dict(selection))

    @on(OptionList.OptionSelected, "#session-picker-options")
    def handle_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id or "")
        selection = self._selection_by_id.get(option_id)
        if selection is not None:
            self.dismiss(dict(selection))

    def action_focus_options(self) -> None:
        options = self.query_one("#session-picker-options", OptionList)
        if options.option_count and options.highlighted is None:
            options.highlighted = 0
        options.focus()

    def action_close(self) -> None:
        self.dismiss(None)


class QueueManagerScreen(ModalScreen[QueuedPrompt | None]):
    BINDINGS = [
        Binding("left", "priority_down", "降低优先级", show=False),
        Binding("right", "priority_up", "提高优先级", show=False),
        Binding("d", "delete", "移除", show=False, priority=True),
        Binding("c", "clear", "清空", show=False, priority=True),
        Binding("escape", "close", "关闭", show=False),
    ]
    PRIORITIES = ("later", "next", "now")
    PRIORITY_LABELS = {
        "now": "现在",
        "next": "接下来",
        "later": "稍后",
    }

    def __init__(self, session: TuiSessionState) -> None:
        self.session = session
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="queue-manager-dialog"):
            yield Static("任务队列", classes="queue-manager-title")
            yield Static(id="queue-manager-summary")
            yield OptionList(id="queue-manager-options", compact=True)
            yield Static(
                "Enter取回编辑 · D移除 · ←→调整优先级 · C清空 · Esc关闭",
                classes="queue-manager-footer",
            )

    def on_mount(self) -> None:
        self._render_queue()
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    def _selected_index(self) -> int | None:
        value = self.query_one("#queue-manager-options", OptionList).highlighted
        return value if value is not None and value >= 0 else None

    def _render_queue(self, *, selected: int | None = None) -> None:
        queued = self.session.ordered_queue()
        summary = (
            f"{len(queued)}项等待 · "
            f"{'自动继续' if not self.session.queue_paused else '队列已暂停'}"
        )
        self.query_one("#queue-manager-summary", Static).update(summary)
        options = self.query_one("#queue-manager-options", OptionList)
        options.clear_options()
        if not queued:
            options.add_option(Option("队列为空", disabled=True))
            return
        for index, item in enumerate(queued):
            label = self.PRIORITY_LABELS.get(item.priority, item.priority)
            options.add_option(
                Option(
                    Text.assemble(
                        (f"{index + 1}. ", "dim"),
                        (f"[{label}] ", "#d97757"),
                        (redact_public_detail(item.display_text, limit=120), ""),
                    ),
                    id=str(item.sequence),
                )
            )
        options.highlighted = min(selected or 0, len(queued) - 1)
        options.focus()

    @on(OptionList.OptionSelected, "#queue-manager-options")
    def handle_selected(self, event: OptionList.OptionSelected) -> None:
        index = event.option_index
        item = self.session.remove_queued(index)
        if item is not None:
            self.dismiss(item)

    def _change_priority(self, delta: int) -> None:
        index = self._selected_index()
        if index is None:
            return
        queued = self.session.ordered_queue()
        if index >= len(queued):
            return
        item = queued[index]
        current = self.PRIORITIES.index(item.priority)
        target = self.PRIORITIES[
            max(0, min(len(self.PRIORITIES) - 1, current + delta))
        ]
        if target == item.priority:
            return
        updated = self.session.reprioritize_queued(index, target)
        self._render_queue(selected=index)
        if updated is not None:
            self.notify(
                f"已设为{self.PRIORITY_LABELS[updated.priority]}执行。"
            )

    def action_priority_down(self) -> None:
        self._change_priority(-1)

    def action_priority_up(self) -> None:
        self._change_priority(1)

    def action_delete(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        removed = self.session.remove_queued(index)
        if removed is not None:
            self.notify(
                "已移除："
                + redact_public_detail(removed.display_text, limit=80)
            )
        self._render_queue(selected=index)

    def action_clear(self) -> None:
        count = len(self.session.prompt_queue)
        self.session.prompt_queue.clear()
        self._render_queue()
        self.notify(f"已清空{count}个等待任务。")

    def action_close(self) -> None:
        self.dismiss(None)


class PermissionModeScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "close", "关闭", show=False)]
    DESCRIPTIONS = {
        "ask": "写入和命令前询问",
        "auto_edit": "普通写入自动，危险操作询问",
        "full_access": "本会话自动执行，仍受沙箱限制",
    }

    def __init__(self, current_mode: str) -> None:
        self.current_mode = current_mode
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="permission-mode-dialog"):
            yield Static("执行权限", classes="permission-title")
            yield OptionList(id="permission-mode-options", compact=True)
            yield Static(
                "↑↓选择 · Enter确认 · Esc关闭",
                classes="permission-footer",
            )

    def on_mount(self) -> None:
        options = self.query_one("#permission-mode-options", OptionList)
        selected = 0
        for index, (mode, title, description, _) in enumerate(
            PERMISSION_MODE_OPTIONS
        ):
            if mode == self.current_mode:
                selected = index
            marker = "✓ " if mode == self.current_mode else "  "
            options.add_option(
                Option(
                    Text.assemble(
                        (marker + title, "bold"),
                        (f"  {self.DESCRIPTIONS.get(mode, description)}", "dim"),
                    ),
                    id=mode,
                )
            )
        options.add_option(
            Option(
                Text.assemble(
                    ("  高级规则", "bold"),
                    ("  按工具设置允许、询问或拒绝", "dim"),
                ),
                id="rules",
            )
        )
        options.highlighted = selected
        options.focus()
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    @on(OptionList.OptionSelected, "#permission-mode-options")
    def handle_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id or "") or None)

    def action_close(self) -> None:
        self.dismiss(None)


class PermissionRuleScreen(ModalScreen[dict[str, set[str]]]):
    BINDINGS = [
        Binding("left", "previous_tab", "上一类", show=False),
        Binding("right", "next_tab", "下一类", show=False),
        Binding("tab", "next_tab", "下一类", show=False),
        Binding("a", "add_rule", "添加规则", show=False, priority=True),
        Binding("slash", "search", "搜索", show=False, priority=True),
        Binding("d", "delete_rule", "删除规则", show=False, priority=True),
        Binding("escape", "close", "关闭", show=False),
    ]
    BEHAVIORS = ("allow", "ask", "deny")
    LABELS = {"allow": "Allow", "ask": "Ask", "deny": "Deny"}
    DESCRIPTIONS = {
        "allow": "匹配的工具不再询问",
        "ask": "匹配的工具始终询问",
        "deny": "匹配的工具始终拒绝",
    }

    def __init__(self, rules: dict[str, set[str]]) -> None:
        self.rules = {key: set(values) for key, values in rules.items()}
        self.tab = 0
        self.adding = False
        super().__init__()

    @property
    def behavior(self) -> str:
        return self.BEHAVIORS[self.tab]

    def compose(self) -> ComposeResult:
        with Container(id="permission-rules-dialog"):
            yield Static("工具权限规则", classes="permission-title")
            yield Static(id="permission-rule-tabs")
            yield Static(id="permission-rule-description")
            yield Input(
                placeholder="输入关键词搜索；按A添加规则",
                id="permission-rule-input",
            )
            yield OptionList(id="permission-rule-options", compact=True)
            yield Static(
                "←→切换分类 · /搜索 · A添加 · D删除 · Esc保存并关闭",
                classes="permission-footer",
            )

    def on_mount(self) -> None:
        self._render_tab()
        self.query_one("#permission-rule-options", OptionList).focus()
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    def _render_tab(self) -> None:
        tabs = Text()
        for index, behavior in enumerate(self.BEHAVIORS):
            tabs.append(
                f" {self.LABELS[behavior]} ",
                style="reverse bold" if index == self.tab else "dim",
            )
            if index < 2:
                tabs.append("  ")
        self.query_one("#permission-rule-tabs", Static).update(tabs)
        self.query_one("#permission-rule-description", Static).update(
            self.DESCRIPTIONS[self.behavior]
        )
        self._render_rules()

    def _render_rules(self) -> None:
        query = self.query_one("#permission-rule-input", Input).value.strip().lower()
        values = sorted(
            value for value in self.rules.get(self.behavior, set()) if not query or query in value
        )
        options = self.query_one("#permission-rule-options", OptionList)
        options.clear_options()
        options.add_option(Option("＋ 添加新规则", id="__add__"))
        options.add_options([Option(value, id=value) for value in values])
        options.highlighted = 0

    @on(Input.Changed, "#permission-rule-input")
    def handle_rule_query(self, event: Input.Changed) -> None:
        if not self.adding:
            self._render_rules()

    @on(Input.Submitted, "#permission-rule-input")
    def handle_rule_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip().lower()
        if self.adding:
            if not re.fullmatch(r"[a-z0-9_.:*/-]+", value):
                self.notify("规则只能包含工具名字符，*表示全部工具。", severity="warning")
                return
            for rules in self.rules.values():
                rules.discard(value)
            self.rules[self.behavior].add(value)
            self.adding = False
            event.input.value = ""
            event.input.placeholder = "输入关键词搜索；按A添加规则"
        self._render_rules()
        self.query_one("#permission-rule-options", OptionList).focus()

    @on(OptionList.OptionSelected, "#permission-rule-options")
    def handle_rule_selected(self, event: OptionList.OptionSelected) -> None:
        if str(event.option.id or "") == "__add__":
            self.action_add_rule()

    def action_previous_tab(self) -> None:
        self.tab = (self.tab - 1) % len(self.BEHAVIORS)
        self._render_tab()

    def action_next_tab(self) -> None:
        self.tab = (self.tab + 1) % len(self.BEHAVIORS)
        self._render_tab()

    def action_search(self) -> None:
        field = self.query_one("#permission-rule-input", Input)
        if self.focused is field:
            field.insert("/")
            return
        self.adding = False
        field.focus()

    def action_add_rule(self) -> None:
        field = self.query_one("#permission-rule-input", Input)
        if self.focused is field:
            field.insert("a")
            return
        self.adding = True
        field.value = ""
        field.placeholder = f"添加到{self.LABELS[self.behavior]}，输入工具名后回车"
        field.focus()

    def action_delete_rule(self) -> None:
        field = self.query_one("#permission-rule-input", Input)
        if self.focused is field:
            field.insert("d")
            return
        options = self.query_one("#permission-rule-options", OptionList)
        index = options.highlighted
        if index is None or index <= 0:
            return
        option = options.get_option_at_index(index)
        value = str(option.id or "")
        if value and value in self.rules.get(self.behavior, set()):
            self.rules[self.behavior].remove(value)
            self._render_rules()
            self.notify(f"已删除规则：{value}")

    def action_close(self) -> None:
        field = self.query_one("#permission-rule-input", Input)
        if self.focused is field and (self.adding or field.value):
            self.adding = False
            field.value = ""
            field.placeholder = "输入关键词搜索；按A添加规则"
            self._render_rules()
            self.query_one("#permission-rule-options", OptionList).focus()
            return
        self.dismiss({key: set(values) for key, values in self.rules.items()})


class ApprovalScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("enter", "allow", "允许本次", show=False),
        Binding("y", "allow", "允许本次", show=False),
        Binding("d", "deny", "拒绝", show=False),
        Binding("n", "deny", "拒绝", show=False),
        Binding("s", "allow_session", "本次会话允许", show=False),
        Binding("escape", "deny", "返回", show=False),
    ]

    def __init__(self, tool_name: str, risk: str, detail: str = "") -> None:
        self.tool_name = tool_name
        self.risk = risk
        self.detail = detail
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="approval-dialog"):
            yield Static("需要确认", classes="approval-title")
            yield Static(
                f"{self.tool_name}准备执行{self.risk or '写入'}操作。",
                classes="approval-body",
            )
            if self.detail:
                yield Static(self.detail, classes="approval-detail")
            with Horizontal(classes="approval-actions"):
                yield Button("允许本次", id="allow", variant="primary")
                yield Button("本次会话允许", id="allow-session")
                yield Button("拒绝", id="deny")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        decision = {
            "allow": "allow_once",
            "allow-session": "allow_session",
        }.get(str(event.button.id), "deny")
        self.dismiss(decision)

    def action_allow(self) -> None:
        self.dismiss("allow_once")

    def action_deny(self) -> None:
        self.dismiss("deny")

    def action_allow_session(self) -> None:
        self.dismiss("allow_session")


class WorkspaceUndoScreen(ModalScreen[dict[str, str] | None]):
    BINDINGS = [
        Binding("enter", "confirm", "确认撤销", show=False),
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(self, path: str, operation_id: str, run_id: str) -> None:
        self.path = redact_public_detail(path or "未命名文件", limit=500) or "未命名文件"
        self.operation_id = str(operation_id or "").strip()[:200]
        self.run_id = str(run_id or "").strip()[:200]
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="workspace-undo-dialog"):
            yield Static("撤销文件变更", classes="approval-title")
            yield Static(
                f"将把{self.path}恢复到这次Agent操作之前。",
                classes="approval-body",
            )
            yield Static(
                f"操作：{self.operation_id}",
                classes="approval-detail",
            )
            with Horizontal(classes="approval-actions"):
                yield Button(
                    "确认撤销",
                    id="workspace-undo-confirm",
                    variant="warning",
                )
                yield Button("取消", id="workspace-undo-cancel")

    def on_mount(self) -> None:
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        if str(event.button.id or "") == "workspace-undo-confirm":
            self.action_confirm()
        else:
            self.action_cancel()

    def action_confirm(self) -> None:
        self.dismiss(
            {
                "operationId": self.operation_id,
                "runId": self.run_id,
            }
        )

    def action_cancel(self) -> None:
        self.dismiss(None)


class QuestionScreen(ModalScreen[dict[str, Any] | None]):
    """Structured prompt for an Agent user-question interrupt.

    The Ink client renders these prompts inline, while Textual needs a modal
    surface to keep keyboard focus inside the pending interaction.  The
    screen deliberately returns the same small payload accepted by
    ``TuiBackend.answer_question`` so local and remote runs share one path.
    """

    CUSTOM_OPTION_ID = "__custom__"
    BINDINGS = [
        Binding("ctrl+enter", "submit", "提交", show=False),
        Binding("ctrl+u", "focus_custom", "自定义回答", show=False),
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(
        self,
        header: Any,
        question: Any,
        options: Any,
        allow_custom: bool = True,
        *,
        question_id: Any = "",
    ) -> None:
        self.header = redact_public_detail(header or "需要回答", limit=80) or "需要回答"
        self.question = (
            redact_public_detail(question or "请选择下一步。", limit=600)
            or "请选择下一步。"
        )
        self.allow_custom = bool(allow_custom)
        self.question_id = str(question_id or "").strip()[:160]
        self.options = self._normalize_options(options)
        self._submitted = False
        super().__init__()

    @staticmethod
    def _normalize_options(value: Any) -> list[dict[str, str]]:
        source = value if isinstance(value, (list, tuple)) else []
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(source[:4]):
            if isinstance(item, dict):
                raw_value = str(item.get("value") or item.get("label") or "").strip()
                raw_label = str(item.get("label") or raw_value or "").strip()
                raw_description = str(item.get("description") or "").strip()
            else:
                raw_value = str(item or "").strip()
                raw_label = raw_value
                raw_description = ""
            if not raw_value and not raw_label:
                continue
            raw_value = raw_value[:120] or raw_label[:120]
            label = redact_public_detail(
                raw_label or raw_value or f"选项{index + 1}",
                limit=120,
            ) or f"选项{index + 1}"
            description = redact_public_detail(raw_description, limit=180)
            normalized.append(
                {
                    "value": raw_value,
                    "label": label,
                    "description": description,
                }
            )
        return normalized

    def compose(self) -> ComposeResult:
        with Container(id="question-dialog"):
            yield Static(self.header, classes="question-title")
            yield Static(self.question, classes="question-body")
            yield OptionList(id="question-options", compact=True)
            if self.allow_custom:
                yield Input(
                    placeholder="选择“自定义回答”后，在这里输入…",
                    id="question-custom-input",
                )
            with Horizontal(classes="question-actions"):
                yield Button("提交回答", id="question-submit", variant="primary")
                yield Button("取消并停止", id="question-cancel")
            yield Static(
                "↑↓选择 · Enter提交 · Ctrl+U自定义 · Esc取消并停止",
                classes="question-footer",
            )

    def on_mount(self) -> None:
        options = self.query_one("#question-options", OptionList)
        options.add_options(
            [
                Option(
                    Text.assemble(
                        (item["label"], "bold"),
                        (
                            f"  {item['description']}"
                            if item["description"]
                            else "",
                            "dim",
                        ),
                    ),
                    id=f"option:{index}",
                )
                for index, item in enumerate(self.options)
            ]
        )
        if self.allow_custom:
            options.add_option(
                Option(
                    Text.assemble(
                        ("自定义回答", "bold"),
                        ("  输入自己的答案", "dim"),
                    ),
                    id=self.CUSTOM_OPTION_ID,
                )
            )
        if not options.option_count:
            options.add_option(Option("没有可用选项，请按Esc停止任务。", disabled=True))
        options.highlighted = 0
        options.focus()
        self.set_class(self.size.width < 64, "narrow")

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 64, "narrow")

    def _selected_option(self) -> tuple[str, dict[str, str] | None]:
        options = self.query_one("#question-options", OptionList)
        index = options.highlighted
        if index is None or index < 0 or index >= options.option_count:
            return "", None
        option = options.get_option_at_index(index)
        option_id = str(option.id or "")
        if option_id == self.CUSTOM_OPTION_ID:
            return self.CUSTOM_OPTION_ID, None
        if option_id.startswith("option:"):
            try:
                option_index = int(option_id.split(":", 1)[1])
            except (TypeError, ValueError):
                return "", None
            if 0 <= option_index < len(self.options):
                return option_id, self.options[option_index]
        return "", None

    def _submit_answer(self, *, custom: bool = False) -> None:
        if self._submitted:
            return
        selected_id, selected = self._selected_option()
        custom_selected = custom or selected_id == self.CUSTOM_OPTION_ID
        if custom_selected:
            if not self.allow_custom:
                return
            field = self.query_one("#question-custom-input", Input)
            answer = field.value.strip()
            if not answer:
                field.focus()
                self.notify("请输入自定义回答后再提交。", severity="warning")
                return
            selected_options: list[str] = []
        elif selected is not None:
            answer = selected["value"].strip()
            selected_options = [answer] if answer else []
        else:
            self.notify("请先选择一个回答。", severity="warning")
            return
        if not answer:
            self.notify("请先选择或输入回答。", severity="warning")
            return
        self._submitted = True
        self.dismiss(
            {
                "answer": answer[:4000],
                "selectedOptions": selected_options[:4],
            }
        )

    @on(OptionList.OptionSelected, "#question-options")
    def handle_selected(self, event: OptionList.OptionSelected) -> None:
        if str(event.option.id or "") == self.CUSTOM_OPTION_ID:
            if self.allow_custom:
                self.query_one("#question-custom-input", Input).focus()
            return
        self._submit_answer()

    @on(Input.Submitted, "#question-custom-input")
    def handle_custom_submitted(self, event: Input.Submitted) -> None:
        self._submit_answer(custom=True)

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        button_id = str(event.button.id or "")
        if button_id == "question-cancel":
            self.action_cancel()
        elif button_id == "question-submit":
            self._submit_answer()

    def action_submit(self) -> None:
        self._submit_answer()

    def action_focus_custom(self) -> None:
        if self.allow_custom:
            self.query_one("#question-custom-input", Input).focus()

    def action_cancel(self) -> None:
        if not self._submitted:
            self.dismiss(None)


class KnowFlowTui(App[None]):
    CSS_PATH = "knowflow.tcss"
    TITLE = "AgentLens"
    COMMAND_PALETTE_BINDING = "ctrl+p"
    BINDINGS = [
        Binding("ctrl+c", "interrupt", "中断/退出", show=True),
        Binding("ctrl+l", "clear", "清屏", show=True),
        Binding("ctrl+n", "new", "新会话", show=True),
        Binding("ctrl+o", "toggle_details", "展开/收起过程", show=True),
        Binding("ctrl+s", "stash", "暂存/恢复输入", show=False),
        Binding("ctrl+t", "tasks", "任务队列", show=False),
        Binding(
            "ctrl+p",
            "slash_commands",
            "命令面板",
            show=False,
            priority=True,
        ),
        Binding(
            "shift+tab",
            "cycle_permission_mode",
            "切换权限",
            show=False,
            priority=True,
        ),
        Binding("shift+enter", "newline", "换行", show=False),
        Binding("escape", "focus_composer", "输入", show=False),
    ]

    def __init__(
        self,
        backend: TuiBackend,
        *,
        assume_yes: bool = False,
        startup_action: str = "",
    ) -> None:
        self.backend = backend
        self.assume_yes = assume_yes
        normalized_startup_action = str(startup_action or "").strip().lower()
        self.startup_action = (
            normalized_startup_action
            if normalized_startup_action in {"resume", "continue"}
            else ""
        )
        self.running = False
        self._restore_in_progress = False
        self.streamed = False
        self.pending_execution: AgentExecution | None = None
        self.started_at: float | None = None
        self.current_phase = "就绪"
        self.session = TuiSessionState()
        self.commands: tuple[SlashCommand, ...] = COMMANDS
        self.history_store = PromptHistoryStore(
            local_data_dir() / "history.jsonl"
        )
        self.activity_expanded = False
        self.current_approval_tool = ""
        self.current_approval_policy = ""
        self.current_run_id: str | None = None
        self.current_approval_id: str | None = None
        self.current_question_id: str | None = None
        self._approval_in_progress = False
        self._question_in_progress = False
        self._stream_failure_reported = False
        self._queue_manager_previous_pause: bool | None = None
        try:
            workspace_status = self.backend.workspace_status()
        except Exception:
            workspace_status = {}
        self.workspace = str(
            workspace_status.get("cwd")
            or workspace_status.get("projectRoot")
            or Path.cwd()
        )
        self.command_handlers: dict[str, Any] = {
            "/help": self._cmd_help,
            "/about": self._cmd_about,
            "/version": self._cmd_version,
            "/new": self._cmd_new,
            "/clear": self._cmd_clear,
            "/model": self._cmd_model,
            "/tools": self._cmd_tools,
            "/skills": self._cmd_skills,
            "/mcp": self._cmd_mcp,
            "/memory": self._cmd_memory,
            "/status": self._cmd_status,
            "/workspace": self._cmd_workspace,
            "/cd": self._cmd_cd,
            "/doctor": self._cmd_doctor,
            "/diff": self._cmd_diff,
            "/undo": self._cmd_undo,
            "/permissions": self._cmd_permissions,
            "/tasks": self._cmd_tasks,
            "/history": self._cmd_history,
            "/resume": self._cmd_resume,
            "/continue": self._cmd_continue,
            "/retry": self._cmd_retry,
            "/update": self._cmd_update,
            "/exit": self._cmd_exit,
        }
        super().__init__()

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="transcript")
        with Vertical(id="bottom-pane"):
            with Horizontal(id="composer-row"):
                yield Static("❯", id="composer-prefix")
                yield Composer()
            yield HistorySearchBar()
            yield QueuePreview()
            yield CommandMenu()
            with Horizontal(id="prompt-footer"):
                yield Static("输入 / 查看命令", id="run-status")
                yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        await self.query_one(TranscriptView).show_welcome(
            version=_cli_release(),
            model=self.backend.model_label,
            workspace=self.workspace,
        )
        self.query_one(Composer).focus()
        self.query_one(Composer).set_history(self.history_store.load())
        self.query_one(CommandMenu).set_commands(self.commands)
        self.load_command_catalog()
        self.set_interval(0.25, self._tick_elapsed)
        self._apply_viewport_class(self.size.width)
        self._refresh_status_bar()
        startup_action = self.startup_action
        self.startup_action = ""
        if startup_action == "resume":
            self.call_after_refresh(self._open_session_picker)
        elif startup_action == "continue":
            await self._restore_latest_session()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_viewport_class(event.size.width)

    def _apply_viewport_class(self, width: int) -> None:
        self.screen.set_class(width < 64, "narrow")

    @on(Composer.CommandQuery)
    async def handle_command_query(self, message: Composer.CommandQuery) -> None:
        menu = self.query_one(CommandMenu)
        await menu.update_query(message.value)
        self.query_one(Composer).command_menu_open = bool(menu.matches)

    @on(Composer.CommandMove)
    async def handle_command_move(self, message: Composer.CommandMove) -> None:
        await self.query_one(CommandMenu).move(message.delta)

    @on(Composer.CommandAccepted)
    async def handle_command_accepted(self) -> None:
        menu = self.query_one(CommandMenu)
        command = menu.selected_command
        if command is None:
            return
        menu.record_usage(command)
        composer = self.query_one(Composer)
        if command.requires_arguments:
            composer.load_text(f"{command.value} ")
            await menu.hide()
            composer.command_menu_open = False
            return
        composer.load_text(command.value)
        if composer.command_menu_open:
            await menu.hide()
            composer.command_menu_open = False
        await self._submit()

    @on(Composer.CommandDismissed)
    async def handle_command_dismissed(self) -> None:
        await self.query_one(CommandMenu).hide()
        self.query_one(Composer).command_menu_open = False

    @on(Composer.Submitted)
    async def handle_composer_submitted(self) -> None:
        await self._submit()

    @on(Composer.HistoryRequested)
    def handle_history_requested(self) -> None:
        composer = self.query_one(Composer)
        self.query_one(HistorySearchBar).open(
            composer.prompt_history,
            composer.text,
        )

    @on(HistorySearchBar.Preview)
    def handle_history_preview(self, message: HistorySearchBar.Preview) -> None:
        self.query_one(Composer).load_text(message.value)

    @on(HistorySearchBar.Accepted)
    def handle_history_accepted(self) -> None:
        self.query_one(HistorySearchBar).close()
        self.query_one(Composer).focus()

    @on(HistorySearchBar.Cancelled)
    def handle_history_cancelled(self) -> None:
        bar = self.query_one(HistorySearchBar)
        original = bar.original
        bar.close()
        self.query_one(Composer).load_text(original)
        self.query_one(Composer).focus()

    def on_command_catalog_loaded(self, message: CommandCatalogLoaded) -> None:
        dynamic = [
            SlashCommand(
                str(item.get("value") or ""),
                redact_public_detail(
                    item.get("description") or "Agent扩展",
                    limit=160,
                ),
                source=str(item.get("source") or "dynamic"),
                argument_hint="<任务>",
            )
            for item in message.items
            if str(item.get("value") or "").startswith("/")
        ]
        self.commands = merge_commands(COMMANDS, dynamic)
        self.query_one(CommandMenu).set_commands(self.commands)

    @work(exclusive=True, thread=True, group="command-catalog")
    def load_command_catalog(self) -> None:
        try:
            items = self.backend.command_catalog()
        except Exception:
            items = []
        self.post_message(CommandCatalogLoaded(items))

    async def _submit(self) -> None:
        composer = self.query_one(Composer)
        display_question = composer.text.strip()
        question = composer.expanded_text().strip()
        if not display_question or not question:
            return
        if self._restore_in_progress:
            self.notify("正在打开历史会话，请稍候。", severity="warning")
            return
        composer.remember(display_question)
        if not self.history_store.append(display_question):
            self.notify(
                "输入历史无法写入，本次会话仍可继续。",
                severity="warning",
            )
        composer.clear()
        composer.pasted_contents.clear()
        dynamic = find_command(
            parse_command(display_question)[0],
            self.commands,
        )
        if dynamic is not None and dynamic.source != "builtin":
            _token, args = parse_command(question)
            task = " ".join(args).strip()
            if not task:
                await self.query_one(TranscriptView).add_notice(
                    f"请在{dynamic.value}后输入要完成的任务。"
                )
                return
            target = dynamic.value.removeprefix("/").split(":", 1)[-1]
            question = (
                f"请使用{dynamic.source} {target}完成以下任务：{task}"
            )
        elif await self._handle_command(display_question):
            return
        if self.running:
            self.session.enqueue(
                question,
                display_text=display_question,
                priority="next",
            )
            self._refresh_status_bar()
            return
        await self._start_turn(question, display_question=display_question)

    async def _start_turn(
        self,
        question: str,
        *,
        display_question: str | None = None,
    ) -> None:
        transcript = self.query_one(TranscriptView)
        await transcript.add_user(display_question or question)
        self.session.last_prompt = QueuedPrompt(
            text=question,
            display_text=display_question or question,
        )
        await transcript.begin_run()
        await transcript.set_activity_expanded(self.activity_expanded)
        self.streamed = False
        self._stream_failure_reported = False
        self.running = True
        self.session.reset_run()
        self.started_at = monotonic()
        self._set_status("分析任务")
        self.execute_turn(question)
        self._refresh_status_bar()

    async def _handle_command(self, value: str) -> bool:
        if not value.startswith("/"):
            return False
        token, args = parse_command(value)
        if not token:
            return False

        command_key = canonical_command(token, self.commands)
        command_definition = find_command(command_key, self.commands)
        if command_definition is None:
            await self.query_one(TranscriptView).add_notice(
                f"未知命令：{value}。输入 / 查看支持命令。"
            )
            return True
        handler = self.command_handlers.get(command_key)
        if handler is None:
            await self.query_one(TranscriptView).add_notice(
                f"{command_key} 当前无处理入口，请使用子命令版本。"
            )
            return True
        return bool(await handler(list(args)))

    async def _cmd_help(self, args: list[str]) -> bool:
        if not args:
            self.push_screen(CommandBrowserScreen(self.commands))
            return True
        part = args[0].lower().strip()
        if part == "commands":
            self.push_screen(CommandBrowserScreen(self.commands))
            return True
        if part == "shortcuts":
            await self.query_one(TranscriptView).add_notice(
                "快捷键：Ctrl+P 命令面板, Ctrl+L清屏, Ctrl+N新会话, "
                "Ctrl+O展开过程, Ctrl+R搜索历史, Ctrl+S暂存输入, "
                "Ctrl+T任务队列, Shift+Tab切换权限, Shift+Enter换行。"
            )
            return True
        if part == "tui":
            await self.query_one(TranscriptView).add_notice(
                "TUI提示：输入/显示候选，↑↓切换，Tab/Enter确认。"
            )
            return True
        await self.query_one(TranscriptView).add_notice(
            f"未知help参数：{part}。可用：commands、shortcuts、tui。"
        )
        return True

    async def _cmd_about(self, args: list[str]) -> bool:
        runtime = "本地" if self.backend.remote_client is None else "远程"
        await self.query_one(TranscriptView).add_notice(
            f"AgentLens TUI · 模式：{runtime} · 模型：{self.backend.model_label} "
            f"· 工作目录：{self.workspace}"
        )
        return True

    async def _cmd_version(self, args: list[str]) -> bool:
        await self.query_one(TranscriptView).add_notice(
            f"AgentLens CLI 当前版本 v{_cli_release()}"
        )
        return True

    async def _cmd_update(self, args: list[str]) -> bool:
        await self.query_one(TranscriptView).add_notice(
            "更新CLI：执行 `agentlens update`（与主程序版本同步）。"
        )
        return True

    async def _cmd_new(self, args: list[str]) -> bool:
        await self.action_new()
        return True

    async def _cmd_clear(self, args: list[str]) -> bool:
        await self.action_clear()
        return True

    async def _cmd_model(self, args: list[str]) -> bool:
        if not args:
            if self.backend.remote_client is not None:
                await self.query_one(TranscriptView).add_notice(
                    f"当前模型：{self.backend.model_id or '默认'}。"
                )
            else:
                await self.query_one(TranscriptView).add_notice(
                    f"当前模型：{self.backend.model_label}。"
                )
            return True
        part = args[0].lower().strip()
        if part == "list":
            if self.backend.remote_client is None:
                await self.query_one(TranscriptView).add_notice(
                    "本地模式请先执行 agentlens configure。"
                )
                return True
            await self._cmd_model_list_remote()
            return True
        if part == "use":
            if self.backend.remote_client is None:
                await self.query_one(TranscriptView).add_notice(
                    "本地模式不支持在会话内切换模型ID。请重新配置 agentlens configure。"
                )
                return True
            if len(args) < 2:
                await self.query_one(TranscriptView).add_notice(
                    "使用示例：/model use <模型ID>"
                )
                return True
            try:
                self.backend.model_id = int(args[1])
            except ValueError:
                await self.query_one(TranscriptView).add_notice("模型ID必须是整数。")
                return True
            self.backend.session_id = None
            await self.query_one(TranscriptView).add_notice(
                f"已切换会话模型到 #{self.backend.model_id}，新会话已开启。"
            )
            return True
        if part == "config":
            await self.query_one(TranscriptView).add_notice(
                "模型配置请使用 agentlens configure，或在 /model list 后在网页调整。"
            )
            return True
        await self.query_one(TranscriptView).add_notice(
            f"未知参数：{part}。可用参数：list、config。"
        )
        return True

    async def _cmd_status(self, args: list[str]) -> bool:
        permission_label = PERMISSION_MODE_BY_ID[
            self.session.permission_mode
        ][2]
        await self.query_one(TranscriptView).add_notice(
            f"模型：{self.backend.model_label}；目录：{self.workspace}；"
            f"状态：{self.current_phase}；等待任务："
            f"{len(self.session.queued_questions)}；队列："
            f"{'已暂停' if self.session.queue_paused else '自动继续'}；"
            f"权限：{permission_label}。"
        )
        return True

    async def _cmd_workspace(self, args: list[str]) -> bool:
        transcript = self.query_one(TranscriptView)
        path = " ".join(args).strip()
        if len(path) >= 2 and path[0] == path[-1] and path[0] in {'"', "'"}:
            path = path[1:-1]
        if path and self.running:
            await transcript.add_notice(
                "当前任务尚未结束，请先完成或取消后再切换工作区。",
                error=True,
            )
            return True
        try:
            result = (
                await asyncio.to_thread(self.backend.workspace_switch_root, path)
                if path
                else await asyncio.to_thread(self.backend.workspace_status)
            )
        except Exception as exc:
            await transcript.add_recovery(
                "工作区未切换",
                redact_public_detail(exc, limit=240),
                "确认目录存在且可访问后重试 /workspace <项目目录>。",
                error=True,
            )
            return True
        next_workspace = str(
            result.get("cwd") or result.get("projectRoot") or self.workspace
        )
        if path:
            self.workspace = next_workspace
            self.session.reset_session()
            self.pending_execution = None
            self.current_run_id = None
            self.current_approval_id = None
            self.current_question_id = None
            self._set_status("工作区已切换")
        else:
            self.workspace = next_workspace
            self._refresh_status_bar()
        message = str(result.get("message") or "").strip()
        await transcript.add_notice(message or f"当前工作区：{self.workspace}")
        self.query_one(Composer).focus()
        return True

    async def _cmd_cd(self, args: list[str]) -> bool:
        transcript = self.query_one(TranscriptView)
        if self.running:
            await transcript.add_notice(
                "当前任务尚未结束，请先完成或取消后再切换目录。",
                error=True,
            )
            return True
        path = " ".join(args).strip()
        if len(path) >= 2 and path[0] == path[-1] and path[0] in {'"', "'"}:
            path = path[1:-1]
        try:
            result = await asyncio.to_thread(
                self.backend.workspace_change_directory,
                path,
            )
        except Exception as exc:
            await transcript.add_recovery(
                "工作目录未切换",
                redact_public_detail(exc, limit=240),
                "目录必须存在于当前工作区边界内。",
                error=True,
            )
            return True
        self.workspace = str(
            result.get("cwd") or result.get("projectRoot") or self.workspace
        )
        self._set_status("工作目录已切换")
        await transcript.add_notice(f"当前工作目录：{self.workspace}")
        self.query_one(Composer).focus()
        return True

    async def _cmd_doctor(self, args: list[str]) -> bool:
        transcript = self.query_one(TranscriptView)
        await transcript.add_notice("正在检查SRT沙箱与本地执行环境…")
        checks = await asyncio.to_thread(self.backend.sandbox_diagnostics)
        lines = []
        for item in checks:
            marker = "✓" if item.get("ready") else "×"
            detail = redact_public_detail(item.get("detail"), limit=160)
            lines.append(f"{marker} {item.get('name')}: {detail}")
        ready = bool(checks) and all(bool(item.get("ready")) for item in checks)
        lines.append(
            "SRT已可执行shell工具。"
            if ready
            else "按失败项补齐依赖后重新输入/doctor。"
        )
        await transcript.add_notice("\n".join(lines))
        self._set_status("SRT可用" if ready else "SRT诊断未通过")
        return True

    async def _cmd_permissions(self, args: list[str]) -> bool:
        if not args:
            self.push_screen(
                PermissionModeScreen(self.session.permission_mode),
                self._on_permission_mode_result,
            )
            return True
        behavior = str(args[0]).strip().lower()
        if behavior == "rules":
            self.push_screen(
                PermissionRuleScreen(self.session.permission_rules),
                self._on_permission_rules_result,
            )
            return True
        if behavior in {"allow", "ask", "deny"} and len(args) >= 2:
            tool_name = str(args[1]).strip().lower()
            if self.session.set_permission_rule(behavior, tool_name):
                await self.query_one(TranscriptView).add_notice(
                    f"已将{tool_name}设为{behavior.upper()}。"
                )
            return True
        if behavior == "mode" and len(args) >= 2:
            mode = {
                "ask": "ask",
                "edits": "auto_edit",
                "full": "full_access",
            }.get(str(args[1]).strip().lower())
            if mode is not None:
                await self._apply_permission_mode(mode)
                return True
        await self.query_one(TranscriptView).add_notice(
            "用法：/permissions；高级规则可用/permissions rules。"
        )
        return True

    async def _on_permission_mode_result(self, result: str | None) -> None:
        if result == "rules":
            self.push_screen(
                PermissionRuleScreen(self.session.permission_rules),
                self._on_permission_rules_result,
            )
            return
        if result in PERMISSION_MODE_BY_ID:
            await self._apply_permission_mode(result)

    def _on_permission_rules_result(
        self,
        rules: dict[str, set[str]] | None,
    ) -> None:
        if not rules:
            return
        self.session.permission_rules = {
            behavior: set(rules.get(behavior, set()))
            for behavior in ("allow", "ask", "deny")
        }
        total = sum(len(values) for values in self.session.permission_rules.values())
        self.notify(f"权限规则已保存，共{total}条。")

    async def _apply_permission_mode(self, mode: str) -> None:
        if mode not in PERMISSION_MODE_BY_ID:
            return
        self.session.permission_mode = mode
        self.session.session_approvals.clear()
        title, description, short_label = PERMISSION_MODE_BY_ID[mode]
        self._set_status(f"权限：{short_label}")
        await self.query_one(TranscriptView).add_notice(
            f"权限模式已切换为“{title}”：{description}。"
        )

    def _permission_mode_allows(self, event: dict[str, Any]) -> bool:
        mode = self.session.permission_mode
        if mode == "full_access":
            return True
        if mode != "auto_edit":
            return False
        if event.get("destructive") is True:
            return False
        risk = str(event.get("risk") or "unknown").strip().lower()
        return risk in {"write", "edit", "editing", "写入", "编辑"}

    async def _cmd_tools(self, args: list[str]) -> bool:
        if self.backend.remote_client is None:
            status = self.backend.capability_status()
            items = list((status.get("tools") or {}).get("items") or [])
        else:
            items = await self._fetch_remote_list("/api/agent/tools")
            if items is None:
                return True
        tools = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in items
        ]
        await self.query_one(TranscriptView).add_notice(
            "可用工具："
            + ("、".join(tools[:20]) if tools else "无可用工具。")
        )
        if len(tools) > 20:
            await self.query_one(TranscriptView).add_notice(
                f"... 仅展示前20条，剩余{len(tools)-20}条。"
            )
        return True

    async def _cmd_skills(self, args: list[str]) -> bool:
        if self.backend.remote_client is None:
            status = self.backend.capability_status()
            items = list((status.get("skills") or {}).get("items") or [])
        else:
            items = await self._fetch_remote_list("/api/skills/")
            if items is None:
                return True
        names = [
            str(item.get("name") if isinstance(item, dict) else item)
            for item in items
        ]
        await self.query_one(TranscriptView).add_notice(
            "Skills："
            + ("、".join(names[:20]) if names else "无可用技能。")
        )
        if len(names) > 20:
            await self.query_one(TranscriptView).add_notice(
                f"... 仅展示前20条，剩余{len(names)-20}条。"
            )
        return True

    async def _cmd_mcp(self, args: list[str]) -> bool:
        if self.backend.remote_client is None:
            status = self.backend.capability_status()
            items = list((status.get("mcp") or {}).get("servers") or [])
        else:
            items = await self._fetch_remote_list("/api/mcp/servers")
            if items is None:
                return True
        records = []
        for item in items:
            if not isinstance(item, dict):
                continue
            records.append(
                f"{item.get('name') or item.get('slug') or ''} "
                f"· {item.get('status') or 'unknown'}"
            )
        await self.query_one(TranscriptView).add_notice(
            "MCP："
            + ("、".join(records[:20]) if records else "无MCP服务。")
        )
        if len(records) > 20:
            await self.query_one(TranscriptView).add_notice(
                f"... 仅展示前20条，剩余{len(records)-20}条。"
            )
        return True

    async def _cmd_memory(self, args: list[str]) -> bool:
        if self.backend.remote_client is None:
            status = self.backend.capability_status()
            memory = dict(status.get("memory") or {})
            if not memory.get("configured"):
                await self.query_one(TranscriptView).add_notice(
                    "长期记忆未配置。运行agentlens memory configure开始配置。"
                )
                return True
            if not memory.get("enabled"):
                await self.query_one(TranscriptView).add_notice(
                    "长期记忆已配置但未启用。运行agentlens memory enable启用。"
                )
                return True
            items = list(memory.get("items") or [])
        else:
            items = await self._fetch_remote_list(
                "/api/memories",
                params={"limit": 20},
            )
            if items is None:
                return True
        if not items:
            await self.query_one(TranscriptView).add_notice("暂无记忆记录。")
            return True
        await self.query_one(TranscriptView).add_notice("最近记忆：")
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            content = str(
                item.get("memory")
                or item.get("content")
                or item.get("summary")
                or ""
            )
            await self.query_one(TranscriptView).add_notice(
                f"{index}. {content[:64]}{'...' if len(content) > 64 else ''}"
            )
        return True

    async def _cmd_model_list_remote(self) -> None:
        items = await self._fetch_remote_list(
            "/api/model-configs",
            params={"modelType": "chat"},
        )
        if items is None:
            return
        if not items:
            await self.query_one(TranscriptView).add_notice("未查询到聊天模型。")
            return
        entries = []
        for item in items:
            if not isinstance(item, dict):
                continue
            entries.append(
                f"#{item.get('id')} "
                f"{item.get('name') or item.get('configName') or ''} "
                f"{item.get('model') or item.get('modelName') or item.get('model_name')}"
                f" · {item.get('apiMode') or item.get('api_mode') or item.get('protocol')}"
            )
        if not entries:
            await self.query_one(TranscriptView).add_notice("当前无可用模型。")
            return
        await self.query_one(TranscriptView).add_notice("模型清单：")
        for entry in entries[:20]:
            await self.query_one(TranscriptView).add_notice(entry)
        if len(entries) > 20:
            await self.query_one(TranscriptView).add_notice(
                f"... 仅展示前20条，剩余{len(entries)-20}条。"
            )

    async def _fetch_remote_list(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]] | list[str] | None:
        try:
            payload = self.backend.remote_client.request("GET", path, params=params or {})
        except Exception as exc:
            await self.query_one(TranscriptView).add_notice(
                f"查询失败：{redact_public_detail(exc, limit=220)}",
                error=True,
            )
            return None
        if isinstance(payload, list):
            return payload
        return []

    async def _cmd_tasks(self, args: list[str]) -> bool:
        part = args[0].lower().strip() if args else "open"
        if part == "open":
            self._open_queue_manager()
            return True
        if part == "remove":
            if len(args) < 2 or not args[1].isdigit():
                await self.query_one(TranscriptView).add_notice(
                    "使用示例：/tasks remove <序号>"
                )
                return True
            removed = self.session.remove_queued(int(args[1]) - 1)
            await self.query_one(TranscriptView).add_notice(
                (
                    f"已移除：{redact_public_detail(removed.display_text, limit=100)}"
                    if removed is not None
                    else "没有这个等待任务。"
                )
            )
            self._refresh_status_bar()
            return True
        if part == "clear":
            count = len(self.session.prompt_queue)
            self.session.prompt_queue.clear()
            await self.query_one(TranscriptView).add_notice(
                f"已清空{count}个等待任务。"
            )
            self._refresh_status_bar()
            return True
        if part not in {"list"}:
            await self.query_one(TranscriptView).add_notice(
                "可用参数：list、remove、clear。"
            )
            return True
        queued = self.session.ordered_queue()
        await self.query_one(TranscriptView).add_notice(
            "等待任务："
            + (
                "；".join(
                    f"{index + 1}. [{item.priority}] "
                    f"{redact_public_detail(item.display_text, limit=100)}"
                    for index, item in enumerate(queued)
                )
                if queued
                else "无。"
            )
        )
        return True

    async def _cmd_continue(self, args: list[str]) -> bool:
        if self.running:
            self.notify("当前任务仍在执行。", severity="warning")
        elif not self.session.queued_questions:
            await self.query_one(TranscriptView).add_notice("等待队列为空。")
        else:
            self.session.queue_paused = False
            self._run_next_queued()
        return True

    async def _cmd_retry(self, args: list[str]) -> bool:
        if self.running:
            self.notify("当前任务仍在执行。", severity="warning")
            return True
        prompt = self.session.last_prompt
        if prompt is None:
            await self.query_one(TranscriptView).add_notice(
                "没有可重新执行的任务。"
            )
            return True
        self.session.queue_paused = False
        await self._start_turn(
            prompt.text,
            display_question=prompt.display_text,
        )
        return True

    async def _cmd_diff(self, args: list[str]) -> bool:
        path = " ".join(args).strip() or None
        transcript = self.query_one(TranscriptView)
        running_snapshot = self.running
        try:
            result = await asyncio.to_thread(self.backend.workspace_diff, path)
        except Exception as exc:
            await transcript.add_recovery(
                "无法读取文件变更",
                redact_public_detail(exc, limit=240),
                "确认当前会话已运行文件操作后重试 /diff。",
                error=True,
            )
            return True
        files = [
            item
            for item in list(result.get("files") or [])
            if isinstance(item, dict)
        ]
        if not files:
            await transcript.add_notice(
                (
                    "任务仍在执行；当前Diff快照还没有文件变更。"
                    if running_snapshot
                    else f"{path}没有可审阅的文件变更。"
                    if path
                    else "当前Agent运行没有文件变更。"
                )
            )
            return True
        if running_snapshot:
            await transcript.add_notice(
                "任务仍在执行；以下是当前Diff快照，完成后再次运行 /diff 查看最终结果。"
            )
        await transcript.add_workspace_diff(result)
        return True

    async def _cmd_undo(self, args: list[str]) -> bool:
        transcript = self.query_one(TranscriptView)
        if self.running:
            await transcript.add_notice(
                "当前任务仍在执行；结束或取消后才能撤销文件变更。",
                error=True,
            )
            return True
        if len(args) > 1:
            await transcript.add_notice(
                "使用示例：/undo [operation-id]",
                error=True,
            )
            return True
        operation_id = str(args[0] if args else "").strip()
        try:
            result = await asyncio.to_thread(self.backend.workspace_diff)
        except Exception as exc:
            await transcript.add_recovery(
                "无法准备撤销",
                redact_public_detail(exc, limit=240),
                "运行 /diff 查看当前会话的可撤销项。",
                error=True,
            )
            return True
        files = [
            item
            for item in list(result.get("files") or [])
            if (
                isinstance(item, dict)
                and item.get("operationId")
                and not item.get("reverted")
            )
        ]
        target = (
            next(
                (
                    item
                    for item in files
                    if str(item.get("operationId") or "") == operation_id
                ),
                None,
            )
            if operation_id
            else (files[-1] if files else None)
        )
        if target is None:
            await transcript.add_notice(
                (
                    f"未找到变更{redact_public_detail(operation_id, limit=120)}；"
                    "先运行 /diff 查看可撤销项。"
                    if operation_id
                    else "当前Agent运行没有可撤销的文件变更。"
                ),
                error=bool(operation_id),
            )
            return True
        self.push_screen(
            WorkspaceUndoScreen(
                str(target.get("path") or "未命名文件"),
                str(target.get("operationId") or ""),
                str(result.get("runId") or ""),
            ),
            self._on_workspace_undo_result,
        )
        return True

    async def _on_workspace_undo_result(
        self,
        selection: dict[str, str] | None,
    ) -> None:
        self.query_one(Composer).focus()
        if not selection:
            return
        transcript = self.query_one(TranscriptView)
        try:
            result = await asyncio.to_thread(
                self.backend.workspace_undo,
                selection.get("operationId") or None,
                selection.get("runId") or None,
            )
        except Exception as exc:
            await transcript.add_recovery(
                "文件变更未撤销",
                redact_public_detail(exc, limit=240),
                "文件保持不变；运行 /diff 刷新后再试。",
                error=True,
            )
            return
        path = redact_public_detail(result.get("path") or "文件", limit=500) or "文件"
        await transcript.add_notice(
            f"已撤销{path}的这次Agent变更。运行 /diff 查看剩余变更。"
        )

    async def _cmd_history(self, args: list[str]) -> bool:
        part = args[0].lower().strip() if args else "search"
        composer = self.query_one(Composer)
        if part == "clear":
            cleared = self.history_store.clear()
            composer.clear_history()
            await self.query_one(TranscriptView).add_notice(
                (
                    "本地输入历史已清空。"
                    if cleared
                    else "输入历史文件无法删除；已清空本次会话历史。"
                ),
                error=not cleared,
            )
            return True
        if part == "search":
            query = " ".join(args[1:]).strip().lower()
            if not query:
                self.query_one(HistorySearchBar).open(
                    composer.prompt_history,
                    composer.text,
                )
                return True
            matches = [
                item
                for item in reversed(composer.prompt_history)
                if query in item.lower()
            ][:10]
            await self.query_one(TranscriptView).add_notice(
                "历史匹配："
                + (
                    "；".join(
                        redact_public_detail(item, limit=100)
                        for item in matches
                    )
                    if matches
                    else "无。"
                )
            )
            return True
        await self.query_one(TranscriptView).add_notice(
            "可用参数：search、clear。"
        )
        return True

    def _open_session_picker(self, query: str = "") -> None:
        if self.running or self._restore_in_progress:
            self.notify("当前任务尚未结束，暂时不能切换会话。", severity="warning")
            return
        if isinstance(self.screen, SessionPickerScreen):
            self.screen.query_one("#session-picker-search", Input).focus()
            return
        self.push_screen(
            SessionPickerScreen(self.backend, query=query),
            self._on_session_picker_result,
        )

    def _on_session_picker_result(
        self,
        selection: dict[str, Any] | None,
    ) -> None:
        self.query_one(Composer).focus()
        if selection is not None:
            self._queue_session_restore(selection)

    async def _cmd_resume(self, args: list[str]) -> bool:
        if self.running or self._restore_in_progress:
            self.notify("当前任务尚未结束，暂时不能切换会话。", severity="warning")
            return True
        self._open_session_picker(" ".join(args).strip())
        return True

    async def _restore_latest_session(self) -> None:
        if self.running or self._restore_in_progress:
            return
        try:
            try:
                sessions = await asyncio.to_thread(
                    self.backend.list_sessions,
                    100,
                    archived=False,
                )
            except TypeError as exc:
                if "archived" not in str(exc):
                    raise
                sessions = await asyncio.to_thread(self.backend.list_sessions, 100)
        except Exception as exc:
            self._set_status("会话读取失败")
            await self.query_one(TranscriptView).add_recovery(
                "无法读取历史会话",
                redact_public_detail(exc, limit=240),
                "输入/resume重试，或直接输入新的任务。",
                error=True,
            )
            self.query_one(Composer).focus()
            return
        selection = next(
            (
                dict(item)
                for item in (sessions or [])
                if isinstance(item, dict)
                and str(item.get("runId") or item.get("sessionId") or "").strip()
            ),
            None,
        )
        if selection is None:
            self._set_status("已就绪")
            await self.query_one(TranscriptView).add_notice(
                "当前工作区还没有可继续的历史会话。"
            )
            self.query_one(Composer).focus()
            return
        self._queue_session_restore(selection)

    def _queue_session_restore(self, selection: dict[str, Any]) -> None:
        if self.running or self._restore_in_progress:
            self.notify("当前任务尚未结束，暂时不能切换会话。", severity="warning")
            return
        normalized = dict(selection)
        run_id = str(
            normalized.get("runId") or normalized.get("sessionId") or ""
        ).strip()
        if not run_id:
            self.notify("所选会话缺少运行ID。", severity="error")
            return
        normalized["runId"] = run_id
        self._restore_in_progress = True
        self.running = False
        self.pending_execution = None
        self.current_run_id = run_id
        self._stream_failure_reported = False
        title = redact_public_detail(
            normalized.get("title") or "历史会话",
            limit=100,
        ) or "历史会话"
        self._set_status(f"正在打开：{title}")
        self.restore_session_worker(normalized)

    @work(exclusive=True, thread=True, group="session-restore")
    def restore_session_worker(self, selection: dict[str, Any]) -> None:
        events: list[dict[str, Any]] = []
        run_id = str(selection.get("runId") or "").strip()
        try:
            try:
                execution = self.backend.restore_session(
                    run_id,
                    events.append,
                    session_id=str(selection.get("sessionId") or ""),
                    status=str(selection.get("status") or ""),
                )
            except TypeError as exc:
                if not any(
                    marker in str(exc).lower()
                    for marker in ("session_id", "status", "unexpected keyword")
                ):
                    raise
                execution = self.backend.restore_session(run_id, events.append)
            self.post_message(SessionRestored(execution, dict(selection), events))
        except Exception as exc:
            self.post_message(SessionRestoreFailed(dict(selection), exc))

    async def on_session_restored(self, message: SessionRestored) -> None:
        execution = message.execution
        events = list(message.events or execution.events or [])
        if events and not execution.events:
            execution = AgentExecution(
                result=dict(execution.result),
                events=events,
            )
        self._restore_in_progress = False
        self.pending_execution = None
        self.current_approval_id = None
        self.current_question_id = None
        self._approval_in_progress = False
        self._question_in_progress = False
        self._stream_failure_reported = False
        self.streamed = False
        self.session.reset_session()
        result = execution.result if isinstance(execution.result, dict) else {}
        raw_messages = result.get("transcriptMessages") or result.get("messages") or []
        transcript = self.query_one(TranscriptView)
        await transcript.restore_messages(raw_messages)
        last_user = next(
            (
                str(item.get("content") or "").strip()
                for item in reversed(raw_messages if isinstance(raw_messages, list) else [])
                if isinstance(item, dict)
                and str(item.get("role") or "").lower() == "user"
                and str(item.get("content") or "").strip()
            ),
            "",
        )
        if last_user:
            self.session.last_prompt = QueuedPrompt(
                text=last_user,
                display_text=last_user,
            )
        try:
            workspace_status = self.backend.workspace_status()
        except Exception:
            workspace_status = {}
        if isinstance(workspace_status, dict):
            self.workspace = str(
                workspace_status.get("cwd")
                or workspace_status.get("projectRoot")
                or self.workspace
            )
        self.current_run_id = str(
            result.get("runId")
            or message.selection.get("runId")
            or ""
        ).strip() or None
        title = redact_public_detail(
            message.selection.get("title") or "历史会话",
            limit=120,
        ) or "历史会话"
        await transcript.add_notice(f"已打开会话：{title}")
        if events or execution.paused:
            self.running = True
            self.started_at = monotonic()
            await transcript.begin_run()
            await transcript.set_activity_expanded(self.activity_expanded)
            self._set_status("恢复任务")
            for event in events:
                if isinstance(event, dict):
                    await self.on_agent_event_message(AgentEventMessage(event))
            if execution.paused:
                self.on_turn_paused(TurnPaused(execution))
            else:
                await self.on_turn_completed(TurnCompleted(execution))
            return
        answer = str(result.get("answer") or "")
        if answer:
            await transcript.append_assistant(answer)
            transcript.finalize_assistant()
        self.running = False
        self.started_at = None
        self._set_status("已恢复")
        self.query_one(Composer).focus()

    async def on_session_restore_failed(
        self,
        message: SessionRestoreFailed,
    ) -> None:
        self._restore_in_progress = False
        self.running = False
        self.started_at = None
        self.pending_execution = None
        self.current_run_id = None
        self._set_status("恢复失败")
        await self.query_one(TranscriptView).add_recovery(
            "会话未打开",
            redact_public_detail(message.error, limit=300),
            "输入/resume重试，或直接输入新的任务。",
            error=True,
        )
        self.query_one(Composer).focus()

    async def _cmd_exit(self, args: list[str]) -> bool:
        self.exit()
        return True

    @work(exclusive=True, thread=True, group="agent")
    def execute_turn(self, question: str) -> None:
        try:
            execution = self.backend.run(
                question,
                lambda event: self.post_message(AgentEventMessage(event)),
            )
            if execution.paused:
                self.post_message(TurnPaused(execution))
            else:
                self.post_message(TurnCompleted(execution))
        except Exception as exc:
            self.post_message(TurnFailed(exc))

    @work(exclusive=True, thread=True, group="agent-cancel")
    def cancel_turn(self, run_id: str | None) -> None:
        try:
            cancel = getattr(self.backend, "cancel", None)
            sent = bool(cancel(run_id)) if callable(cancel) else False
            self.post_message(CancelRequested(sent))
        except Exception as exc:
            self.post_message(CancelRequested(False, exc))

    @work(exclusive=True, thread=True, group="agent")
    def resume_turn(self, execution: AgentExecution, decision: str) -> None:
        try:
            resolved = self.backend.resolve(
                execution,
                decision,
                lambda event: self.post_message(AgentEventMessage(event)),
            )
            if resolved.paused:
                self.post_message(TurnPaused(resolved))
            else:
                self.post_message(TurnCompleted(resolved))
        except Exception as exc:
            self.post_message(TurnFailed(exc))

    @work(exclusive=True, thread=True, group="agent")
    def answer_turn(
        self,
        execution: AgentExecution,
        answer: dict[str, Any],
    ) -> None:
        try:
            resolved = self.backend.answer_question(
                execution,
                answer,
                lambda event: self.post_message(AgentEventMessage(event)),
            )
            if resolved.paused:
                self.post_message(TurnPaused(resolved))
            else:
                self.post_message(TurnCompleted(resolved))
        except Exception as exc:
            self.post_message(TurnFailed(exc))

    async def on_agent_event_message(self, message: AgentEventMessage) -> None:
        event = message.event
        event_name = agent_event_name(event)
        run = event.get("run")
        run_id = event.get("runId")
        if not run_id and isinstance(run, dict):
            run_id = run.get("id")
        if run_id:
            self.current_run_id = str(run_id)
        transcript = self.query_one(TranscriptView)
        await transcript.update_activity(event)
        if event_name in {"message.delta", "message.completed"}:
            text = str(event.get("text") or event.get("content") or "")
            if text:
                self.streamed = True
                await transcript.append_assistant(text)
            self._set_status("生成回答")
        elif event_name == "model.event":
            self._set_status("生成回答")
        elif event_name == "model.retrying":
            seconds = max(
                0,
                int((int(event.get("retryInMs") or 0) + 999) / 1000),
            )
            attempt = int(event.get("retryAttempt") or 1)
            maximum = int(event.get("maxRetries") or 1)
            error_type = str(event.get("errorType") or "").lower()
            reason = (
                "模型连接超时"
                if "timeout" in error_type
                else (
                    "模型连接失败"
                    if "connect" in error_type
                    else "模型请求失败"
                )
            )
            self._set_status(
                f"{reason}，{seconds}秒后重试（{attempt}/{maximum}）"
            )
        elif event_name.startswith("tool."):
            self.session.record_tool(event)
            title = tool_activity_title(event)
            status = str(
                event.get("normalizedStatus") or event.get("status") or ""
            ).lower()
            if event_name == "tool.started":
                self._set_status(
                    f"等待确认：{title}"
                    if status == "waiting"
                    else f"正在{title}"
                )
            elif event_name == "tool.progress":
                elapsed = event.get("elapsedSeconds")
                suffix = (
                    f"（{float(elapsed):.1f}s，Ctrl+C停止）"
                    if isinstance(elapsed, (int, float))
                    else "（Ctrl+C停止）"
                )
                self._set_status(f"正在{title}{suffix}")
            elif status in {"failed", "error"}:
                self._set_status(f"{title}失败，正在调整")
            else:
                self._set_status(f"{title}完成，继续分析")
        elif event_name.startswith("step."):
            step = event.get("step") if isinstance(event.get("step"), dict) else event
            self._set_status(
                str(step.get("title") or step.get("name") or "执行Agent步骤")
            )
        elif event_name in {"run.plan_created", "run.updated"}:
            self._set_status("更新任务进度")
        elif event_name == "approval.required":
            self._set_status("等待确认")
        elif event_name == "question.required" or event.get(
            "type"
        ) == "user_question_required":
            self._set_status("等待回答")
        elif event_name in {"error.raised", "run.failed"}:
            error = event.get("error")
            detail = (
                error.get("message")
                if isinstance(error, dict)
                else event.get("errorMessage") or event.get("message") or error
            )
            detail = redact_public_detail(detail or "Agent运行失败。", limit=300)
            failure_title, recovery = error_recovery_message(detail)
            if not self._stream_failure_reported:
                await transcript.add_recovery(
                    failure_title,
                    detail,
                    recovery,
                    error=True,
                )
                self._stream_failure_reported = True
            self._set_status(failure_title)
        self._refresh_status_bar()

    async def on_turn_completed(self, message: TurnCompleted) -> None:
        transcript = self.query_one(TranscriptView)
        interrupted = bool(
            self.session.cancel_requested
            or message.execution.result.get("cancelled")
        )
        trace = message.execution.result.get("trace")
        if isinstance(trace, list):
            for step in trace:
                if isinstance(step, dict):
                    await transcript.update_activity(
                        {"type": "agent_step", **step}
                    )
        answer = str(message.execution.result.get("answer") or "")
        if answer and not self.streamed:
            await transcript.append_assistant(answer)
        transcript.finalize_assistant()
        await transcript.finish_run(cancelled=interrupted)
        self.pending_execution = None
        self.current_question_id = None
        self._question_in_progress = False
        self.current_run_id = None
        self.running = False
        self.started_at = None
        self._set_status("已停止" if interrupted else "已完成")
        if interrupted:
            await transcript.add_recovery(
                "任务已中断",
                "当前工具可能已完成部分操作，请先检查结果再重试。",
                "输入新的要求调整方向，或输入/retry重新执行。",
            )
        self.query_one(Composer).focus()
        if interrupted:
            self.session.queue_paused = bool(self.session.prompt_queue)
            if isinstance(self.screen, QueueManagerScreen):
                self._queue_manager_previous_pause = True
        else:
            if isinstance(self.screen, QueueManagerScreen):
                self.session.queue_paused = True
                self._refresh_status_bar()
            else:
                self.session.queue_paused = False
                self._run_next_queued()

    def on_turn_paused(self, message: TurnPaused) -> None:
        self.pending_execution = message.execution
        if message.execution.interrupt_type == "user_question":
            event = next(
                (
                    value
                    for value in reversed(message.execution.events)
                    if value.get("type") == "user_question_required"
                ),
                {},
            )
            question_id = message.execution.question_id or str(
                event.get("questionId") or ""
            ).strip()
            if not question_id:
                self._set_status("问题状态无效")
                self.notify(
                    "Agent返回的问题缺少ID，无法安全恢复。",
                    severity="error",
                )
                return
            if (
                self._question_in_progress
                and self.current_question_id == question_id
            ):
                return
            self.current_question_id = question_id
            self._question_in_progress = True
            self.current_approval_id = None
            self._set_status("等待回答")
            self.push_screen(
                QuestionScreen(
                    event.get("header") or "需要回答",
                    event.get("question") or "请选择下一步。",
                    event.get("options") or [],
                    bool(event.get("allowCustom", True)),
                    question_id=question_id,
                ),
                self._on_question_screen_result,
            )
            return
        event = next(
            (
                value
                for value in reversed(message.execution.events)
                if value.get("type") == "approval_required"
            ),
            {},
        )
        self.current_approval_tool = str(
            event.get("toolName") or "工具调用"
        )
        self.current_approval_policy = self._approval_policy_key(event)
        self.current_approval_id = str(
            event.get("approvalId")
            or event.get("approval_id")
            or event.get("id")
            or ""
        )
        rule_behavior = self.session.permission_behavior(
            self.current_approval_tool
        )
        if rule_behavior == "deny":
            self.current_approval_id = None
            self._approval_decided("deny")
            return
        if rule_behavior == "allow":
            self.current_approval_id = None
            self._approval_decided("allow_once")
            return
        if self.current_approval_policy in self.session.session_approvals:
            self.current_approval_id = None
            self._approval_decided("allow_once")
            return
        if rule_behavior != "ask" and (
            self.assume_yes or self._permission_mode_allows(event)
        ):
            self.current_approval_id = None
            self._approval_decided("allow_once")
            return
        self.push_screen(
            ApprovalScreen(
                self.current_approval_tool,
                str(event.get("risk") or "写入"),
                self._approval_detail(event),
            ),
            self._on_approval_screen_result,
        )

    def _on_approval_screen_result(self, decision: str | None) -> None:
        self._approval_in_progress = False
        if self.current_approval_id is None:
            return
        self._approval_decided(decision)

    def _on_question_screen_result(
        self,
        answer: dict[str, Any] | None,
    ) -> None:
        self._question_in_progress = False
        execution = self.pending_execution
        if execution is None:
            self.current_question_id = None
            return
        self.pending_execution = None
        self.current_question_id = None
        if answer is None:
            run_id = str(execution.result.get("runId") or self.current_run_id or "")
            self.session.cancel_requested = True
            self._set_status("正在停止")
            self.notify("问题已取消，正在停止当前任务。", severity="warning")
            if run_id:
                self.cancel_turn(run_id)
            self.post_message(
                TurnCompleted(
                    AgentExecution(
                        result={
                            "paused": False,
                            "runId": run_id,
                            "answer": "",
                            "cancelled": True,
                        }
                    )
                )
            )
            return
        self._set_status("正在继续…")
        self.answer_turn(execution, answer)
        self._refresh_status_bar()

    def _approval_decided(self, decision: str | None) -> None:
        if self._approval_in_progress:
            return
        self._approval_in_progress = True
        execution = self.pending_execution
        if execution is None:
            self._approval_in_progress = False
            self.current_approval_id = None
            return
        if self.pending_execution is None:
            self._approval_in_progress = False
            self.current_approval_id = None
            return
        self.pending_execution = None
        self.current_approval_id = None
        selected = decision or "deny"
        if selected == "allow_session":
            if self.current_approval_policy:
                self.session.session_approvals[
                    self.current_approval_policy
                ] = self.current_approval_tool
        self._set_status("正在继续…")
        self.resume_turn(execution, selected)
        self._refresh_status_bar()
        self._approval_in_progress = False

    async def on_turn_failed(self, message: TurnFailed) -> None:
        self.running = False
        self.pending_execution = None
        self.current_approval_id = None
        self._approval_in_progress = False
        self.current_question_id = None
        self._question_in_progress = False
        self.current_run_id = None
        self.started_at = None
        self._set_status("执行失败")
        self.query_one(TranscriptView).finalize_assistant()
        await self.query_one(TranscriptView).finish_run(failed=True)
        if not self._stream_failure_reported:
            failure_title, recovery = error_recovery_message(message.error)
            await self.query_one(TranscriptView).add_recovery(
                failure_title,
                redact_public_detail(message.error, limit=300),
                recovery,
                error=True,
            )
            self._stream_failure_reported = True
        self.query_one(Composer).focus()
        self._refresh_status_bar()
        if self.session.queued_questions:
            self.session.queue_paused = True
            if isinstance(self.screen, QueueManagerScreen):
                self._queue_manager_previous_pause = True
            self._refresh_status_bar()
            await self.query_one(TranscriptView).add_notice(
                f"队列已暂停，仍有{len(self.session.queued_questions)}项。"
                "输入/continue继续，或/retry重试上一任务。"
            )

    def on_cancel_requested(self, message: CancelRequested) -> None:
        if not self.running:
            return
        if message.sent:
            self._set_status("正在停止，等待当前操作收尾")
        elif message.error is not None:
            self.notify(
                "停止请求发送失败："
                f"{redact_public_detail(message.error, limit=180)}",
                severity="error",
            )
        else:
            self.notify(
                "当前运行方式不支持远程取消；任务将在操作边界停止。",
                severity="warning",
            )

    @staticmethod
    def _approval_detail(event: dict[str, Any]) -> str:
        for key in (
            "command",
            "path",
            "inputSummary",
            "arguments",
            "input",
            "description",
        ):
            value = event.get(key)
            if value:
                text = redact_public_detail(value, limit=400)
                return f"{key}：{text[:400]}"
        return ""

    @staticmethod
    def _approval_policy_key(event: dict[str, Any]) -> str:
        value = {
            "tool": event.get("toolName"),
            "server": event.get("serverName"),
            "risk": event.get("risk"),
            "target": event.get("path")
            or event.get("command")
            or event.get("inputSummary")
            or event.get("arguments")
            or event.get("input"),
        }
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _set_status(self, value: str) -> None:
        self.current_phase = value
        prefix = "✻ " if self.running else ""
        queue = len(self.session.queued_questions)
        suffix = f" · 队列 {queue}" if queue else ""
        interrupt = " · Ctrl+C中断" if self.running else ""
        self.query_one("#run-status", Static).update(
            f"{prefix}{value}{suffix}{interrupt}"
        )
        self._refresh_status_bar()

    def _refresh_status_bar(self) -> None:
        if not self.is_mounted:
            return
        self.query_one(StatusBar).update_status(
            model=self.backend.model_label,
            workspace=self.workspace,
            phase=self.current_phase,
            queue_size=len(self.session.queued_questions),
            tool_calls=self.session.tool_calls,
            permissions=len(self.session.session_approvals),
            permission_mode=PERMISSION_MODE_BY_ID[
                self.session.permission_mode
            ][2],
        )
        self.query_one(QueuePreview).update_queue(
            self.session.queued_questions,
            paused=self.session.queue_paused,
        )

    def _run_next_queued(self) -> None:
        if (
            self.running
            or self.session.queue_paused
            or not self.session.prompt_queue
        ):
            self._refresh_status_bar()
            return
        prompt = self.session.dequeue()
        if prompt is None:
            self._refresh_status_bar()
            return
        self.call_later(
            self._start_turn,
            prompt.text,
            display_question=prompt.display_text,
        )
        self._refresh_status_bar()

    def _tick_elapsed(self) -> None:
        if not self.running or self.started_at is None:
            return
        elapsed = monotonic() - self.started_at
        try:
            frames = ("✻", "✽", "✶", "✢")
            frame = frames[int(elapsed * 4) % len(frames)]
            queue = len(self.session.queued_questions)
            suffix = f" · 队列 {queue}" if queue else ""
            self.query_one("#run-status", Static).update(
                f"{frame} {self.current_phase}… ({elapsed:.1f}s){suffix}"
            )
        except NoMatches:
            return
        self.query_one(TranscriptView).tick_run(elapsed)
        self._refresh_status_bar()

    async def action_clear(self) -> None:
        await self.query_one(TranscriptView).clear_transcript()

    async def action_new(self) -> None:
        if self.running:
            self.notify("任务执行期间不能新建会话。", severity="warning")
            return
        self.backend.reset()
        self.session.reset_session()
        await self.query_one(TranscriptView).clear_transcript()
        self._set_status("已开始新会话")
        self.query_one(Composer).focus()

    def action_newline(self) -> None:
        composer = self.query_one(Composer)
        if self.focused is composer:
            composer.insert("\n")

    def action_focus_composer(self) -> None:
        self.query_one(Composer).focus()

    async def action_stash(self) -> None:
        composer = self.query_one(Composer)
        if composer.text:
            self.session.stashed_prompt = composer.text
            composer.clear()
            self.notify("输入已暂存；再次按Ctrl+S恢复。")
            return
        if self.session.stashed_prompt:
            composer.load_text(self.session.stashed_prompt)
            self.session.stashed_prompt = ""
            self.notify("已恢复暂存输入。")
        else:
            self.notify("没有暂存输入。", severity="warning")

    async def action_tasks(self) -> None:
        self._open_queue_manager()

    def _open_queue_manager(self) -> None:
        if isinstance(self.screen, QueueManagerScreen):
            return
        self._queue_manager_previous_pause = self.session.queue_paused
        self.session.queue_paused = True
        self._refresh_status_bar()
        self.push_screen(
            QueueManagerScreen(self.session),
            self._on_queue_manager_result,
        )

    def _on_queue_manager_result(
        self,
        prompt: QueuedPrompt | None,
    ) -> None:
        previous_pause = bool(self._queue_manager_previous_pause)
        self._queue_manager_previous_pause = None
        self.session.queue_paused = previous_pause or prompt is not None
        self._refresh_status_bar()
        composer = self.query_one(Composer)
        if prompt is not None:
            composer.load_text(prompt.text)
        composer.focus()
        if prompt is None and not self.running:
            self._run_next_queued()

    def action_slash_commands(self) -> None:
        composer = self.query_one(Composer)
        composer.load_text("/")
        composer.focus()

    async def action_cycle_permission_mode(self) -> None:
        modes = [option[0] for option in PERMISSION_MODE_OPTIONS]
        try:
            current = modes.index(self.session.permission_mode)
        except ValueError:
            current = 0
        await self._apply_permission_mode(modes[(current + 1) % len(modes)])

    def action_interrupt(self) -> None:
        if self.running:
            if self.session.cancel_requested:
                self.notify("当前操作仍在收尾，请稍候。", severity="warning")
                return
            self.session.cancel_requested = True
            self._set_status("已请求停止，正在终止当前任务")
            self.notify(
                "已请求停止；可取消的命令会立即终止，其他工具将在安全边界结束。",
                severity="warning",
            )
            self.cancel_turn(self.current_run_id)
            return
        self.exit()

    async def action_toggle_details(self) -> None:
        self.activity_expanded = not self.activity_expanded
        await self.query_one(TranscriptView).set_activity_expanded(
            self.activity_expanded
        )


def run_tui(
    backend: TuiBackend,
    *,
    assume_yes: bool = False,
    startup_action: str = "",
) -> None:
    KnowFlowTui(
        backend,
        assume_yes=assume_yes,
        startup_action=startup_action,
    ).run()
