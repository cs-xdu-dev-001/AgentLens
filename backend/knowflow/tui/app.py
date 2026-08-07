from __future__ import annotations

from pathlib import Path
from time import monotonic
from typing import Any

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..services.agent_execution import AgentExecution
from .backend import TuiBackend
from .widgets import CommandMenu, Composer, TranscriptView


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


class ApprovalScreen(ModalScreen[str]):
    BINDINGS = [
        Binding("enter", "allow", "允许本次", show=False),
        Binding("y", "allow", "允许本次", show=False),
        Binding("d", "deny", "拒绝", show=False),
        Binding("n", "deny", "拒绝", show=False),
        Binding("escape", "deny", "返回", show=False),
    ]

    def __init__(self, tool_name: str, risk: str) -> None:
        self.tool_name = tool_name
        self.risk = risk
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="approval-dialog"):
            yield Static("需要确认", classes="approval-title")
            yield Static(
                f"{self.tool_name}准备执行{self.risk or '写入'}操作。",
                classes="approval-body",
            )
            with Horizontal(classes="approval-actions"):
                yield Button("允许本次", id="allow", variant="primary")
                yield Button("拒绝", id="deny")

    @on(Button.Pressed)
    def handle_button(self, event: Button.Pressed) -> None:
        self.dismiss("allow_once" if event.button.id == "allow" else "deny")

    def action_allow(self) -> None:
        self.dismiss("allow_once")

    def action_deny(self) -> None:
        self.dismiss("deny")


class KnowFlowTui(App[None]):
    CSS_PATH = "knowflow.tcss"
    TITLE = "KnowFlow"
    COMMAND_PALETTE_BINDING = "ctrl+p"
    BINDINGS = [
        Binding("ctrl+c", "interrupt", "中断/退出", show=True),
        Binding("ctrl+l", "clear", "清屏", show=True),
        Binding("ctrl+n", "new", "新会话", show=True),
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
        super().__init__()

    def compose(self) -> ComposeResult:
        workspace = str(Path.cwd())
        yield Static(
            f"KnowFlow  ·  {self.backend.model_label}  ·  {workspace}",
            id="topbar",
        )
        yield TranscriptView(id="transcript")
        with Vertical(id="bottom-pane"):
            yield Static("就绪", id="run-status")
            yield CommandMenu()
            yield Composer()
            yield Static(
                "Enter提交  Shift+Enter换行  Ctrl+P命令  Ctrl+C退出",
                id="shortcut-hint",
            )

    def on_mount(self) -> None:
        self.query_one(Composer).focus()
        self.set_interval(0.25, self._tick_elapsed)

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
        value = menu.selected_value
        if value is None:
            return
        composer = self.query_one(Composer)
        composer.load_text(value)
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

    async def _submit(self) -> None:
        if self.running:
            self.notify("当前任务仍在执行。", severity="warning")
            return
        composer = self.query_one(Composer)
        question = composer.text.strip()
        if not question:
            return
        composer.clear()
        if await self._handle_command(question):
            return
        transcript = self.query_one(TranscriptView)
        await transcript.add_user(question)
        await transcript.begin_run()
        self.streamed = False
        self.running = True
        self.started_at = monotonic()
        self._set_status("分析任务")
        self.execute_turn(question)

    async def _handle_command(self, value: str) -> bool:
        if value in {"/quit", "/exit"}:
            self.exit()
            return True
        if value == "/new":
            await self.action_new()
            return True
        if value == "/clear":
            await self.action_clear()
            return True
        if value == "/help":
            await self.query_one(TranscriptView).add_notice(
                "/new新会话  /clear清屏  /exit退出  Ctrl+P打开命令面板"
            )
            return True
        if value == "/model":
            await self.query_one(TranscriptView).add_notice(
                f"当前模型：{self.backend.model_label}。使用knowflow configure修改。"
            )
            return True
        return False

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
        elif event_type == "tool_result":
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
        await transcript.finish_run()
        self.pending_execution = None
        self.running = False
        self.started_at = None
        self._set_status("已完成")
        self.query_one(Composer).focus()

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
        if self.assume_yes:
            self._approval_decided("allow_once")
            return
        self.push_screen(
            ApprovalScreen(
                str(event.get("toolName") or "工具调用"),
                str(event.get("risk") or "写入"),
            ),
            self._approval_decided,
        )

    async def on_turn_failed(self, message: TurnFailed) -> None:
        self.running = False
        self.pending_execution = None
        self.started_at = None
        self._set_status("执行失败")
        await self.query_one(TranscriptView).finish_run(failed=True)
        await self.query_one(TranscriptView).add_notice(
            f"执行失败：{message.error}",
            error=True,
        )
        self.query_one(Composer).focus()

    def _approval_decided(self, decision: str | None) -> None:
        execution = self.pending_execution
        if execution is None:
            return
        self._set_status("正在继续…")
        self.resume_turn(execution, decision or "deny")

    def _set_status(self, value: str) -> None:
        self.current_phase = value
        self.query_one("#run-status", Static).update(value)

    def _tick_elapsed(self) -> None:
        if not self.running or self.started_at is None:
            return
        elapsed = monotonic() - self.started_at
        self.query_one("#run-status", Static).update(
            f"{self.current_phase} · {elapsed:.1f}s"
        )
        self.query_one(TranscriptView).tick_run(elapsed)

    async def action_clear(self) -> None:
        await self.query_one(TranscriptView).clear_transcript()

    async def action_new(self) -> None:
        if self.running:
            self.notify("任务执行期间不能新建会话。", severity="warning")
            return
        self.backend.reset()
        await self.query_one(TranscriptView).clear_transcript()
        self._set_status("已开始新会话")
        self.query_one(Composer).focus()

    def action_newline(self) -> None:
        composer = self.query_one(Composer)
        if self.focused is composer:
            composer.insert("\n")

    def action_focus_composer(self) -> None:
        self.query_one(Composer).focus()

    def action_interrupt(self) -> None:
        if self.running:
            self.notify("当前模型请求尚未返回，暂不能安全中断。", severity="warning")
            return
        self.exit()


def run_tui(backend: TuiBackend, *, assume_yes: bool = False) -> None:
    KnowFlowTui(backend, assume_yes=assume_yes).run()
