from __future__ import annotations

import importlib
import os
from pathlib import Path
from queue import Queue
import sys
from threading import Event
import time

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "agent-run-api.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "agent-run-api-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    run_router = importlib.import_module("knowflow.routers.agent_runs")
    alice = TestClient(app_module.app)
    bob = TestClient(app_module.app)
    register(alice, "run-api-alice")
    register(bob, "run-api-bob")
    alice_row = runtime.fetch_one(
        "SELECT id FROM app_user WHERE username=:username",
        {"username": "run-api-alice"},
    )
    assert alice_row
    alice_id = int(alice_row["id"])

    run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-api",
        user_message_id=1,
        goal_summary="整理资料",
        trigger_mode="plan_only",
        run_id="run_api_test",
    )
    runtime.agent_runs.replace_plan(
        alice_id,
        run["id"],
        [
            {"title": "搜索资料", "kind": "tool"},
            {"title": "整理回答", "kind": "answer"},
        ],
    )
    runtime.agent_runs.transition_run(
        alice_id,
        run["id"],
        "waiting_start",
    )

    snapshot_response = alice.get(f"/api/agent/runs/{run['id']}")
    assert snapshot_response.status_code == 200, snapshot_response.text
    snapshot = snapshot_response.json()["data"]
    assert snapshot["status"] == "waiting_start"
    assert len(snapshot["steps"]) == 2
    assert bob.get(f"/api/agent/runs/{run['id']}").status_code == 404

    with alice.stream(
        "GET",
        f"/api/agent/runs/{run['id']}/events",
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())
    assert '"type": "run_snapshot"' in body
    assert '"id": "run_api_test"' in body

    race_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-race",
        user_message_id=3,
        goal_summary="订阅竞态",
        trigger_mode="plan_only",
        run_id="run_api_race",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        race_run["id"],
        "waiting_start",
    )
    original_subscribe = runtime.agent_run_coordinator.subscribe

    def finish_before_subscribe(run_id):
        runtime.agent_runs.transition_run(
            alice_id,
            run_id,
            "running",
        )
        runtime.agent_runs.transition_run(
            alice_id,
            run_id,
            "completed",
        )
        return None

    runtime.agent_run_coordinator.subscribe = finish_before_subscribe
    try:
        race_events = alice.get(
            f"/api/agent/runs/{race_run['id']}/events"
        )
    finally:
        runtime.agent_run_coordinator.subscribe = original_subscribe
    assert race_events.status_code == 200, race_events.text
    assert '"status": "completed"' in race_events.text
    assert '"type": "done"' in race_events.text

    failed_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-failed",
        user_message_id=4,
        goal_summary="异常收尾",
        trigger_mode="auto",
        run_id="run_api_failed",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        failed_run["id"],
        "running",
    )

    closed_events: Queue = Queue()
    closed_events.put(
        {"type": "stream_closed", "runId": failed_run["id"]}
    )
    runtime.agent_run_coordinator.subscribe = (
        lambda run_id: closed_events
    )
    try:
        failed_events = alice.get(
            f"/api/agent/runs/{failed_run['id']}/events"
        )
    finally:
        runtime.agent_run_coordinator.subscribe = original_subscribe
    assert failed_events.status_code == 200, failed_events.text
    assert '"type": "error"' in failed_events.text
    assert '"code": "agent_run_failed"' in failed_events.text
    failed_snapshot = runtime.agent_runs.get_snapshot(
        alice_id,
        failed_run["id"],
    )
    assert failed_snapshot
    assert failed_snapshot["status"] == "failed"

    entered = Event()
    release = Event()
    cancelled = Event()

    def fake_executor(user_id, run_id, action, cancel_event, publish):
        assert user_id == alice_id
        assert run_id == run["id"]
        assert action == "start"
        entered.set()
        while not release.wait(0.01):
            if cancel_event.is_set():
                runtime.agent_runs.transition_run(
                    user_id,
                    run_id,
                    "cancelled",
                )
                cancelled.set()
                return

    run_router.configure_agent_run_executor(fake_executor)
    start = alice.post(f"/api/agent/runs/{run['id']}/start")
    assert start.status_code == 200, start.text
    assert entered.wait(1)
    duplicate = alice.post(f"/api/agent/runs/{run['id']}/start")
    assert duplicate.status_code == 409, duplicate.text
    assert bob.post(f"/api/agent/runs/{run['id']}/cancel").status_code == 404
    cancel = alice.post(f"/api/agent/runs/{run['id']}/cancel")
    assert cancel.status_code == 200, cancel.text
    assert cancelled.wait(1)
    release.set()
    for _ in range(100):
        if not runtime.agent_run_coordinator.is_active(run["id"]):
            break
        time.sleep(0.01)
    assert not runtime.agent_run_coordinator.is_active(run["id"])

    waiting_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-waiting-approval",
        user_message_id=6,
        goal_summary="等待写入审批",
        trigger_mode="auto",
        run_id="run_api_waiting_approval",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        waiting_run["id"],
        "running",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        waiting_run["id"],
        "waiting_approval",
    )
    waiting_operation = runtime.agent_tool_operations.ensure_waiting(
        user_id=alice_id,
        run_id=waiting_run["id"],
        tool_call_id="call_cancelled_approval",
        tool_name="mcp_notes_create",
        server_name="Notes",
        risk="write",
        input_summary={"title": "cancelled"},
    )
    waiting_cancel = alice.post(
        f"/api/agent/runs/{waiting_run['id']}/cancel"
    )
    assert waiting_cancel.status_code == 200, waiting_cancel.text
    assert waiting_cancel.json()["data"]["run"]["status"] == "cancelled"
    cancelled_operation = runtime.agent_tool_operations.get(
        alice_id,
        waiting_operation["approvalId"],
    )
    assert cancelled_operation is not None
    assert cancelled_operation["status"] == "cancelled"
    stale_approval = alice.post(
        f"/api/agent/approvals/{waiting_operation['approvalId']}",
        json={"decision": "allow_once"},
    )
    assert stale_approval.status_code == 404, stale_approval.text

    completed = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-completed",
        user_message_id=2,
        goal_summary="已完成任务",
        trigger_mode="auto",
        run_id="run_api_completed",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        completed["id"],
        "running",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        completed["id"],
        "completed",
    )
    invalid_resume = alice.post(
        f"/api/agent/runs/{completed['id']}/resume"
    )
    assert invalid_resume.status_code == 409, invalid_resume.text

    isolated_resume = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-isolated-resume",
        user_message_id=6,
        goal_summary="隔离恢复",
        trigger_mode="auto",
        run_id="run_api_isolated_resume",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        isolated_resume["id"],
        "running",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        isolated_resume["id"],
        "interrupted",
    )
    foreign_executor_called = Event()

    def isolated_executor(*args, **kwargs):
        foreign_executor_called.set()

    run_router.configure_agent_run_executor(isolated_executor)
    foreign_resume = bob.post(
        f"/api/agent/runs/{isolated_resume['id']}/resume"
    )
    assert foreign_resume.status_code == 404, foreign_resume.text
    assert not foreign_executor_called.is_set()

    restart_source = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-restart",
        user_message_id=5,
        goal_summary="重新运行任务",
        trigger_mode="auto",
        request_payload={
            "question": "重新运行任务",
            "sessionId": "session-run-restart",
        },
        run_id="run_api_restart_source",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        restart_source["id"],
        "running",
    )
    runtime.agent_runs.transition_run(
        alice_id,
        restart_source["id"],
        "failed",
    )
    restarted = Event()

    def restart_executor(user_id, run_id, action, cancel_event, publish):
        assert user_id == alice_id
        assert run_id != restart_source["id"]
        assert action == "restart"
        assert runtime.agent_runs.load_request(user_id, run_id) == {
            "question": "重新运行任务",
            "sessionId": "session-run-restart",
            "_agentEngine": "langgraph",
        }
        runtime.agent_runs.transition_run(user_id, run_id, "running")
        runtime.agent_runs.transition_run(user_id, run_id, "completed")
        restarted.set()

    run_router.configure_agent_run_executor(restart_executor)
    restart_response = alice.post(
        f"/api/agent/runs/{restart_source['id']}/restart"
    )
    assert restart_response.status_code == 200, restart_response.text
    restart_data = restart_response.json()["data"]
    assert restart_data["replacesRunId"] == restart_source["id"]
    assert restart_data["run"]["id"] != restart_source["id"]
    assert restarted.wait(1)
    assert bob.post(
        f"/api/agent/runs/{restart_source['id']}/restart"
    ).status_code == 404
    print("agent run API and coordinator checks passed")


if __name__ == "__main__":
    main()
