from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import CURRENT_SCHEMA_VERSION, Database
from knowflow.services.agent_run_store import AgentRunStore
from knowflow.services.agent_tool_operations import (
    AgentApprovalRunner,
    AgentToolOperationStore,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "operations.sqlite3"
        database = Database(f"sqlite:///{db_path.as_posix()}")
        runs = AgentRunStore(database=database)
        runs.create_run(
            user_id=11,
            session_id="session-operation",
            user_message_id=1,
            goal_summary="Write a page",
            trigger_mode="auto",
            run_id="run-operation",
        )
        current = [datetime(2026, 8, 3, 12, 0, 0)]
        store = AgentToolOperationStore(
            database=database,
            approval_timeout_seconds=30,
            clock=lambda: current[0],
        )

        waiting = store.ensure_waiting(
            user_id=11,
            run_id="run-operation",
            tool_call_id="call-write-1",
            tool_name="mcp__notion__create_page",
            server_name="Notion",
            risk="write",
            input_summary={"title": "Weekly report"},
        )
        duplicate = store.ensure_waiting(
            user_id=11,
            run_id="run-operation",
            tool_call_id="call-write-1",
            tool_name="mcp__notion__create_page",
            server_name="Notion",
            risk="write",
            input_summary={"title": "Weekly report"},
        )
        assert waiting["approvalId"] == duplicate["approvalId"]
        assert waiting["status"] == "waiting"
        assert waiting["expiresAt"].endswith("Z")
        assert waiting["inputSummary"] == {"title": "Weekly report"}
        assert store.resolve(
            12,
            waiting["approvalId"],
            "allow_once",
        ) is None
        approved = store.resolve(
            11,
            waiting["approvalId"],
            "allow_once",
        )
        assert approved is not None
        assert approved["status"] == "approved"
        assert store.resolve(
            11,
            waiting["approvalId"],
            "deny",
        ) is None

        claimed = store.claim_execution(11, waiting["approvalId"])
        assert claimed is not None
        assert claimed["status"] == "executing"
        assert store.claim_execution(11, waiting["approvalId"]) is None
        finished = store.finish_execution(
            11,
            waiting["approvalId"],
            {
                "call_id": "call-write-1",
                "tool_name": "mcp__notion__create_page",
                "arguments": {"title": "Weekly report"},
                "output": {"pageId": "page-1"},
                "status": "success",
                "error_code": None,
                "error_message": None,
                "latency_ms": 42,
            },
        )
        assert finished is not None
        assert finished["status"] == "succeeded"
        assert finished["execution"]["output"] == {"pageId": "page-1"}

        denied = store.ensure_waiting(
            user_id=11,
            run_id="run-operation",
            tool_call_id="call-write-2",
            tool_name="mcp__notion__delete_page",
            server_name="Notion",
            risk="destructive",
            input_summary={"pageId": "page-2"},
        )
        denied_result = store.resolve(
            11,
            denied["approvalId"],
            "deny",
        )
        assert denied_result is not None
        assert denied_result["status"] == "denied"
        assert store.claim_execution(11, denied["approvalId"]) is None

        cancelled = store.ensure_waiting(
            user_id=11,
            run_id="run-operation",
            tool_call_id="call-write-cancelled",
            tool_name="mcp__notion__archive_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-cancelled"},
        )
        assert store.cancel_for_run(12, "run-operation") == 0
        assert store.cancel_for_run(11, "run-operation") == 1
        cancelled_result = store.get(11, cancelled["approvalId"])
        assert cancelled_result is not None
        assert cancelled_result["status"] == "cancelled"
        assert cancelled_result["decision"] == "cancelled"
        assert store.resolve(
            11,
            cancelled["approvalId"],
            "allow_once",
        ) is None
        assert store.claim_execution(11, cancelled["approvalId"]) is None

        expiring = store.ensure_waiting(
            user_id=11,
            run_id="run-operation",
            tool_call_id="call-write-3",
            tool_name="mcp__notion__update_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-3"},
        )
        current[0] += timedelta(seconds=31)
        expired_result = store.resolve(
            11,
            expiring["approvalId"],
            "allow_once",
        )
        assert expired_result is not None
        assert expired_result["status"] == "expired"
        assert expired_result["decision"] == "timeout"
        expired = store.get_for_run(
            11,
            "run-operation",
            statuses={"expired"},
        )
        assert [item["approvalId"] for item in expired] == [
            expiring["approvalId"]
        ]

        runs.create_run(
            user_id=11,
            session_id="session-timeout-runner",
            user_message_id=2,
            goal_summary="Expire without a browser",
            trigger_mode="auto",
            run_id="run-timeout-runner",
        )
        runs.transition_run(11, "run-timeout-runner", "running")
        runs.transition_run(
            11,
            "run-timeout-runner",
            "waiting_approval",
        )
        unattended = store.ensure_waiting(
            user_id=11,
            run_id="run-timeout-runner",
            tool_call_id="call-unattended-write",
            tool_name="mcp__notion__update_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-unattended"},
        )
        current[0] += timedelta(seconds=31)
        resumed: list[dict] = []
        def resume_operation(operation: dict) -> bool:
            resumed.append(operation)
            runs.transition_run(
                int(operation["userId"]),
                str(operation["runId"]),
                "running",
            )
            return True

        runner = AgentApprovalRunner(
            store=store,
            resume=resume_operation,
        )
        assert runner.run_once() is True
        assert len(resumed) == 1
        assert resumed[0]["approvalId"] == unattended["approvalId"]
        assert resumed[0]["status"] == "expired"
        assert resumed[0]["decision"] == "timeout"
        assert store.expire_due() == 0

        runs.create_run(
            user_id=11,
            session_id="session-recover-approved",
            user_message_id=3,
            goal_summary="Recover an approved checkpoint",
            trigger_mode="auto",
            run_id="run-recover-approved",
        )
        runs.transition_run(11, "run-recover-approved", "running")
        runs.transition_run(
            11,
            "run-recover-approved",
            "waiting_approval",
        )
        recoverable = store.ensure_waiting(
            user_id=11,
            run_id="run-recover-approved",
            tool_call_id="call-recover-approved",
            tool_name="mcp__notion__update_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-approved"},
        )
        assert store.resolve(
            11,
            recoverable["approvalId"],
            "allow_once",
        )["status"] == "approved"
        assert runner.run_once() is True
        assert resumed[-1]["approvalId"] == recoverable["approvalId"]

        runs.create_run(
            user_id=11,
            session_id="session-latest-approval",
            user_message_id=4,
            goal_summary="Resume only the latest approval",
            trigger_mode="auto",
            run_id="run-latest-approval",
        )
        runs.transition_run(11, "run-latest-approval", "running")
        runs.transition_run(
            11,
            "run-latest-approval",
            "waiting_approval",
        )
        old_operation = store.ensure_waiting(
            user_id=11,
            run_id="run-latest-approval",
            tool_call_id="call-old-timeout",
            tool_name="mcp__notion__update_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-old"},
        )
        assert store.resolve(
            11,
            old_operation["approvalId"],
            "timeout",
        )["status"] == "expired"
        latest_operation = store.ensure_waiting(
            user_id=11,
            run_id="run-latest-approval",
            tool_call_id="call-latest-waiting",
            tool_name="mcp__notion__update_page",
            server_name="Notion",
            risk="write",
            input_summary={"pageId": "page-latest"},
        )
        resumable_ids = {
            item["approvalId"]
            for item in store.resumable_resolutions()
        }
        assert old_operation["approvalId"] not in resumable_ids
        assert latest_operation["approvalId"] not in resumable_ids
        current[0] += timedelta(seconds=31)
        assert store.expire_due() == 1
        latest_resumable = store.resumable_resolutions()
        assert [
            item["approvalId"]
            for item in latest_resumable
            if item["runId"] == "run-latest-approval"
        ] == [latest_operation["approvalId"]]

        try:
            store.ensure_waiting(
                user_id=12,
                run_id="run-operation",
                tool_call_id="call-cross-user",
                tool_name="mcp__notion__create_page",
                server_name="Notion",
                risk="write",
                input_summary={},
            )
            raise AssertionError("another user must not attach to the run")
        except ValueError:
            pass

        with database.engine.connect() as conn:
            version = conn.exec_driver_sql(
                "SELECT MAX(version) FROM schema_version"
            ).scalar()
        assert version == CURRENT_SCHEMA_VERSION == 10
        database.engine.dispose()

    schema = (ROOT / "backend" / "knowflow" / "db_schema.py").read_text(
        encoding="utf-8"
    )
    assert "UNIQUE (run_id, tool_call_id)" in schema
    assert "uk_agent_tool_operation_call" in schema
    print(
        "durable Agent tool approvals expire and resume without a browser"
    )


if __name__ == "__main__":
    main()
