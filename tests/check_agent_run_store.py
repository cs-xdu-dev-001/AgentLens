from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import Database  # noqa: E402
from knowflow.services.agent_run_store import (  # noqa: E402
    AgentRunStore,
    AgentRunStoreError,
)


def expect_code(code: str, action) -> None:
    try:
        action()
    except AgentRunStoreError as exc:
        assert exc.code == code, exc.code
    else:
        raise AssertionError(f"expected {code}")


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "agent-run-store.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    database = Database(f"sqlite:///{db_path.as_posix()}")
    store = AgentRunStore(database=database)

    run = store.create_run(
        user_id=1,
        session_id="session-alice",
        user_message_id=17,
        goal_summary="整理 Notion 资料",
        trigger_mode="auto",
        request_payload={
            "question": "整理 Notion 资料",
            "chatModelConfigId": 9,
        },
        run_id="run_store_test",
    )
    assert run["status"] == "planning"
    assert run["goalSummary"] == "整理 Notion 资料"
    assert "userId" not in run
    assert store.load_request(1, run["id"]) == {
        "question": "整理 Notion 资料",
        "chatModelConfigId": 9,
    }
    assert store.load_request(2, run["id"]) is None
    expect_code(
        "active_agent_run_exists",
        lambda: store.create_run(
            user_id=1,
            session_id="session-alice",
            user_message_id=18,
            goal_summary="重复任务",
            trigger_mode="auto",
            run_id="run_store_duplicate",
        ),
    )

    steps = store.replace_plan(
        1,
        run["id"],
        [
            {"title": "搜索资料", "kind": "mcp"},
            {"title": "整理回答", "kind": "answer"},
        ],
    )
    assert [step["position"] for step in steps] == [1, 2]
    assert [step["status"] for step in steps] == ["pending", "pending"]

    running = store.transition_run(1, run["id"], "running")
    first = store.transition_step(
        1,
        run["id"],
        steps[0]["id"],
        "running",
    )
    assert running["status"] == "running"
    assert first["status"] == "running"
    snapshot = store.get_snapshot(1, run["id"])
    assert snapshot is not None
    assert snapshot["currentStepId"] == steps[0]["id"]
    assert snapshot["steps"][0]["status"] == "running"
    assert store.get_snapshot(2, run["id"]) is None

    completed = store.transition_step(
        1,
        run["id"],
        steps[0]["id"],
        "completed",
        output_summary="找到 3 个页面",
    )
    assert completed["outputSummary"] == "找到 3 个页面"
    expect_code(
        "illegal_step_transition",
        lambda: store.transition_step(
            1,
            run["id"],
            steps[0]["id"],
            "running",
        ),
    )

    store.update_trace(
        1,
        run["id"],
        [{"stepId": "trace_1", "status": "success"}],
    )
    snapshot = store.get_snapshot(1, run["id"])
    assert snapshot is not None
    assert snapshot["trace"][0]["stepId"] == "trace_1"

    columns = database.table_columns(
        database.engine.connect(),
        "agent_tool_call",
    )
    assert {"run_id", "run_step_id"}.issubset(columns)

    assert store.interrupt_stale_runs() == 1
    interrupted = store.get_snapshot(1, run["id"])
    assert interrupted is not None
    assert interrupted["status"] == "interrupted"
    assert interrupted["steps"][0]["status"] == "completed"

    expect_code(
        "agent_run_not_found",
        lambda: store.transition_run(2, run["id"], "cancelled"),
    )
    expect_code(
        "illegal_run_transition",
        lambda: store.transition_run(1, run["id"], "completed"),
    )
    print("durable agent run store checks passed")


if __name__ == "__main__":
    main()
