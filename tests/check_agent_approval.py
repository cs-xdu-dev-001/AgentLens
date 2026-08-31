from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from queue import Queue
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "test-dbs" / "agent-approval-api.db"
DB.unlink(missing_ok=True)
os.environ.update(
    KNOWFLOW_DB_URL=f"sqlite:///{DB.as_posix()}",
    KNOWFLOW_SECRET_KEY="approval-test-secret",
    KNOWFLOW_BASE_URL="http://127.0.0.1:8010",
    KNOWFLOW_VECTOR_STORE="local",
)
os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_trace import AgentTraceRecorder


def test_trace_waiting_details_are_sanitized() -> None:
    emitted: list[dict] = []
    trace = AgentTraceRecorder(emit=emitted.append, run_id="run_safe")
    step_id = trace.start_step(
        kind="approval",
        name="approval_required",
        title="Waiting for approval",
        status="waiting",
        input_summary={
            "title": "Weekly report",
            "headers": {"Authorization": "Bearer raw-header-secret"},
        },
        details={
            "approvalId": "apr_public",
            "risk": "write",
            "serverName": "Notion",
            "toolName": "create_page",
            "expiresAt": "2026-07-24T15:10:00Z",
            "access_token": "ntn_access_secret",
            "refresh_token": "refresh-secret",
            "client_secret": "client-secret",
            "code_verifier": "verifier-secret",
        },
    )
    trace.finish_step(
        step_id,
        status="success",
        title="Approval granted",
        output_summary={"decision": "allow_once"},
    )
    serialized = json.dumps(
        {"events": emitted, "trace_json": trace.snapshot()},
        ensure_ascii=False,
    )
    for secret in (
        "raw-header-secret",
        "ntn_access_secret",
        "refresh-secret",
        "client-secret",
        "verifier-secret",
    ):
        assert secret not in serialized
    assert "apr_public" in serialized
    assert "[REDACTED]" in serialized
    assert emitted[0]["status"] == "waiting"


def test_durable_approval_api_is_owner_scoped_and_resumes() -> None:
    app = importlib.import_module("main").app
    runtime = importlib.import_module("knowflow.runtime")
    approval_router = importlib.import_module(
        "knowflow.routers.approvals"
    )
    alice = TestClient(app)
    bob = TestClient(app)
    for client, username in ((alice, "alice"), (bob, "bob")):
        response = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": "123456",
                "displayName": username,
            },
        )
        assert response.status_code == 200, response.text

    runtime.agent_runs.create_run(
        user_id=1,
        session_id="session-durable-approval",
        user_message_id=1,
        goal_summary="Create a durable page",
        trigger_mode="auto",
        run_id="run_durable_approval",
    )
    runtime.agent_runs.transition_run(1, "run_durable_approval", "running")
    runtime.agent_runs.transition_run(
        1,
        "run_durable_approval",
        "waiting_approval",
    )
    durable = runtime.agent_tool_operations.ensure_waiting(
        user_id=1,
        run_id="run_durable_approval",
        tool_call_id="call_durable_write",
        tool_name="notion_create_page",
        server_name="Notion",
        risk="write",
        input_summary={"title": "Durable"},
    )
    waiting_response = alice.get("/api/agent/approvals?status=waiting")
    assert waiting_response.status_code == 200, waiting_response.text
    waiting_items = waiting_response.json()["data"]
    assert [item["approvalId"] for item in waiting_items] == [
        durable["approvalId"]
    ]
    assert waiting_items[0]["sessionId"] == "session-durable-approval"
    assert bob.get("/api/agent/approvals?status=waiting").json()["data"] == []
    assert alice.get(
        "/api/agent/approvals/waiting"
    ).json()["data"][0]["approvalId"] == durable["approvalId"]
    durable_resumes: Queue = Queue()
    original_executor = approval_router._run_executor
    approval_router.configure_approval_run_executor(
        lambda user_id, run_id, action, cancel_event, publish: (
            durable_resumes.put((user_id, run_id, action))
        )
    )
    try:
        assert bob.post(
            f"/api/agent/approvals/{durable['approvalId']}",
            json={"decision": "allow_once"},
        ).status_code == 404
        response = alice.post(
            f"/api/agent/approvals/{durable['approvalId']}",
            json={"decision": "allow_once"},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["resolved"] is True
        assert data["runId"] == "run_durable_approval"
        assert data["resumeStarted"] is True
        assert durable_resumes.get(timeout=1) == (
            1,
            "run_durable_approval",
            f"approval:{durable['approvalId']}",
        )
        assert runtime.agent_tool_operations.get(
            1,
            durable["approvalId"],
        )["status"] == "approved"
        assert alice.get("/api/agent/approvals?status=waiting").json()["data"] == []

        runtime.agent_runs.create_run(
            user_id=1,
            session_id="session-timeout-approval",
            user_message_id=2,
            goal_summary="Expire a durable write",
            trigger_mode="auto",
            run_id="run_timeout_approval",
        )
        runtime.agent_runs.transition_run(
            1,
            "run_timeout_approval",
            "running",
        )
        runtime.agent_runs.transition_run(
            1,
            "run_timeout_approval",
            "waiting_approval",
        )
        timeout_operation = runtime.agent_tool_operations.ensure_waiting(
            user_id=1,
            run_id="run_timeout_approval",
            tool_call_id="call_timeout_write",
            tool_name="notion_create_page",
            server_name="Notion",
            risk="write",
            input_summary={"title": "Timeout"},
        )
        timeout_response = alice.post(
            f"/api/agent/approvals/{timeout_operation['approvalId']}",
            json={"decision": "timeout"},
        )
        assert timeout_response.status_code == 200, timeout_response.text
        assert durable_resumes.get(timeout=1) == (
            1,
            "run_timeout_approval",
            f"approval:{timeout_operation['approvalId']}",
        )
        expired = runtime.agent_tool_operations.get(
            1,
            timeout_operation["approvalId"],
        )
        assert expired is not None
        assert expired["status"] == "expired"
        assert expired["decision"] == "timeout"
    finally:
        approval_router.configure_approval_run_executor(original_executor)

    assert alice.post(
        f"/api/agent/approvals/{durable['approvalId']}",
        json={"decision": "deny"},
    ).status_code == 404
    assert alice.post(
        "/api/agent/approvals/apr_missing",
        json={"decision": "deny"},
    ).status_code == 404


def main() -> None:
    test_trace_waiting_details_are_sanitized()
    test_durable_approval_api_is_owner_scoped_and_resumes()
    extensions = (
        ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
    ).read_text(encoding="utf-8")
    assert '"Approval timed out"' in extensions
    assert '"approval_timeout"' in extensions
    print("durable LangGraph approvals are isolated, resumable, and expiring")


if __name__ == "__main__":
    main()
