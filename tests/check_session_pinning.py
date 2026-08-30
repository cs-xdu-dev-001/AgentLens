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
    db_path = ROOT / "data" / "test-dbs" / "session-pinning.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "session-pinning-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    local_runtime = importlib.import_module("knowflow.services.local_cli_runtime")
    alice = TestClient(app_module.app, raise_server_exceptions=False)
    bob = TestClient(app_module.app, raise_server_exceptions=False)
    register(alice, "pin-alice")
    register(bob, "pin-bob")
    alice_id = int(runtime.fetch_one(
        "SELECT id FROM app_user WHERE username=:username",
        {"username": "pin-alice"},
    )["id"])

    first = runtime.ensure_session(None, None, None, alice_id)
    second = runtime.ensure_session(None, None, None, alice_id)
    runtime.execute(
        "UPDATE chat_session SET title=:title WHERE id=:id",
        {"title": "需要置顶", "id": first},
    )
    runtime.execute(
        "UPDATE chat_session SET title=:title WHERE id=:id",
        {"title": "普通会话", "id": second},
    )

    assert bob.put(
        f"/api/sessions/{first}/pin",
        json={"pinned": True},
    ).status_code == 404
    pinned = alice.put(
        f"/api/sessions/{first}/pin",
        json={"pinned": True},
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["data"] == {"id": first, "pinned": True}
    sessions = alice.get("/api/sessions")
    assert sessions.status_code == 200, sessions.text
    values = sessions.json()["data"]
    assert values[0]["id"] == first, values
    assert values[0]["is_pinned"] == 1, values[0]

    invalid = alice.put(
        f"/api/sessions/{first}/pin",
        json={"pinned": True, "unexpected": "rejected"},
    )
    assert invalid.status_code == 422, invalid.text

    with tempfile.TemporaryDirectory() as value:
        store = local_runtime.LocalSessionStore(Path(value))
        store.save("run_old", title="置顶会话", pinned=True, updatedAt=1)
        store.save("run_new", title="普通会话", pinned=False, updatedAt=2)
        local_sessions = store.list()
        assert local_sessions[0]["runId"] == "run_old", local_sessions
        assert local_sessions[0]["pinned"] is True

    runtime.db.engine.dispose()
    db_path.unlink(missing_ok=True)
    print("session pinning stays user-scoped and consistent across web and local CLI storage")


if __name__ == "__main__":
    main()
