from __future__ import annotations

import importlib
import os
from pathlib import Path
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

    completed = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id="session-run-api",
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
    print("agent run API and coordinator checks passed")


if __name__ == "__main__":
    main()
