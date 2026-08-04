from __future__ import annotations

import importlib
from pathlib import Path
import sys
from threading import Event

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import Database
from knowflow.services.agent_run_store import AgentRunStore
from knowflow.services.agent_tool_operations import AgentToolOperationStore


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "legacy-agent-retirement.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    database = Database(f"sqlite:///{db_path.as_posix()}")
    runs = AgentRunStore(database=database)
    operations = AgentToolOperationStore(
        database=database,
        approval_timeout_seconds=60,
    )
    run = runs.create_run(
        user_id=1,
        session_id="session-legacy-agent",
        user_message_id=1,
        goal_summary="Legacy write",
        trigger_mode="auto",
        request_payload={
            "question": "Create a page",
            "sessionId": "session-legacy-agent",
            "_agentEngine": "current",
        },
        run_id="run_legacy_agent",
    )
    runs.transition_run(1, run["id"], "running")
    runs.transition_run(1, run["id"], "waiting_approval")
    operation = operations.ensure_waiting(
        user_id=1,
        run_id=run["id"],
        tool_call_id="call_legacy_write",
        tool_name="notion_create_page",
        server_name="Notion",
        risk="write",
        input_summary={"title": "Legacy"},
    )
    assert operations.resolve(
        1,
        operation["approvalId"],
        "allow_once",
    )

    extensions = importlib.import_module("knowflow.routers.extensions")
    original_runs = extensions.agent_runs
    original_operations = extensions.agent_tool_operations
    extensions.agent_runs = runs
    extensions.agent_tool_operations = operations
    try:
        try:
            extensions.execute_persisted_agent_run(
                1,
                run["id"],
                f"approval:{operation['approvalId']}",
                Event(),
                lambda event: None,
            )
            raise AssertionError("legacy approval resume must be rejected")
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "new LangGraph run" in str(exc.detail)
    finally:
        extensions.agent_runs = original_runs
        extensions.agent_tool_operations = original_operations

    assert runs.get_snapshot(1, run["id"])["status"] == "failed"
    restarted = runs.restart_run(
        1,
        run["id"],
        run_id="run_legacy_restarted",
    )
    assert runs.load_request(1, restarted["id"])["_agentEngine"] == "langgraph"
    print("legacy Agent side effects cannot be resumed under LangGraph")


if __name__ == "__main__":
    main()
