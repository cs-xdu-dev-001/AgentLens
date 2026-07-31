from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

from fastapi import HTTPException
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


def create_chat_model(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": name,
            "provider": "openai",
            "modelType": "chat",
            "baseUrl": "https://example.invalid/v1",
            "apiKey": "test-key",
            "modelName": name.lower().replace(" ", "-"),
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "session-model-selection.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "session-model-selection-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    alice = TestClient(app_module.app)
    bob = TestClient(app_module.app)
    register(alice, "session-model-alice")
    register(bob, "session-model-bob")
    alice_id = int(
        runtime.fetch_one(
            "SELECT id FROM app_user WHERE username=:username",
            {"username": "session-model-alice"},
        )["id"]
    )
    bob_id = int(
        runtime.fetch_one(
            "SELECT id FROM app_user WHERE username=:username",
            {"username": "session-model-bob"},
        )["id"]
    )

    alice_first = create_chat_model(alice, "Alice First")
    alice_second = create_chat_model(alice, "Alice Second")
    bob_model = create_chat_model(bob, "Bob Private")

    session_id = runtime.ensure_session(
        None,
        None,
        alice_first,
        alice_id,
    )
    runtime.ensure_session(
        session_id,
        None,
        alice_second,
        alice_id,
    )
    selected = runtime.fetch_one(
        "SELECT chat_model_config_id FROM chat_session WHERE id=:id",
        {"id": session_id},
    )
    assert int(selected["chat_model_config_id"]) == alice_second

    runtime.ensure_session(session_id, None, None, alice_id)
    preserved = runtime.fetch_one(
        "SELECT chat_model_config_id FROM chat_session WHERE id=:id",
        {"id": session_id},
    )
    assert int(preserved["chat_model_config_id"]) == alice_second

    try:
        runtime.ensure_session(session_id, None, bob_model, alice_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("cross-user model selection was accepted")
    isolated = runtime.fetch_one(
        "SELECT chat_model_config_id FROM chat_session WHERE id=:id",
        {"id": session_id},
    )
    assert int(isolated["chat_model_config_id"]) == alice_second

    try:
        runtime.ensure_session(session_id, None, bob_model, bob_id)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("cross-user session access was accepted")

    runtime.db.engine.dispose()
    db_path.unlink(missing_ok=True)
    print("chat session model selection is durable and user isolated")


if __name__ == "__main__":
    main()
