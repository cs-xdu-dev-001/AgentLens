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
    recent = store.list_recent(1, limit=1)
    assert len(recent) == 1
    assert recent[0]["id"] == run["id"]
    assert store.list_recent(2) == []
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

    waiting_run = store.create_run(
        user_id=1,
        session_id="session-waiting-restart",
        user_message_id=19,
        goal_summary="等待持久化审批",
        trigger_mode="auto",
        run_id="run_waiting_restart",
    )
    waiting_steps = store.replace_plan(
        1,
        waiting_run["id"],
        [
            {"title": "写入页面", "kind": "mcp"},
            {"title": "整理结果", "kind": "answer"},
        ],
    )
    store.transition_run(1, waiting_run["id"], "running")
    store.transition_step(
        1,
        waiting_run["id"],
        waiting_steps[0]["id"],
        "running",
    )
    store.transition_step(
        1,
        waiting_run["id"],
        waiting_steps[0]["id"],
        "waiting_approval",
    )
    store.transition_run(1, waiting_run["id"], "waiting_approval")

    assert store.interrupt_stale_runs() == 1
    interrupted = store.get_snapshot(1, run["id"])
    assert interrupted is not None
    assert interrupted["status"] == "interrupted"
    assert interrupted["steps"][0]["status"] == "completed"
    waiting_after_restart = store.get_snapshot(1, waiting_run["id"])
    assert waiting_after_restart is not None
    assert waiting_after_restart["status"] == "waiting_approval"
    assert waiting_after_restart["steps"][0]["status"] == "waiting_approval"

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
