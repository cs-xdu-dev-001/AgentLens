from __future__ import annotations

import json
import importlib
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Thread
import time

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

from knowflow.services.agent_loop import AgentRunner, ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.approval import AgentApprovalGate, ApprovalBroker


def tool_call(arguments: str = '{"title":"Weekly report"}') -> dict:
    return {
        "id": "call_write_1",
        "type": "function",
        "function": {
            "name": "notion_create_page",
            "arguments": arguments,
        },
    }


class FakeGateway:
    def __init__(self):
        self.responses = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call()],
            },
            {
                "role": "assistant",
                "content": "The write request was handled.",
            },
        ]

    def complete(self, *args, **kwargs):
        return self.responses.pop(0)


def make_registry(calls: list[dict]) -> ToolRegistry:
    schema = {
        "type": "object",
        "properties": {"title": {"type": "string"}},
        "required": ["title"],
        "additionalProperties": False,
    }
    registry = ToolRegistry()
    registry.register(
        name="notion_create_page",
        description="Create a Notion page.",
        input_schema=schema,
        handler=lambda arguments: (
            calls.append(arguments) or {"pageId": "page_1"}
        ),
        read_only=False,
        trace_kind="mcp",
        risk="write",
        server_name="Notion",
    )
    return registry


def wait_for_event(events: Queue, timeout: float = 1.0) -> dict:
    return events.get(timeout=timeout)


def test_broker_owner_allow_once_and_duplicate() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    events: Queue = Queue()
    result: Queue = Queue()
    thread = Thread(
        target=lambda: result.put(
            broker.request(
                user_id=1,
                run_id="run_owner",
                server_name="Notion",
                tool_name="create_page",
                risk="write",
                input_summary='{"title":"Weekly report"}',
                emit=events.put,
            )
        )
    )
    thread.start()
    event = wait_for_event(events)
    approval_id = event["approvalId"]
    assert event["type"] == "approval_required"
    assert event["runId"] == "run_owner"
    assert event["serverName"] == "Notion"
    assert event["toolName"] == "create_page"
    assert event["risk"] == "write"
    assert event["expiresAt"].endswith("Z")
    assert broker.resolve(2, approval_id, "allow_once") is False
    assert broker.resolve(1, approval_id, "allow_once") is True
    assert broker.resolve(1, approval_id, "deny") is False
    assert result.get(timeout=1) == "allow_once"
    thread.join(timeout=1)
    assert not thread.is_alive()


def test_broker_deny_timeout_cancel_and_shutdown() -> None:
    broker = ApprovalBroker(timeout_seconds=0.05)

    denied_events: Queue = Queue()
    denied_result: Queue = Queue()
    denied = Thread(
        target=lambda: denied_result.put(
            broker.request(
                user_id=1,
                run_id="run_deny",
                server_name="Notion",
                tool_name="delete_page",
                risk="destructive",
                input_summary="{}",
                emit=denied_events.put,
            )
        )
    )
    denied.start()
    denied_id = wait_for_event(denied_events)["approvalId"]
    assert broker.resolve(1, denied_id, "deny") is True
    assert denied_result.get(timeout=1) == "deny"
    denied.join(timeout=1)

    assert (
        broker.request(
            user_id=1,
            run_id="run_timeout",
            server_name="Notion",
            tool_name="create_page",
            risk="write",
            input_summary="{}",
        )
        == "timeout"
    )

    cancelled_events: Queue = Queue()
    cancelled_result: Queue = Queue()
    cancelled = Thread(
        target=lambda: cancelled_result.put(
            broker.request(
                user_id=1,
                run_id="run_cancel",
                server_name="Notion",
                tool_name="create_page",
                risk="write",
                input_summary="{}",
                emit=cancelled_events.put,
            )
        )
    )
    cancelled.start()
    wait_for_event(cancelled_events)
    assert broker.cancel_run("run_cancel") == 1
    assert cancelled_result.get(timeout=1) == "deny"
    cancelled.join(timeout=1)

    shutdown_events: Queue = Queue()
    shutdown_result: Queue = Queue()
    shutdown_waiter = Thread(
        target=lambda: shutdown_result.put(
            broker.request(
                user_id=1,
                run_id="run_shutdown",
                server_name="Notion",
                tool_name="create_page",
                risk="write",
                input_summary="{}",
                emit=shutdown_events.put,
            )
        )
    )
    shutdown_waiter.start()
    wait_for_event(shutdown_events)
    assert broker.shutdown() == 1
    assert shutdown_result.get(timeout=1) == "deny"
    shutdown_waiter.join(timeout=1)
    assert (
        broker.request(
            user_id=1,
            run_id="after_shutdown",
            server_name="Notion",
            tool_name="create_page",
            risk="write",
            input_summary="{}",
        )
        == "deny"
    )


def run_agent(
    broker: ApprovalBroker | None,
    events: Queue | None,
    calls: list[dict],
    trace: AgentTraceRecorder | None = None,
) -> dict:
    trace = trace or AgentTraceRecorder(run_id="run_agent_approval")
    gate = (
        AgentApprovalGate(
            broker=broker,
            user_id=1,
            run_id=trace.run_id,
            emit=events.put if events else None,
            trace=trace,
        )
        if broker
        else None
    )
    result = AgentRunner(gateway=FakeGateway()).run(
        messages=[{"role": "user", "content": "Create a weekly report"}],
        config={"model_name": "fake"},
        registry=make_registry(calls),
        trace=trace,
        approval_gate=gate,
    )
    return {
        "result": result,
        "trace": trace.snapshot(),
    }


def test_runner_waits_before_write_and_allows_once() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    events: Queue = Queue()
    calls: list[dict] = []
    outcome: Queue = Queue()
    trace_events: list[dict] = []
    trace = AgentTraceRecorder(
        emit=trace_events.append,
        run_id="run_agent_allow",
    )
    thread = Thread(
        target=lambda: outcome.put(
            run_agent(broker, events, calls, trace)
        )
    )
    thread.start()
    event = wait_for_event(events)
    assert event["stepId"]
    waiting = trace.snapshot()[-1]
    assert waiting["stepId"] == event["stepId"]
    assert waiting["kind"] == "approval"
    assert waiting["status"] == "waiting"
    assert waiting["details"]["approvalId"] == event["approvalId"]
    time.sleep(0.02)
    assert calls == []
    assert broker.resolve(1, event["approvalId"], "allow_once") is True
    value = outcome.get(timeout=1)
    thread.join(timeout=1)
    assert calls == [{"title": "Weekly report"}]
    execution = value["result"].executions[0]
    assert execution.status == "success"
    assert execution.error_code is None
    approval = next(
        step for step in value["trace"] if step["kind"] == "approval"
    )
    assert approval["stepId"] == event["stepId"]
    assert approval["status"] == "success"
    assert approval["outputSummary"] == '{"decision": "allow_once"}'
    assert any(step["kind"] == "mcp" for step in value["trace"])
    resolved = wait_for_event(events)
    assert resolved == {
        "type": "approval_resolved",
        "approvalId": event["approvalId"],
        "stepId": event["stepId"],
        "decision": "allow_once",
        "status": "success",
    }
    assert any(
        item["kind"] == "approval" and item["status"] == "waiting"
        for item in trace_events
    )


def test_runner_denies_times_out_and_requires_stream_gate() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    events: Queue = Queue()
    calls: list[dict] = []
    outcome: Queue = Queue()
    denied_trace = AgentTraceRecorder(run_id="run_agent_deny")
    thread = Thread(
        target=lambda: outcome.put(
            run_agent(broker, events, calls, denied_trace)
        )
    )
    thread.start()
    event = wait_for_event(events)
    assert broker.resolve(1, event["approvalId"], "deny") is True
    denied_outcome = outcome.get(timeout=1)
    denied = denied_outcome["result"].executions[0]
    thread.join(timeout=1)
    assert denied.error_code == "permission_denied"
    assert calls == []
    denied_step = next(
        step
        for step in denied_outcome["trace"]
        if step["kind"] == "approval"
    )
    assert denied_step["status"] == "failed"
    assert denied_step["errorCode"] == "permission_denied"

    timeout_calls: list[dict] = []
    timeout_outcome = run_agent(
        ApprovalBroker(timeout_seconds=0.01),
        Queue(),
        timeout_calls,
    )
    timeout = timeout_outcome["result"].executions[0]
    assert timeout.error_code == "approval_timeout"
    assert timeout_calls == []
    timeout_step = next(
        step
        for step in timeout_outcome["trace"]
        if step["kind"] == "approval"
    )
    assert timeout_step["status"] == "failed"
    assert timeout_step["errorCode"] == "approval_timeout"

    no_gate_calls: list[dict] = []
    no_gate = run_agent(None, None, no_gate_calls)["result"].executions[0]
    assert no_gate.error_code == "approval_required_stream_only"
    assert no_gate_calls == []


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
    assert emitted[0]["details"]["approvalId"] == "apr_public"


def test_gate_events_and_trace_json_are_sanitized() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    product_events: Queue = Queue()
    trace_events: list[dict] = []
    trace = AgentTraceRecorder(
        emit=trace_events.append,
        run_id="run_gate_redaction",
    )
    gate = AgentApprovalGate(
        broker=broker,
        user_id=1,
        run_id=trace.run_id,
        emit=product_events.put,
        trace=trace,
    )
    registry = ToolRegistry()
    schema = {
        "type": "object",
        "properties": {
            "headers": {"type": "object"},
            "access_token": {"type": "string"},
        },
        "additionalProperties": True,
    }
    registry.register(
        name="write_secret",
        description="Write.",
        input_schema=schema,
        handler=lambda arguments: arguments,
        read_only=False,
        risk="write",
        server_name="Notion",
    )
    prepared = registry.prepare(
        {
            "id": "secret_call",
            "function": {
                "name": "write_secret",
                "arguments": json.dumps(
                    {
                        "headers": {
                            "Authorization": "Bearer raw-secret"
                        },
                        "access_token": "ntn_access-secret",
                    }
                ),
            },
        }
    )
    result: Queue = Queue()
    waiter = Thread(
        target=lambda: result.put(
            gate.request(
                prepared.definition,
                prepared.arguments,
                prepared.call_id,
            )
        )
    )
    waiter.start()
    required = wait_for_event(product_events)
    serialized = json.dumps(
        {
            "event": required,
            "trace_json": trace.snapshot(),
            "traceEvents": trace_events,
        },
        ensure_ascii=False,
    )
    assert required["stepId"]
    assert "raw-secret" not in serialized
    assert "ntn_access-secret" not in serialized
    assert "[REDACTED]" in serialized
    assert broker.resolve(1, required["approvalId"], "deny")
    assert result.get(timeout=1) == "deny"
    waiter.join(timeout=1)


def test_approval_api_hides_missing_and_wrong_owner() -> None:
    app = importlib.import_module("main").app
    runtime = importlib.import_module("knowflow.runtime")
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

    events: Queue = Queue()
    result: Queue = Queue()
    waiter = Thread(
        target=lambda: result.put(
            runtime.approval_broker.request(
                user_id=1,
                run_id="run_api",
                server_name="Notion",
                tool_name="create_page",
                risk="write",
                input_summary="{}",
                emit=events.put,
            )
        )
    )
    waiter.start()
    approval_id = wait_for_event(events)["approvalId"]
    assert (
        bob.post(
            f"/api/agent/approvals/{approval_id}",
            json={"decision": "allow_once"},
        ).status_code
        == 404
    )
    resolved = alice.post(
        f"/api/agent/approvals/{approval_id}",
        json={"decision": "allow_once"},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["data"] == {"resolved": True}
    assert result.get(timeout=1) == "allow_once"
    waiter.join(timeout=1)
    assert (
        alice.post(
            f"/api/agent/approvals/{approval_id}",
            json={"decision": "deny"},
        ).status_code
        == 404
    )

    approval_router = importlib.import_module(
        "knowflow.routers.approvals"
    )
    original_broker = approval_router.approval_broker
    expiring_broker = ApprovalBroker(timeout_seconds=0.01)
    approval_router.approval_broker = expiring_broker
    expired_events: Queue = Queue()
    expired_result: Queue = Queue()
    expired_waiter = Thread(
        target=lambda: expired_result.put(
            expiring_broker.request(
                user_id=1,
                run_id="run_expired_api",
                server_name="Notion",
                tool_name="create_page",
                risk="write",
                input_summary="{}",
                emit=expired_events.put,
            )
        )
    )
    try:
        expired_waiter.start()
        expired_id = wait_for_event(expired_events)["approvalId"]
        time.sleep(0.02)
        assert (
            alice.post(
                f"/api/agent/approvals/{expired_id}",
                json={"decision": "allow_once"},
            ).status_code
            == 404
        )
        assert expired_result.get(timeout=1) == "timeout"
        expired_waiter.join(timeout=1)
    finally:
        approval_router.approval_broker = original_broker

    runtime.agent_runs.create_run(
        user_id=1,
        session_id="session-durable-approval",
        user_message_id=1,
        goal_summary="Create a durable page",
        trigger_mode="auto",
        run_id="run_durable_approval",
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
    durable_resumes: Queue = Queue()
    original_executor = approval_router._run_executor
    approval_router.configure_approval_run_executor(
        lambda user_id, run_id, action, cancel_event, publish: (
            durable_resumes.put((user_id, run_id, action))
        )
    )
    try:
        assert (
            bob.post(
                f"/api/agent/approvals/{durable['approvalId']}",
                json={"decision": "allow_once"},
            ).status_code
            == 404
        )
        durable_response = alice.post(
            f"/api/agent/approvals/{durable['approvalId']}",
            json={"decision": "allow_once"},
        )
        assert durable_response.status_code == 200, durable_response.text
        durable_data = durable_response.json()["data"]
        assert durable_data["resolved"] is True
        assert durable_data["runId"] == "run_durable_approval"
        assert durable_data["resumeStarted"] is True
        assert durable_resumes.get(timeout=1) == (
            1,
            "run_durable_approval",
            f"approval:{durable['approvalId']}",
        )
        assert runtime.agent_tool_operations.get(
            1,
            durable["approvalId"],
        )["status"] == "approved"
    finally:
        approval_router.configure_approval_run_executor(original_executor)
    assert (
        alice.post(
            "/api/agent/approvals/apr_missing",
            json={"decision": "deny"},
        ).status_code
        == 404
    )


def main() -> None:
    test_broker_owner_allow_once_and_duplicate()
    test_broker_deny_timeout_cancel_and_shutdown()
    test_runner_waits_before_write_and_allows_once()
    test_runner_denies_times_out_and_requires_stream_gate()
    test_trace_waiting_details_are_sanitized()
    test_gate_events_and_trace_json_are_sanitized()
    test_approval_api_hides_missing_and_wrong_owner()
    print("approval broker, runner gate, and trace sanitization work")


if __name__ == "__main__":
    main()
