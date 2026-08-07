from __future__ import annotations

from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
import json
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
from .commands import canonical_command
from .state import TuiSessionState
from .widgets import (
    CommandMenu,
    Composer,
    StatusBar,
    TranscriptView,
    redact_public_detail,
)


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
        self.activity_expanded = True
        self.current_approval_tool = ""
        self.current_approval_policy = ""
        self.current_run_id: str | None = None
        self.workspace = str(Path.cwd())
        super().__init__()

    def compose(self) -> ComposeResult:
        yield TranscriptView(id="transcript")
        with Vertical(id="bottom-pane"):
            yield Static("就绪", id="run-status")
            yield CommandMenu()
            with Horizontal(id="composer-row"):
                yield Static("›", id="composer-prefix")
                yield Composer()
            yield StatusBar(id="status-bar")

    async def on_mount(self) -> None:
        try:
            release = version("knowflow-ai")
        except PackageNotFoundError:
            release = "dev"
        await self.query_one(TranscriptView).show_welcome(
            version=release,
            model=self.backend.model_label,
            workspace=self.workspace,
        )
        self.query_one(Composer).focus()
        self.set_interval(0.25, self._tick_elapsed)
        self._refresh_status_bar()

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
        composer = self.query_one(Composer)
        question = composer.text.strip()
        if not question:
            return
        composer.remember(question)
        composer.clear()
        if await self._handle_command(question):
            return
        if self.running:
            self.session.queued_questions.append(question)
            await self.query_one(TranscriptView).add_notice(
                f"已加入队列：{question}"
            )
            self._refresh_status_bar()
            return
        await self._start_turn(question)

    async def _start_turn(self, question: str) -> None:
        transcript = self.query_one(TranscriptView)
        await transcript.add_user(question)
        await transcript.begin_run()
        self.streamed = False
        self.running = True
        self.session.reset_run()
        self.started_at = monotonic()
        self._set_status("分析任务")
        self.execute_turn(question)
        self._refresh_status_bar()

    async def _handle_command(self, value: str) -> bool:
        value = canonical_command(value)
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
                "/new新会话  /clear清屏  /model模型  /status状态  "
                "/permissions权限  /tasks队列  /exit退出"
            )
            return True
        if value == "/model":
            await self.query_one(TranscriptView).add_notice(
                f"当前模型：{self.backend.model_label}。使用knowflow configure修改。"
            )
            return True
        if value == "/status":
            await self.query_one(TranscriptView).add_notice(
                f"模型：{self.backend.model_label}；目录：{self.workspace}；"
                f"状态：{self.current_phase}；等待任务："
                f"{len(self.session.queued_questions)}。"
            )
            return True
        if value == "/permissions":
            tools = sorted(set(self.session.session_approvals.values()))
            await self.query_one(TranscriptView).add_notice(
                "本次会话已允许："
                + ("、".join(tools) if tools else "无，所有写操作按需确认。")
            )
            return True
        if value == "/tasks":
            queued = self.session.queued_questions
            await self.query_one(TranscriptView).add_notice(
                "等待任务："
                + (
                    "；".join(
                        f"{index + 1}. {item}"
                        for index, item in enumerate(queued)
                    )
                    if queued
                    else "无。"
                )
            )
            return True
        if value == "/continue":
            if self.running:
                self.notify("当前任务仍在执行。", severity="warning")
            elif not self.session.queued_questions:
                await self.query_one(TranscriptView).add_notice(
                    "等待队列为空。"
                )
            else:
                self._run_next_queued()
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
        await transcript.finish_run()
        self.pending_execution = None
        self.current_run_id = None
        self.running = False
        self.started_at = None
        interrupted = self.session.cancel_requested
        self._set_status("已停止" if interrupted else "已完成")
        self.query_one(Composer).focus()
        if not interrupted:
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
        if self.current_approval_policy in self.session.session_approvals:
            self._approval_decided("allow_once")
            return
        if self.assume_yes:
            self._approval_decided("allow_once")
            return
        self.push_screen(
            ApprovalScreen(
                self.current_approval_tool,
                str(event.get("risk") or "写入"),
                self._approval_detail(event),
            ),
            self._approval_decided,
        )

    async def on_turn_failed(self, message: TurnFailed) -> None:
        self.running = False
        self.pending_execution = None
        self.current_run_id = None
        self.started_at = None
        self._set_status("执行失败")
        await self.query_one(TranscriptView).finish_run(failed=True)
        await self.query_one(TranscriptView).add_notice(
            f"执行失败：{message.error}",
            error=True,
        )
        self.query_one(Composer).focus()
        self._refresh_status_bar()
        if self.session.queued_questions:
            await self.query_one(TranscriptView).add_notice(
                f"队列已暂停，仍有{len(self.session.queued_questions)}项。"
                "输入/continue继续。"
            )

    def on_cancel_requested(self, message: CancelRequested) -> None:
        if message.sent:
            self._set_status("已向服务器请求停止")
        elif message.error is not None:
            self.notify(
                f"停止请求发送失败：{message.error}",
                severity="error",
            )

    def _approval_decided(self, decision: str | None) -> None:
        execution = self.pending_execution
        if execution is None:
            return
        self.pending_execution = None
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
        self.query_one("#run-status", Static).update(value)
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
        )

    def _run_next_queued(self) -> None:
        if self.running or not self.session.queued_questions:
            self._refresh_status_bar()
            return
        question = self.session.queued_questions.pop(0)
        self.call_later(self._start_turn, question)
        self._refresh_status_bar()

    def _tick_elapsed(self) -> None:
        if not self.running or self.started_at is None:
            return
        elapsed = monotonic() - self.started_at
        self.query_one("#run-status", Static).update(
            f"{self.current_phase} · {elapsed:.1f}s"
        )
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
