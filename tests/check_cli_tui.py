from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.tui.app import ApprovalScreen, KnowFlowTui  # noqa: E402
from knowflow.tui.widgets import CommandMenu, Composer  # noqa: E402


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
        time.sleep(0.35)
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run_slow_tui",
                "answer": "完成",
            }
        )


async def exercise_tui() -> None:
    backend = FakeBackend()
    app = KnowFlowTui(backend, assume_yes=False)
    async with app.run_test(size=(100, 30)) as pilot:
        composer = app.query_one(Composer)
        composer.load_text("line one")
        await pilot.press("shift+enter")
        await pilot.pause(0.05)
        assert composer.text == "\nline one"
        assert backend.questions == []

        composer.load_text("/")
        await pilot.pause(0.05)
        menu = app.query_one(CommandMenu)
        assert menu.matches
        assert menu.has_class("visible")
        await pilot.press("down")
        assert menu.selected == 1
        await pilot.press("escape")
        await pilot.pause(0.05)
        assert not menu.matches

        composer.load_text("/he")
        await pilot.pause(0.05)
        assert [item.value for item in menu.matches] == ["/help"]
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert not menu.matches
        assert any("/new新会话" in str(item.render()) for item in app.query(".notice"))

        composer.load_text("hello")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and backend.questions:
                break
        assert backend.questions == ["hello"]
        assert not app.running
        assert len(list(app.query(".assistant-message"))) == 1
        assert len(list(app.query(".run-activity"))) == 1
        assert len(list(app.query(".activity-step"))) >= 2
        activity = app.query_one(".run-activity")
        assert "执行完成" in str(activity.query_one(".activity-header").render())
        assert any(
            "read_workspace_file" in str(item.render())
            for item in activity.query(".activity-step")
        )
        assert "已完成" in str(app.query_one("#run-status").render())

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
        await pilot.pause(0.15)
        assert app.running
        assert "理解任务" in str(app.query_one("#run-status").render())
        assert "Agent运行" in str(
            app.query_one(".activity-header").render()
        )
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


def main() -> None:
    asyncio.run(exercise_tui())
    asyncio.run(exercise_remote_streaming())
    asyncio.run(exercise_live_status())
    asyncio.run(exercise_narrow_command_menu())
    asyncio.run(exercise_approval())
    print("cli tui checks passed")


if __name__ == "__main__":
    main()
