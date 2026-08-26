from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import tempfile

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
    db_path = ROOT / "data" / "test-dbs" / "session-archiving.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "session-archiving-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    local_runtime = importlib.import_module("knowflow.services.local_cli_runtime")
    alice = TestClient(app_module.app, raise_server_exceptions=False)
    bob = TestClient(app_module.app, raise_server_exceptions=False)
    register(alice, "archive-alice")
    register(bob, "archive-bob")
    alice_id = int(
        runtime.fetch_one(
            "SELECT id FROM app_user WHERE username=:username",
            {"username": "archive-alice"},
        )["id"]
    )

    archived_id = runtime.ensure_session(None, None, None, alice_id)
    active_id = runtime.ensure_session(None, None, None, alice_id)
    runtime.execute(
        "UPDATE chat_session SET title=:title, is_pinned=1 WHERE id=:id",
        {"title": "准备归档", "id": archived_id},
    )
    runtime.execute(
        "UPDATE chat_session SET title=:title WHERE id=:id",
        {"title": "保留任务", "id": active_id},
    )

    assert bob.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": True},
    ).status_code == 404
    response = alice.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "id": archived_id,
        "archived": True,
        "pinned": False,
    }

    active = alice.get("/api/sessions")
    assert active.status_code == 200, active.text
    assert [item["id"] for item in active.json()["data"]] == [active_id]
    archived = alice.get("/api/sessions?archived=true")
    assert archived.status_code == 200, archived.text
    archived_values = archived.json()["data"]
    assert [item["id"] for item in archived_values] == [archived_id]
    assert archived_values[0]["is_archived"] == 1
    assert archived_values[0]["is_pinned"] == 0
    repin = alice.put(
        f"/api/sessions/{archived_id}/pin",
        json={"pinned": True},
    )
    assert repin.status_code == 409, repin.text

    runtime.execute(
        """
        INSERT INTO agent_run(id, user_id, session_id, goal_summary, status)
        VALUES (:id, :user_id, :session_id, :goal_summary, :status)
        """,
        {
            "id": "run_active_archive_guard",
            "user_id": alice_id,
            "session_id": active_id,
            "goal_summary": "仍在执行",
            "status": "running",
        },
    )
    busy = alice.put(
        f"/api/sessions/{active_id}/archive",
        json={"archived": True},
    )
    assert busy.status_code == 409, busy.text

    invalid = alice.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": False, "unexpected": "rejected"},
    )
    assert invalid.status_code == 422, invalid.text
    restored = alice.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": False},
    )
    assert restored.status_code == 200, restored.text
    active_ids = {item["id"] for item in alice.get("/api/sessions").json()["data"]}
    assert active_ids == {active_id, archived_id}

    assert alice.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": True},
    ).status_code == 200
    assert runtime.ensure_session(archived_id, None, None, alice_id) == archived_id
    continued = runtime.fetch_one(
        "SELECT is_archived FROM chat_session WHERE id=:id AND user_id=:user_id",
        {"id": archived_id, "user_id": alice_id},
    )
    assert continued and not bool(continued["is_archived"])

    assert alice.put(
        f"/api/sessions/{archived_id}/archive",
        json={"archived": True},
    ).status_code == 200
    created = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id=archived_id,
        user_message_id=None,
        goal_summary="恢复归档会话",
        trigger_mode="ask",
        run_id="run_restore_archived_session",
    )
    assert created["status"] == "planning"
    during_run = runtime.fetch_one(
        "SELECT is_archived FROM chat_session WHERE id=:id AND user_id=:user_id",
        {"id": archived_id, "user_id": alice_id},
    )
    assert during_run and not bool(during_run["is_archived"])

    with tempfile.TemporaryDirectory() as value:
        store = local_runtime.LocalSessionStore(Path(value))
        store.save("run_active", title="活跃", archived=False)
        store.save("run_archived", title="已归档", archived=True)
        assert [item["runId"] for item in store.list()] == ["run_active"]
        assert [item["runId"] for item in store.list(archived=True)] == ["run_archived"]

    runtime.db.engine.dispose()
    db_path.unlink(missing_ok=True)
    print("session archiving is user-scoped, reversible, and consistent across web and local CLI storage")


if __name__ == "__main__":
    main()
