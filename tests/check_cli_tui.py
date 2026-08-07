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
from knowflow.tui.app import ApprovalScreen, KnowFlowTui  # noqa: E402
from knowflow.tui.backend import TuiBackend  # noqa: E402
from knowflow.tui.widgets import (  # noqa: E402
    CommandMenu,
    Composer,
    HistorySearchBar,
    redact_public_detail,
)


class FakeBackend:
    model_label = "test-model"

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
                "type": "tool_result",
                "toolName": "read_workspace_file",
                "status": "success",
                "latencyMs": 12,
                "arguments": {"path": "README.md"},
                "output": {"bytes": 128},
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
            "risk": "写入",
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


class ScopedApprovalBackend(ApprovalBackend):
    def run(self, question, event_sink):
        self.questions.append(question)
        event = {
            "type": "approval_required",
            "approvalId": f"approval_{len(self.questions)}",
            "runId": "run_approval",
            "toolName": "write_workspace_file",
            "risk": "写入",
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


async def exercise_tui() -> None:
    backend = FakeBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        assert "KnowFlow" in str(app.query_one(".welcome-panel").border_title)
        assert "KNOWFLOW" in str(app.query_one(".welcome-brand").render())
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

        composer.load_text("/")
        await pilot.pause(0.05)
        menu = app.query_one(CommandMenu)
        assert menu.matches
        assert menu.has_class("visible")
        assert [item.value for item in menu.matches[:3]] == [
            "/help",
            "/new",
            "/clear",
        ]
        assert any(item.value == "/status" for item in menu.matches)
        assert "查看命令与快捷键" in str(
            menu.query_one(".command-menu-title").render()
        )
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert composer.text == "/help "
        assert [item.value for item in menu.matches] == [
            "/help commands",
            "/help shortcuts",
            "/help tui",
        ]
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert not menu.matches
        assert any(
            "help子命令" in str(item.render()) for item in app.query(".notice")
        )
        assert not menu.matches
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert not menu.matches

        composer.load_text("/he")
        await pilot.pause(0.05)
        assert [item.value for item in menu.matches] == ["/help"]
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert composer.text == "/help "
        assert [item.value for item in menu.matches] == [
            "/help commands",
            "/help shortcuts",
            "/help tui",
        ]
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert not menu.matches

        composer.load_text("/help c")
        await pilot.pause(0.05)
        assert [item.value for item in menu.matches] == [
            "/help commands",
            "/help shortcuts",
        ]
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert any(
            "help子命令" in str(item.render())
            for item in app.query(".notice")
        )
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
        assert "已完成" in str(app.query_one("#run-status").render())
        assert "test-model" in str(app.query_one("#status-bar").render())

        await pilot.press("up")
        await pilot.pause(0.05)
        assert composer.text == "hello"
        composer.clear()

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
        assert [item.value for item in menu.matches] == [
            "/help commands",
            "/help shortcuts",
            "/help tui",
        ]
        await pilot.press("escape")

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


async def exercise_narrow_command_menu() -> None:
    app = KnowFlowTui(FakeBackend(), assume_yes=False)
    async with app.run_test(size=(48, 20)) as pilot:
        app.query_one(Composer).load_text("/")
        await pilot.pause(0.05)
        menu = app.query_one(CommandMenu)
        assert menu.matches
        assert 0 < menu.size.width < 48
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
        backend.release.set()
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
        backend.release.set()
        for _ in range(30):
            await pilot.pause(0.05)
            if not app.running:
                break
        assert app.session.queue_paused
        assert backend.questions == ["first fails"]
        composer.load_text("/continue")
        await pilot.press("enter")
        for _ in range(30):
            await pilot.pause(0.05)
            if backend.questions == ["first fails", "second waits"] and not app.running:
                break
        assert backend.questions == ["first fails", "second waits"]
        assert not app.session.queue_paused


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
    ):
        assert not any(
            secret in redact_public_detail(secret_text)
            for secret in (
                "bearer-secret",
                "command-secret",
                "eyJheader.payload.signature",
            )
        )

    class FakeRemoteClient:
        def __init__(self):
            self.calls = []

        def request(self, method, path):
            self.calls.append((method, path))

    remote_client = FakeRemoteClient()
    tui_backend = TuiBackend(
        local_agent=None,
        remote_client=remote_client,
        tools=True,
        model_id=None,
        skill_id=None,
    )
    assert tui_backend.cancel("run_cancel")
    assert remote_client.calls == [
        ("POST", "/api/agent/runs/run_cancel/cancel")
    ]
    assert not tui_backend.cancel(None)
    original_data_home = os.environ.get("XDG_DATA_HOME")
    with TemporaryDirectory() as data_home:
        os.environ["XDG_DATA_HOME"] = data_home
        asyncio.run(exercise_tui())
        asyncio.run(exercise_remote_streaming())
        asyncio.run(exercise_live_status())
        asyncio.run(exercise_narrow_command_menu())
        asyncio.run(exercise_approval())
        asyncio.run(exercise_session_approval())
        asyncio.run(exercise_queue())
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
