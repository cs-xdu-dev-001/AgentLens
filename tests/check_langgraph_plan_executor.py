from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.langgraph_plan_executor import (
    LangGraphPlanExecutor,
    PlanStepOutcome,
)


def main() -> None:
    executor = LangGraphPlanExecutor()
    calls: list[tuple[str, bool, list[str]]] = []

    def execute(step, resumes, completed):
        calls.append((step["id"], resumes, list(completed)))
        return PlanStepOutcome(
            answer=f"answer-{step['id']}",
            public_result=f"result-{step['id']}",
        )

    result = executor.run(
        steps=[
            {
                "id": "done",
                "status": "completed",
                "outputSummary": "existing-result",
            },
            {"id": "skip", "status": "running"},
            {"id": "first", "status": "pending"},
            {"id": "second", "status": "failed"},
        ],
        execute_step=execute,
    )
    assert not result.paused
    assert result.answer == "answer-second"
    assert result.executed_step_ids == ["first", "second"]
    assert calls == [
        ("first", False, ["existing-result"]),
        (
            "second",
            False,
            ["existing-result", "result-first"],
        ),
    ]

    paused_calls = []

    def pause(step, resumes, completed):
        paused_calls.append((step["id"], resumes, list(completed)))
        return PlanStepOutcome(
            answer="",
            pause_payload={"paused": True, "stepId": step["id"]},
        )

    paused = executor.run(
        steps=[
            {
                "id": "approval",
                "status": "waiting_approval",
                "outputSummary": None,
            },
            {"id": "later", "status": "pending"},
        ],
        execute_step=pause,
        resume_step_id="approval",
    )
    assert paused.paused
    assert paused.pause_payload == {
        "paused": True,
        "stepId": "approval",
    }
    assert paused_calls == [("approval", True, [])]
    assert paused.executed_step_ids == []

    resumed_calls = []

    def resume(step, resumes, completed):
        resumed_calls.append((step["id"], resumes, list(completed)))
        return PlanStepOutcome(
            answer=f"resumed-{step['id']}",
            public_result=f"resumed-result-{step['id']}",
        )

    resumed = executor.run(
        steps=[
            {"id": "approval", "status": "waiting_approval"},
            {"id": "later", "status": "pending"},
        ],
        execute_step=resume,
        resume_step_id="approval",
    )
    assert not resumed.paused
    assert resumed.answer == "resumed-later"
    assert resumed.executed_step_ids == ["approval", "later"]
    assert resumed_calls == [
        ("approval", True, []),
        ("later", False, ["resumed-result-approval"]),
    ]

    empty = executor.run(steps=[], execute_step=execute)
    assert not empty.paused
    assert empty.answer == ""
    print("LangGraph public-plan execution control flow works")


if __name__ == "__main__":
    main()
