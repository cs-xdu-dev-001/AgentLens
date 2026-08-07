from __future__ import annotations

from pathlib import Path
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
from .widgets import Composer, TranscriptView


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
            yield Composer()
            yield Static(
                "Enter提交  Shift+Enter换行  Ctrl+P命令  Ctrl+C退出",
                id="shortcut-hint",
            )

    def on_mount(self) -> None:
        self.query_one(Composer).focus()

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
        self.streamed = False
        self.running = True
        self._set_status("正在思考…")
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
                "/new新会话  /clear清屏  /quit退出  Ctrl+P打开命令面板"
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
        if event_type == "text_delta":
            text = str(event.get("text") or "")
            if text:
                self.streamed = True
                await transcript.append_assistant(text)
        elif event_type == "answer" and not self.streamed:
            content = str(event.get("content") or "")
            if content:
                self.streamed = True
                await transcript.append_assistant(content)
        elif event_type == "tool_result":
            latency = event.get("latencyMs")
            await transcript.add_tool(
                str(event.get("toolName") or "工具调用"),
                str(event.get("status") or "completed"),
                int(latency) if isinstance(latency, (int, float)) else None,
            )
            self._set_status("工具执行完成，继续处理…")
        elif event_type == "approval_required":
            self._set_status("等待确认")

    async def on_turn_completed(self, message: TurnCompleted) -> None:
        answer = str(message.execution.result.get("answer") or "")
        if answer and not self.streamed:
            await self.query_one(TranscriptView).append_assistant(answer)
        self.pending_execution = None
        self.running = False
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
        self._set_status("执行失败")
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
        self.query_one("#run-status", Static).update(value)

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
