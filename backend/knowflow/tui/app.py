from __future__ import annotations

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
    StatusBar,
    TranscriptView,
    redact_public_detail,
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


class KnowFlowTui(App[None]):
    CSS_PATH = "knowflow.tcss"
    TITLE = "KnowFlow"
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
        assume_yes: bool,
    ) -> None:
        self.backend = backend
        self.assume_yes = assume_yes
        self.running = False
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
        self._approval_in_progress = False
        self.workspace = str(Path.cwd())
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
            "/permissions": self._cmd_permissions,
            "/tasks": self._cmd_tasks,
            "/history": self._cmd_history,
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
            await self.query_one(TranscriptView).add_notice(
                f"已加入队列：{redact_public_detail(display_question, limit=120)}"
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
            f"KnowFlow TUI · 模式：{runtime} · 模型：{self.backend.model_label} "
            f"· 工作目录：{self.workspace}"
        )
        return True

    async def _cmd_version(self, args: list[str]) -> bool:
        await self.query_one(TranscriptView).add_notice(
            f"KnowFlow CLI 当前版本 v{_cli_release()}"
        )
        return True

    async def _cmd_update(self, args: list[str]) -> bool:
        await self.query_one(TranscriptView).add_notice(
            "更新CLI：执行 `knowflow update`（与主程序版本同步）。"
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
                    "本地模式请先执行 knowflow configure。"
                )
                return True
            await self._cmd_model_list_remote()
            return True
        if part == "use":
            if self.backend.remote_client is None:
                await self.query_one(TranscriptView).add_notice(
                    "本地模式不支持在会话内切换模型ID。请重新配置 knowflow configure。"
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
                "模型配置请使用 knowflow configure，或在 /model list 后在网页调整。"
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

    async def _cmd_permissions(self, args: list[str]) -> bool:
        if not args:
            self.push_screen(
                PermissionRuleScreen(self.session.permission_rules),
                self._on_permission_rules_result,
            )
            return True
        behavior = str(args[0]).strip().lower()
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
            "用法：/permissions，或/permissions allow|ask|deny <工具名>。"
        )
        return True

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
            await self.query_one(TranscriptView).add_notice(
                "本地模式不支持工具列表查询。"
            )
            return True
        items = await self._fetch_remote_list("/api/agent/tools")
        if items is None:
            return True
        tools = [str(item.get("name") if isinstance(item, dict) else item) for item in items]
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
            await self.query_one(TranscriptView).add_notice(
                "本地模式不支持技能列表查询。"
            )
            return True
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
            await self.query_one(TranscriptView).add_notice(
                "本地模式不支持MCP列表查询。"
            )
            return True
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
            await self.query_one(TranscriptView).add_notice(
                "本地模式暂不支持记忆列表查询。"
            )
            return True
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
        part = args[0].lower().strip() if args else "list"
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

    async def on_agent_event_message(self, message: AgentEventMessage) -> None:
        event = message.event
        event_type = str(event.get("type") or "")
        run = event.get("run")
        run_id = event.get("runId")
        if not run_id and isinstance(run, dict):
            run_id = run.get("id")
        if run_id:
            self.current_run_id = str(run_id)
        transcript = self.query_one(TranscriptView)
        await transcript.update_activity(event)
        if event_type == "text_delta":
            text = str(event.get("text") or "")
            if text:
                self.streamed = True
                await transcript.append_assistant(text)
        elif event_type in {"answer", "message"}:
            content = str(event.get("content") or "")
            if content:
                self.streamed = True
                await transcript.append_assistant(content)
            self._set_status("生成回答")
        elif event_type == "model_event":
            self._set_status("生成回答")
        elif event_type in {"tool", "tool_result"}:
            self.session.record_tool(event)
            self._set_status("处理工具结果")
        elif event_type == "agent_step":
            step = event.get("step") if isinstance(event.get("step"), dict) else event
            self._set_status(
                str(step.get("title") or step.get("name") or "执行Agent步骤")
            )
        elif event_type in {"plan_created", "step_updated", "run_updated"}:
            self._set_status("更新任务进度")
        elif event_type == "approval_required":
            self._set_status("等待确认")
        self._refresh_status_bar()

    async def on_turn_completed(self, message: TurnCompleted) -> None:
        transcript = self.query_one(TranscriptView)
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
        await transcript.finish_run()
        self.pending_execution = None
        self.current_run_id = None
        self.running = False
        self.started_at = None
        interrupted = self.session.cancel_requested
        self._set_status("已停止" if interrupted else "已完成")
        self.query_one(Composer).focus()
        if interrupted:
            self.session.queue_paused = bool(self.session.prompt_queue)
        else:
            self.session.queue_paused = False
            self._run_next_queued()

    def on_turn_paused(self, message: TurnPaused) -> None:
        self.pending_execution = message.execution
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
            selected = "allow_once"
        self._set_status("正在继续…")
        self.resume_turn(execution, selected)
        self._refresh_status_bar()
        self._approval_in_progress = False

    async def on_turn_failed(self, message: TurnFailed) -> None:
        self.running = False
        self.pending_execution = None
        self.current_approval_id = None
        self._approval_in_progress = False
        self.current_run_id = None
        self.started_at = None
        self._set_status("执行失败")
        self.query_one(TranscriptView).finalize_assistant()
        await self.query_one(TranscriptView).finish_run(failed=True)
        await self.query_one(TranscriptView).add_notice(
            f"执行失败：{redact_public_detail(message.error, limit=240)}",
            error=True,
        )
        self.query_one(Composer).focus()
        self._refresh_status_bar()
        if self.session.queued_questions:
            self.session.queue_paused = True
            await self.query_one(TranscriptView).add_notice(
                f"队列已暂停，仍有{len(self.session.queued_questions)}项。"
                "输入/continue继续，或/retry重试上一任务。"
            )

    def on_cancel_requested(self, message: CancelRequested) -> None:
        if message.sent:
            self._set_status("已向服务器请求停止")
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
        await self._cmd_tasks(["list"])

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
            self._set_status("已请求停止，将在当前操作边界结束")
            self.notify(
                "已请求停止；不会强制终止正在执行的工具。",
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


def run_tui(backend: TuiBackend, *, assume_yes: bool = False) -> None:
    KnowFlowTui(backend, assume_yes=assume_yes).run()
