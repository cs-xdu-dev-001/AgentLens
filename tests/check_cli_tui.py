from __future__ import annotations

import asyncio
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.tui.app import ApprovalScreen, KnowFlowTui  # noqa: E402
from knowflow.tui.widgets import Composer  # noqa: E402


class FakeBackend:
    model_label = "test-model"

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.reset_count = 0

    def run(self, question, event_sink):
        self.questions.append(question)
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

        composer.load_text("hello")
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.05)
            if not app.running and backend.questions:
                break
        assert backend.questions == ["hello"]
        assert not app.running
        assert len(list(app.query(".assistant-message"))) == 1
        assert len(list(app.query(".tool-card"))) == 1
        assert "已完成" in str(app.query_one("#run-status").render())

        composer.load_text("/new")
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert backend.reset_count == 1
        assert not list(app.query(".assistant-message"))


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
    asyncio.run(exercise_approval())
    print("cli tui checks passed")


if __name__ == "__main__":
    main()
