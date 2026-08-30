from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event

from textual import events
from textual.widgets import Input, OptionList


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.tui.app import (  # noqa: E402
    ApprovalScreen,
    CommandBrowserScreen,
    KnowFlowTui,
    PermissionModeScreen,
    PermissionRuleScreen,
    QuestionScreen,
    QueueManagerScreen,
)
from knowflow.tui.backend import TuiBackend  # noqa: E402
from knowflow.tui.commands import (  # noqa: E402
    COMMANDS,
    SlashCommand,
    canonical_command,
    match_commands,
    merge_commands,
)
from knowflow.tui.widgets import (  # noqa: E402
    CommandMenu,
    Composer,
    HistorySearchBar,
    QueuePreview,
    redact_public_detail,
)


class FakeBackend:
    model_label = "test-model"
    remote_client = None

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.reset_count = 0

    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink(
            {
                "type": "agent_step",
                "stepId": "step_model",
                "kind": "model",
                "name": "分析请求",
                "status": "running",
            }
        )
        event_sink({"type": "text_delta", "text": "回答"})
        event_sink(
            {
                "type": "tool_started",
                "toolCallId": "call_read",
                "toolName": "read_workspace_file",
                "status": "running",
                "arguments": {"path": "README.md"},
            }
        )
        event_sink(
            {
                "type": "tool_result",
                "toolCallId": "call_read",
                "toolName": "read_workspace_file",
                "status": "success",
                "latencyMs": 12,
                "arguments": {"path": "README.md"},
                "output": {"bytes": 128},
            }
        )
        event_sink(
            {
                "type": "tool_started",
                "toolCallId": "call_shell",
                "toolName": "run_sandbox_command",
                "status": "running",
                "arguments": {"command": "printf hello"},
            }
        )
        event_sink(
            {
                "type": "tool_progress",
                "toolCallId": "call_shell",
                "toolName": "run_sandbox_command",
                "status": "running",
                "output": "hello",
                "elapsedSeconds": 0.2,
                "totalLines": 1,
                "totalBytes": 5,
            }
        )
        event_sink(
            {
                "type": "tool_result",
                "toolCallId": "call_shell",
                "toolName": "run_sandbox_command",
                "status": "success",
                "latencyMs": 220,
                "arguments": {"command": "printf hello"},
                "output": {
                    "exit_code": 0,
                    "stdout": "hello",
                    "stderr": "",
                    "timed_out": False,
                },
            }
        )
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_tui",
                "answer": "回答",
                "trace": [
                    {
                        "type": "agent_step",
                        "stepId": "step_tool",
                        "kind": "tool",
                        "name": "read_workspace_file",
                        "status": "success",
                        "title": "read_workspace_file completed",
                        "durationMs": 12,
                    }
                ],
            }
        )

    def resolve(self, execution, decision, event_sink):
        raise AssertionError("unexpected approval")

    def reset(self):
        self.reset_count += 1

    def command_catalog(self):
        return [
            {
                "value": "/tool:read-workspace-file",
                "description": "读取工作区文件",
                "source": "tool",
            }
        ]

    def sandbox_diagnostics(self):
        return [
            {"name": "srt", "ready": True, "detail": "/usr/bin/srt"},
            {
                "name": "sandbox_smoke",
                "ready": True,
                "detail": "SRT隔离执行成功",
            },
        ]

    def capability_status(self):
        return {
            "tools": {
                "count": 2,
                "enabled": True,
                "items": [
                    {"name": "read_workspace_file"},
                    {"name": "run_sandbox_command"},
                ],
            },
            "skills": {
                "count": 1,
                "items": [{"name": "repo-audit", "enabled": True}],
            },
            "mcp": {
                "count": 1,
                "connected": 1,
                "servers": [
                    {
                        "name": "Notion",
                        "enabled": True,
                        "status": "connected",
                    }
                ],
            },
            "memory": {
                "configured": True,
                "enabled": True,
                "items": [{"memory": "用户偏好中文回答"}],
            },
        }


class ApprovalBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[str] = []

    def run(self, question, event_sink):
        self.questions.append(question)
        event = {
            "type": "approval_required",
            "approvalId": "approval_tui",
            "runId": "run_approval",
            "toolName": "write_workspace_file",
            "risk": "write",
            "destructive": False,
            "inputSummary": {"path": "same.txt"},
        }
        event_sink(event)
        return AgentExecution(
            result={"paused": True, "runId": "run_approval", "answer": ""},
            events=[event],
        )

    def resolve(self, execution, decision, event_sink):
        self.decisions.append(decision)
        event_sink({"type": "text_delta", "text": "已写入"})
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_approval",
                "answer": "已写入",
            }
        )


class QuestionBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.answers: list[dict[str, object]] = []
        self.cancelled: list[str | None] = []

    def run(self, question, event_sink):
        self.questions.append(question)
        question_id = f"question_{len(self.questions)}"
        event = {
            "type": "user_question_required",
            "questionId": question_id,
            "runId": "run_question",
            "header": "部署环境",
            "question": "选择要使用的环境。",
            "options": [
                {
                    "value": "staging",
                    "label": "测试环境",
                    "description": "适合先验证改动。",
                },
                {
                    "value": "production",
                    "label": "生产环境",
                    "description": "会直接影响线上服务。",
                },
            ],
            "allowCustom": True,
        }
        event_sink(event)
        return AgentExecution(
            result={"paused": True, "runId": "run_question", "answer": ""},
            events=[event],
        )

    def answer_question(self, execution, answer, event_sink):
        self.answers.append(dict(answer))
        event_sink({"type": "text_delta", "text": "已收到回答"})
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_question",
                "answer": "已收到回答",
            }
        )

    def cancel(self, run_id=None):
        self.cancelled.append(run_id)
        return True


class ScopedApprovalBackend(ApprovalBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event = {
            "type": "approval_required",
            "approvalId": f"approval_{len(self.questions)}",
            "runId": "run_approval",
            "toolName": "write_workspace_file",
            "risk": "write",
            "destructive": False,
            "inputSummary": {"path": f"{question}.txt"},
        }
        event_sink(event)
        return AgentExecution(
            result={"paused": True, "runId": "run_approval", "answer": ""},
            events=[event],
        )

class RemoteStreamingBackend(FakeBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink({"type": "message", "content": "远程"})
        event_sink({"type": "message", "content": "回答"})
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_remote_tui",
                "answer": "远程回答",
            }
        )


class SlowBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.started = Event()
        self.release = Event()

    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink(
            {
                "type": "agent_step",
                "stepId": "step_slow",
                "kind": "model",
                "name": "理解任务",
                "status": "running",
            }
        )
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("live status test did not release the backend")
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_slow_tui",
                "answer": "完成",
            }
        )


class FailThenBackend(SlowBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        if len(self.questions) == 1:
            self.started.set()
            if not self.release.wait(timeout=5):
                raise TimeoutError("failure queue test did not release")
            raise RuntimeError("synthetic failure")
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_after_failure",
                "answer": "队列继续完成",
            }
        )


class StreamFailureBackend(SlowBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink(
            {
                "eventName": "error.raised",
                "runId": "run_stream_failure",
                "error": {
                    "code": "rate_limited",
                    "message": "HTTP 429 rate limit",
                    "retryable": True,
                },
                "recoveryActions": ["retry"],
            }
        )
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("stream failure test did not release")
        raise RuntimeError("HTTP 429 rate limit")


class RetryBackend(SlowBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink(
            {
                "type": "model_retry",
                "statusCode": 429,
                "retryAttempt": 1,
                "maxRetries": 2,
                "retryInMs": 3000,
            }
        )
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("retry status test did not release")
        event_sink({"type": "text_delta", "text": "恢复成功"})
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_retry_tui",
                "answer": "恢复成功",
            }
        )


class CanonicalEventBackend(SlowBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink({"eventName": "message.delta", "text": "规范事件"})
        event_sink(
            {
                "eventName": "tool.started",
                "toolCallId": "call_canonical",
                "toolName": "read_workspace_file",
                "normalizedStatus": "running",
                "arguments": {"path": "README.md"},
            }
        )
        event_sink(
            {
                "eventName": "tool.completed",
                "toolCallId": "call_canonical",
                "toolName": "read_workspace_file",
                "normalizedStatus": "completed",
                "latencyMs": 8,
                "output": {"bytes": 64},
            }
        )
        event_sink(
            {
                "eventName": "step.completed",
                "stepId": "step_canonical",
                "kind": "tool",
                "name": "读取说明",
                "normalizedStatus": "completed",
            }
        )
        event_sink(
            {
                "eventName": "model.retrying",
                "retryAttempt": 1,
                "maxRetries": 2,
                "retryInMs": 3000,
            }
        )
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("canonical event test did not release")
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_canonical_tui",
                "answer": "规范事件",
            }
        )


class ToolFailureBackend(FakeBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event_sink(
            {
                "type": "tool_started",
                "toolCallId": "call_fail",
                "toolName": "read_workspace_file",
                "status": "running",
                "arguments": {"path": "missing.txt"},
            }
        )
        event_sink(
            {
                "type": "tool_result",
                "toolCallId": "call_fail",
                "toolName": "read_workspace_file",
                "status": "failed",
                "errorCode": "invalid_arguments",
                "errorMessage": "missing path",
                "arguments": {"path": "missing.txt"},
            }
        )
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_tool_failure",
                "answer": "我会换一种方法。",
            }
        )


def exercise_command_matching() -> None:
    dynamic = [
        SlashCommand(
            "/tool:read-workspace-file",
            "读取工作区文件",
            source="tool",
            argument_hint="<任务>",
        )
    ]
    commands = merge_commands(COMMANDS, dynamic)
    assert match_commands("普通问题", commands) == []
    assert match_commands("/help c", commands) == []
    assert match_commands("/model ", commands) == []
    assert match_commands("/pm", commands)[0].value == "/permissions"
    assert match_commands("/read", commands)[0].value == "/tool:read-workspace-file"
    assert canonical_command("/?", commands) == "/help"
    assert canonical_command("/allowed-tools", commands) == "/permissions"
    recently_used = match_commands("/", commands, {"/status": 3})
    assert recently_used[0].value == "/status"


async def exercise_tui() -> None:
    backend = FakeBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        assert "AgentLens" in str(app.query_one(".welcome-panel").border_title)
        rendered_brand = str(app.query_one(".welcome-brand").render())
        assert "AGENT" in rendered_brand
        assert "LENS" in rendered_brand
        assert "test-model" in str(app.query_one(".welcome-context").render())
        assert "输入 / 查看命令" in str(app.query_one(".welcome-tip").render())
        composer.load_text("line one")
        composer.cursor_location = (0, len("line one"))
        await pilot.press("shift+enter")
        await pilot.pause(0.05)
        assert composer.text == "line one\n"
        assert backend.questions == []
        composer.insert("line two")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and backend.questions:
                break
        assert backend.questions == ["line one\nline two"]

        composer.clear()
        large_paste = "前" * 5_500 + "后" * 5_500
        composer.on_paste(events.Paste(large_paste))
        assert "[粘贴内容 #1：已折叠" in composer.text
        assert composer.expanded_text() == large_paste
        composer.clear()
        composer.pasted_contents.clear()

        await pilot.press("ctrl+p")
        await pilot.pause(0.05)
        assert composer.text == "/"
        menu = app.query_one(CommandMenu)
        assert menu.matches
        assert menu.has_class("visible")
        assert [item.value for item in menu.matches[:3]] == [
            "/about",
            "/clear",
            "/continue",
        ]
        assert any(item.value == "/status" for item in menu.matches)
        assert len(menu.query_one("#command-options", OptionList).options) == 6
        assert "查看执行环境与会话上下文" in str(
            menu.query_one("#command-options", OptionList).options[0].prompt
        )
        await pilot.press("escape")

        composer.load_text("/he")
        await pilot.pause(0.05)
        assert [item.value for item in menu.matches] == ["/help"]
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, CommandBrowserScreen)
        assert app.screen.query_one("#command-browser-options", OptionList).option_count > 5
        await pilot.press("right")
        await pilot.pause(0.05)
        assert "自定义命令" in str(
            app.screen.query_one("#command-browser-tabs").render()
        )
        assert any(
            "/tool:read-workspace-file" in str(option.prompt)
            for option in app.screen.query_one(
                "#command-browser-options", OptionList
            ).options
        )
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert not menu.matches

        composer.load_text("/help c")
        await pilot.pause(0.05)
        assert menu.matches == []
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert any("未知help参数" in str(item.render()) for item in app.query(".notice"))
        assert not menu.matches

        composer.clear()
        composer.load_text("hello")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and backend.questions:
                break
        assert backend.questions == ["line one\nline two", "hello"]
        assert not app.running
        assert len(list(app.query(".assistant-message"))) == 2
        assert len(list(app.query(".run-activity"))) == 2
        assert len(list(app.query(".activity-step"))) >= 2
        activity = app.query_one(".run-activity")
        assert "执行完成" in str(activity.query_one(".activity-header").render())
        assert any(
            "read_workspace_file" in str(item.title)
            for item in activity.query(".activity-step")
        )
        assert any(
            "README.md" in str(item.render())
            for item in activity.query(".activity-detail")
        )
        assert any(
            "hello" in str(item.render())
            for item in activity.query(".activity-detail")
        )
        assert "已完成" in str(app.query_one("#run-status").render())
        assert "test-model" in str(app.query_one("#status-bar").render())

        await pilot.press("up")
        await pilot.pause(0.05)
        assert composer.text == "hello"
        composer.clear()

        composer.load_text("/doctor")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert any(
            "SRT已可执行shell工具" in str(item.render())
            for item in app.query(".notice")
        )

        for command, expected in (
            ("/tools", "read_workspace_file"),
            ("/skills", "repo-audit"),
            ("/mcp", "Notion · connected"),
            ("/memory", "用户偏好中文回答"),
        ):
            composer.load_text(command)
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert any(
                expected in str(item.render())
                for item in app.query(".notice")
            )

        await pilot.press("ctrl+r")
        await pilot.pause(0.05)
        history = app.query_one(HistorySearchBar)
        assert history.has_class("visible")
        history.query_one(Input).value = "hell"
        await pilot.pause(0.05)
        assert composer.text == "hello"
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert not history.has_class("visible")
        composer.clear()

        composer.load_text("未提交草稿")
        await pilot.press("ctrl+r")
        await pilot.pause(0.05)
        history.query_one(Input).value = "hell"
        await pilot.pause(0.05)
        assert composer.text == "hello"
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert not history.has_class("visible")
        assert composer.text == "未提交草稿"
        composer.clear()

        composer.load_text("暂存内容")
        await pilot.press("ctrl+s")
        await pilot.pause(0.05)
        assert composer.text == ""
        await pilot.press("ctrl+s")
        await pilot.pause(0.05)
        assert composer.text == "暂存内容"
        composer.clear()

        composer.load_text("/tool:read-workspace-file inspect")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and len(backend.questions) >= 3:
                break
        assert "请使用tool read-workspace-file" in backend.questions[-1]

        composer.load_text("/pm")
        await pilot.pause(0.05)
        assert [item.value for item in menu.matches] == ["/permissions"]
        await pilot.press("escape")

        composer.load_text("/zzz")
        await pilot.pause(0.05)
        assert menu.matches == []
        composer.load_text("/help ")
        await pilot.pause(0.05)
        assert menu.matches == []

        composer.load_text("/new")
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert backend.reset_count == 1
        assert not list(app.query(".assistant-message"))


async def exercise_remote_streaming() -> None:
    backend = RemoteStreamingBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("remote")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and backend.questions:
                break
        transcript = app.query_one("#transcript")
        assert transcript._assistant_text == "远程回答"


async def exercise_live_status() -> None:
    backend = SlowBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("slow")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        assert backend.started.is_set()
        assert app.running
        assert "理解任务" in str(app.query_one("#run-status").render())
        assert "正在处理" in str(
            app.query_one(".activity-header").render()
        )
        backend.release.set()
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert not app.running


async def exercise_retry_status() -> None:
    backend = RetryBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("retry")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        assert backend.started.is_set()
        assert "模型请求失败" in str(app.query_one("#run-status").render())
        activity = app.query_one(".run-activity")
        model = activity._rows["model"]
        assert not model.collapsed
        assert "1/2" in str(
            model.query_one(".activity-detail").render()
        )
        backend.release.set()
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert not app.running
        assert app.query_one("#transcript")._assistant_text == "恢复成功"


async def exercise_canonical_events() -> None:
    backend = CanonicalEventBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("canonical")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        assert backend.started.is_set()
        transcript = app.query_one("#transcript")
        assert transcript._assistant_text == "规范事件"
        activity = app.query_one(".run-activity")
        assert "tool:call_canonical" in activity._rows
        assert activity._statuses["tool:call_canonical"] == "completed"
        assert "step_canonical" in activity._rows
        assert "模型请求失败" in str(app.query_one("#run-status").render())
        backend.release.set()
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert not app.running


async def exercise_stream_failure_recovery() -> None:
    backend = StreamFailureBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("stream failure")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        assert backend.started.is_set()
        notices = list(app.query(".recovery-notice"))
        assert len(notices) == 1
        assert "请求过于频繁" in str(notices[0].render())
        backend.release.set()
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert not app.running
        assert len(list(app.query(".recovery-notice"))) == 1


async def exercise_tool_failure_feedback() -> None:
    app = KnowFlowTui(ToolFailureBackend(), assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("inspect missing file")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        activity = app.query_one(".run-activity")
        tool_rows = [
            row
            for row in activity.query(".activity-step")
            if "missing.txt" in str(row.title)
        ]
        assert len(tool_rows) == 1
        assert not tool_rows[0].collapsed
        detail = str(tool_rows[0].query_one(".activity-detail").render())
        assert "参数不正确" in detail
        assert "让Agent修正参数" in detail
        assert "1次失败" in str(
            activity.query_one(".activity-header").render()
        )


async def exercise_narrow_command_menu() -> None:
    app = KnowFlowTui(FakeBackend(), assume_yes=False)
    async with app.run_test(size=(48, 20)) as pilot:
        app.query_one(Composer).load_text("/")
        menu = app.query_one(CommandMenu)
        for _ in range(50):
            await pilot.pause(0.02)
            if menu.matches and menu.size.width > 0:
                break
        assert menu.matches
        assert 0 < menu.size.width < 48, (
            f"narrow command menu width={menu.size.width}, "
            f"region={menu.region}, screen={app.screen.size}"
        )
        assert app.screen.has_class("narrow")


async def exercise_approval() -> None:
    backend = ApprovalBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("write")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if isinstance(app.screen, ApprovalScreen):
                break
        assert isinstance(app.screen, ApprovalScreen)
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.decisions and not app.running:
                break
        assert backend.decisions == ["allow_once"]
        assert not app.running
        assert len(list(app.query(".assistant-message"))) == 1


async def exercise_question() -> None:
    backend = QuestionBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("deploy")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if isinstance(app.screen, QuestionScreen):
                break
        assert isinstance(app.screen, QuestionScreen)
        screen = app.screen
        assert "选择要使用的环境" in str(screen.query_one(".question-body").render())
        assert screen.query_one("#question-options").option_count == 3
        await pilot.press("down", "enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if backend.answers and not app.running:
                break
        assert backend.answers[-1] == {
            "answer": "production",
            "selectedOptions": ["production"],
        }

        composer.load_text("custom deploy")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if isinstance(app.screen, QuestionScreen):
                break
        assert isinstance(app.screen, QuestionScreen)
        await pilot.press("end", "enter")
        custom = app.screen.query_one("#question-custom-input", Input)
        assert app.screen.focused is custom
        custom.value = "临时环境"
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if len(backend.answers) >= 2 and not app.running:
                break
        assert backend.answers[-1] == {
            "answer": "临时环境",
            "selectedOptions": [],
        }

        composer.load_text("cancel deploy")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if isinstance(app.screen, QuestionScreen):
                break
        await pilot.press("escape")
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert backend.cancelled == ["run_question"]
        assert not app.running
        assert "已停止" in str(app.query_one("#run-status").render())


async def exercise_permission_modes() -> None:
    backend = ApprovalBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        await pilot.press("shift+tab")
        await pilot.pause(0.1)
        assert app.session.permission_mode == "auto_edit"
        assert app._permission_mode_allows(
            {"risk": "write", "destructive": False}
        )
        assert not app._permission_mode_allows(
            {"risk": "write", "destructive": True}
        )
        assert not app._permission_mode_allows({})

        composer.load_text("write without another prompt")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if backend.decisions and not app.running:
                break
        assert backend.decisions == ["allow_once"]
        assert not isinstance(app.screen, ApprovalScreen)

        await pilot.press("shift+tab")
        await pilot.pause(0.1)
        assert app.session.permission_mode == "full_access"

        composer.load_text("/new")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert app.session.permission_mode == "ask"

        composer.load_text("/permissions")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, PermissionModeScreen)
        assert app.screen.query_one("#permission-mode-options").highlighted == 0
        await pilot.press("down", "enter")
        await pilot.pause(0.1)
        assert app.session.permission_mode == "auto_edit"
        assert not isinstance(app.screen, PermissionModeScreen)

        composer.load_text("/permissions")
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, PermissionModeScreen)
        await pilot.resize_terminal(48, 20)
        await pilot.pause(0.1)
        assert app.screen.has_class("narrow")
        assert app.screen.query_one("#permission-mode-dialog").size.width < 48
        await pilot.press("end", "enter")
        await pilot.pause(0.1)
        assert isinstance(app.screen, PermissionRuleScreen)
        assert "Allow" in str(app.screen.query_one("#permission-rule-tabs").render())
        await pilot.press("enter")
        field = app.screen.query_one("#permission-rule-input", Input)
        field.value = "write_workspace_file"
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert "write_workspace_file" in app.screen.rules["allow"]
        await pilot.press("right")
        assert app.screen.behavior == "ask"
        await pilot.press("a")
        ask_field = app.screen.query_one("#permission-rule-input", Input)
        assert app.screen.focused is ask_field
        ask_field.value = "sandbox_command"
        await pilot.press("enter")
        assert "sandbox_command" in app.screen.rules["ask"]
        await pilot.press("down", "d")
        assert "sandbox_command" not in app.screen.rules["ask"]
        await pilot.press("right")
        assert app.screen.behavior == "deny"
        await pilot.resize_terminal(48, 20)
        await pilot.pause(0.1)
        assert isinstance(app.screen, PermissionRuleScreen)
        assert app.screen.has_class("narrow")
        assert app.screen.query_one("#permission-rules-dialog").size.width < 48
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert app.session.permission_behavior("write_workspace_file") == "allow"

        composer.load_text("allowed by rule")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if len(backend.decisions) >= 2 and not app.running:
                break
        assert backend.decisions[-1] == "allow_once"

        app.session.set_permission_rule("deny", "write_workspace_file")
        composer.load_text("denied by rule")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if len(backend.decisions) >= 3 and not app.running:
                break
        assert backend.decisions[-1] == "deny"


async def exercise_session_approval() -> None:
    backend = ApprovalBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("write one")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if isinstance(app.screen, ApprovalScreen):
                break
        assert isinstance(app.screen, ApprovalScreen)
        await pilot.press("s")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert "write_workspace_file" in app.session.session_approvals.values()

        composer.load_text("write two")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if len(backend.decisions) == 2 and not app.running:
                break
        assert backend.decisions == ["allow_once", "allow_once"]
        assert not isinstance(app.screen, ApprovalScreen)


async def exercise_queue() -> None:
    backend = SlowBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("first")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        composer.load_text("second")
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app.session.queued_questions == ["second"]
        assert "队列 1" in str(app.query_one("#status-bar").render())
        await pilot.press("ctrl+t")
        await pilot.pause(0.05)
        assert isinstance(app.screen, QueueManagerScreen)
        backend.release.set()
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert backend.questions == ["first"]
        assert app.session.queue_paused
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause(0.05)
            if backend.questions == ["first", "second"] and not app.running:
                break
        assert backend.questions == ["first", "second"]
        assert app.session.queued_questions == []
        app.session.enqueue("later", priority="later")
        app.session.enqueue("now", priority="now")
        assert [item.text for item in app.session.ordered_queue()] == [
            "now",
            "later",
        ]


async def exercise_queue_manager() -> None:
    app = KnowFlowTui(FakeBackend(), assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.session.enqueue("first queued", priority="next")
        app.session.enqueue("second queued", priority="later")
        app._refresh_status_bar()
        await pilot.press("ctrl+t")
        await pilot.pause(0.05)
        assert isinstance(app.screen, QueueManagerScreen)
        assert "2项等待" in str(
            app.screen.query_one("#queue-manager-summary").render()
        )
        await pilot.press("right")
        assert app.session.ordered_queue()[0].priority == "now"
        await pilot.press("down", "d")
        assert app.session.queued_questions == ["first queued"]
        await pilot.resize_terminal(48, 20)
        await pilot.pause(0.05)
        assert app.screen.has_class("narrow")
        assert app.screen.query_one("#queue-manager-dialog").size.width < 48
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert not isinstance(app.screen, QueueManagerScreen)
        assert app.session.queued_questions == []
        assert app.query_one(Composer).text == "first queued"

        app.session.enqueue("slash queue", priority="next")
        app.query_one(Composer).load_text("/tasks")
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert isinstance(app.screen, QueueManagerScreen)
        await pilot.press("escape")


async def exercise_scoped_session_approval() -> None:
    backend = ScopedApprovalBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("alpha")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if isinstance(app.screen, ApprovalScreen):
                break
        await pilot.press("s")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break

        composer.load_text("beta")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if isinstance(app.screen, ApprovalScreen):
                break
        assert isinstance(app.screen, ApprovalScreen)
        assert backend.decisions == ["allow_once"]
        await pilot.press("d")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break


async def exercise_interrupt_feedback() -> None:
    backend = SlowBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        app.query_one(Composer).load_text("slow")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        await pilot.press("ctrl+c")
        await pilot.pause(0.05)
        assert app.session.cancel_requested
        assert "已请求停止" in str(app.query_one("#run-status").render())
        backend.release.set()
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert not app.running


async def exercise_failed_queue_pause() -> None:
    backend = FailThenBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("first fails")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if backend.started.is_set():
                break
        composer.load_text("second waits")
        await pilot.press("enter")
        await pilot.pause(0.05)
        queue_preview = app.query_one(QueuePreview)
        assert queue_preview.has_class("visible")
        assert "second waits" in str(queue_preview.render())
        backend.release.set()
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert app.session.queue_paused
        assert "队列已暂停" in str(queue_preview.render())
        assert backend.questions == ["first fails"]
        assert any(
            "修改要求后重新发送" in str(item.render())
            for item in app.query(".recovery-notice")
        )
        composer.load_text("/continue")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if backend.questions == ["first fails", "second waits"] and not app.running:
                break
        assert backend.questions == ["first fails", "second waits"]
        assert not app.session.queue_paused
        assert not queue_preview.has_class("visible")


async def exercise_render_caps() -> None:
    app = KnowFlowTui(FakeBackend(), assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        transcript = app.query_one("#transcript")
        for index in range(205):
            await transcript.add_notice(f"notice {index}")
        assert transcript._archived_records
        assert len(transcript._message_widgets) <= transcript.MAX_VISIBLE_BLOCKS
        await pilot.press("ctrl+o")
        await pilot.pause(0.05)
        assert transcript.archive_expanded

        await transcript.begin_run()
        for index in range(1_000):
            await transcript.update_activity(
                {
                    "type": "tool_result",
                    "toolCallId": f"call_{index}",
                    "toolName": "synthetic_tool",
                    "status": "success",
                    "latencyMs": index,
                }
            )
        activity = transcript._activity
        assert activity is not None
        assert len(activity._rows) <= 100
        assert activity._hidden_steps >= 900


def main() -> None:
    exercise_command_matching()
    redacted = redact_public_detail(
        {
            "config": {"api_key": "sk-nested-secret", "path": "safe.txt"},
            "password": "hidden",
        }
    )
    assert "sk-nested-secret" not in redacted
    assert "hidden" not in redacted
    assert "safe.txt" in redacted
    assert "nested-secret" not in redact_public_detail(
        '{"config":{"token":"nested-secret"}}'
    )
    for secret_text in (
        "Authorization: Bearer bearer-secret",
        "curl --password command-secret https://example.test",
        "eyJheader.payload.signature",
        "Your account org-8242d004acb748ada9255f6d42f4dc23<ak-fbzbf9goi431l1d8rrx1>",
    ):
        assert not any(
            secret in redact_public_detail(secret_text)
            for secret in (
                "bearer-secret",
                "command-secret",
                "eyJheader.payload.signature",
                "8242d004acb748ada9255f6d42f4dc23",
                "fbzbf9goi431l1d8rrx1",
            )
        )

    class FakeRemoteClient:
        def __init__(self):
            self.calls = []
            self.resumed = []
            self.session_rows = [
                {
                    "id": "session_remote",
                    "title": "远程历史",
                    "updated_at": "2026-08-29 12:00:00",
                    "latest_run": {
                        "id": "run_remote_complete",
                        "status": "completed",
                    },
                }
            ]
            self.messages_by_session = {
                "session_remote": [
                    {"role": "user", "content": "旧问题"},
                    {
                        "role": "assistant",
                        "content": "旧回答",
                        "run": {
                            "id": "run_remote_complete",
                            "sessionId": "session_remote",
                            "status": "completed",
                            "lastSequence": 8,
                        },
                    },
                ]
            }

        def request(self, method, path):
            self.calls.append((method, path))
            if path.endswith("/messages"):
                return [
                    {"role": "user", "content": "普通对话"},
                    {"role": "assistant", "content": "普通回复"},
                ]

        def delete_session(self, session_id):
            self.calls.append(("DELETE", f"/api/sessions/{session_id}"))
            return True

        def list_sessions(self, limit=20, *, archived=False):
            return [
                {
                    "id": "session_without_run",
                    "title": "普通Web对话",
                    "is_pinned": False,
                    "is_archived": bool(archived),
                    "updated_at": "2026-08-27 10:00:00",
                    "latest_run": None,
                },
                *self.session_rows,
            ][:limit]

        def session_messages(self, session_id):
            if session_id == "session_without_run":
                return [
                    {"role": "user", "content": "普通对话"},
                    {"role": "assistant", "content": "普通回复"},
                ]
            return self.messages_by_session[session_id]

        def get_run(self, run_id):
            for messages in self.messages_by_session.values():
                for message in messages:
                    run = message.get("run") or {}
                    if run.get("id") == run_id:
                        return run
            return {}

        def resume(self, run_id, event_sink, *, after_sequence=None):
            self.resumed.append((run_id, after_sequence))
            event_sink({"type": "message", "content": "继续完成"})
            return AgentExecution(
                result={
                    "paused": False,
                    "runId": run_id,
                    "sessionId": "session_failed",
                    "answer": "继续完成",
                    "lastSequence": (after_sequence or 0) + 1,
                }
            )

    remote_client = FakeRemoteClient()
    tui_backend = TuiBackend(
        local_agent=None,
        remote_client=remote_client,
        tools=True,
        model_id=None,
        skill_id=None,
    )
    remote_sessions = tui_backend.list_sessions()
    assert remote_sessions[0] == {
        "runId": "session_without_run",
        "sessionId": "session_without_run",
        "title": "普通Web对话",
        "pinned": False,
        "archived": False,
        "status": "completed",
        "updatedAt": 1787824800.0,
        "cwd": "",
        "answer": "",
    }
    restored = tui_backend.restore_session(
        "session_without_run",
        lambda _event: None,
        session_id="session_without_run",
        status="completed",
    )
    assert restored.result["restored"] is True
    assert restored.result["messages"][-1]["content"] == "普通回复"
    deleted = tui_backend.delete_session(
        "session_without_run",
        "session_without_run",
    )
    assert deleted == {
        "runId": "session_without_run",
        "sessionId": "session_without_run",
        "deleted": True,
        "current": True,
    }
    assert remote_client.calls[-1] == (
        "DELETE",
        "/api/sessions/session_without_run",
    )
    tui_backend.current_run_id = "unrelated_run"
    tui_backend.session_id = "current_session"
    assert tui_backend.delete_session(session_id="other_session")["current"] is False
    assert remote_client.calls[-1] == (
        "DELETE",
        "/api/sessions/other_session",
    )
    remote_client.calls.clear()
    assert tui_backend.cancel("run_cancel")
    assert remote_client.calls == [
        ("POST", "/api/agent/runs/run_cancel/cancel")
    ]
    assert not tui_backend.cancel(None)
    remote_sessions = tui_backend.list_sessions()
    remote_run_session = next(
        item for item in remote_sessions if item["sessionId"] == "session_remote"
    )
    assert remote_run_session["runId"] == "run_remote_complete"
    assert remote_run_session["status"] == "completed"
    assert isinstance(remote_run_session["updatedAt"], float)
    restored = tui_backend.restore_session("session_remote", lambda _event: None)
    assert restored.result["restored"] is True
    assert restored.result["messages"][-1]["content"] == "旧回答"
    assert tui_backend.session_id == "session_remote"
    assert tui_backend.current_run_id == "run_remote_complete"

    remote_client.messages_by_session["session_waiting"] = [
        {"role": "user", "content": "请发布"},
        {
            "role": "assistant",
            "content": "",
            "run": {
                "id": "run_waiting",
                "sessionId": "session_waiting",
                "status": "waiting_approval",
                "lastSequence": 10,
            },
            "approvals": [
                {
                    "approvalId": "approval_waiting",
                    "status": "waiting",
                    "toolName": "write_workspace_file",
                    "risk": "write",
                }
            ],
        },
    ]
    restored_events = []
    waiting = tui_backend.restore_session(
        "session_waiting",
        restored_events.append,
    )
    assert waiting.paused
    assert waiting.approval_id == "approval_waiting"
    assert restored_events[-1]["type"] == "approval_required"
    assert tui_backend.session_id == "session_waiting"
    assert tui_backend.current_run_id == "run_waiting"

    remote_client.messages_by_session["session_failed"] = [
        {"role": "user", "content": "失败任务"},
        {
            "role": "assistant",
            "content": "",
            "run": {
                "id": "run_failed",
                "sessionId": "session_failed",
                "status": "failed",
                "lastSequence": 11,
            },
        },
    ]
    resumed = tui_backend.restore_session(
        "session_failed",
        lambda _event: None,
    )
    assert resumed.result["restored"] is True
    assert remote_client.resumed == [("run_failed", 11)]

    class FakeLocalAgent:
        def __init__(self):
            self.cancelled = []

        def cancel(self, run_id=None):
            self.cancelled.append(run_id)
            return True

        def delete_session(self, run_id):
            return {"runId": run_id, "deleted": True}

    local_agent = FakeLocalAgent()
    local_backend = TuiBackend(
        local_agent=local_agent,
        remote_client=None,
        tools=True,
        model_id=None,
        skill_id=None,
    )
    assert local_backend.cancel(None)
    assert local_agent.cancelled == [None]
    local_backend.current_run_id = "run_local"
    assert local_backend.delete_session("run_local") == {
        "runId": "run_local",
        "sessionId": "",
        "deleted": True,
        "current": True,
    }
    original_data_home = os.environ.get("XDG_DATA_HOME")
    with TemporaryDirectory() as data_home:
        os.environ["XDG_DATA_HOME"] = data_home
        asyncio.run(exercise_tui())
        asyncio.run(exercise_remote_streaming())
        asyncio.run(exercise_live_status())
        asyncio.run(exercise_retry_status())
        asyncio.run(exercise_canonical_events())
        asyncio.run(exercise_stream_failure_recovery())
        asyncio.run(exercise_tool_failure_feedback())
        asyncio.run(exercise_narrow_command_menu())
        asyncio.run(exercise_approval())
        asyncio.run(exercise_question())
        asyncio.run(exercise_permission_modes())
        asyncio.run(exercise_session_approval())
        asyncio.run(exercise_queue())
        asyncio.run(exercise_queue_manager())
        asyncio.run(exercise_scoped_session_approval())
        asyncio.run(exercise_interrupt_feedback())
        asyncio.run(exercise_failed_queue_pause())
        asyncio.run(exercise_render_caps())
    if original_data_home is None:
        os.environ.pop("XDG_DATA_HOME", None)
    else:
        os.environ["XDG_DATA_HOME"] = original_data_home
    print("cli tui checks passed")


if __name__ == "__main__":
    main()
