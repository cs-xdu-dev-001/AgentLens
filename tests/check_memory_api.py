from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"


def register(client: TestClient, username: str) -> int:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["user"]["id"])


class FakeMemoryManager:
    def __init__(self) -> None:
        self.enabled: dict[int, bool] = {}
        self.items = {
            "memory-alice": {
                "id": "memory-alice",
                "memory": "Alice偏好Markdown。",
                "user_id": None,
                "created_at": "2026-07-29 12:00:00",
            }
        }

    def settings(self, user_id: int):
        return {
            "provider": "mem0",
            "version": "2.0.14",
            "configured": True,
            "enabled": self.enabled.get(user_id, False),
            "available": True,
        }

    def set_enabled(self, user_id: int, enabled: bool):
        self.enabled[user_id] = enabled
        return self.settings(user_id)

    def list(self, user_id: int, limit: int):
        return [
            item
            for item in self.items.values()
            if item["user_id"] == user_id
        ][:limit]

    def update(self, user_id: int, memory_id: str, content: str):
        from knowflow.services.memory import MemoryNotFoundError

        item = self.items.get(memory_id)
        if not item or item["user_id"] != user_id:
            raise MemoryNotFoundError(memory_id)
        item["memory"] = content
        return dict(item)

    def delete(self, user_id: int, memory_id: str):
        from knowflow.services.memory import MemoryNotFoundError

        item = self.items.get(memory_id)
        if not item or item["user_id"] != user_id:
            raise MemoryNotFoundError(memory_id)
        del self.items[memory_id]

    def delete_all(self, user_id: int):
        self.items = {
            key: item
            for key, item in self.items.items()
            if item["user_id"] != user_id
        }


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "memory-api.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "memory-api-test-secret"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    os.environ["KNOWFLOW_MEMORY_ENABLED"] = "0"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    memory_router = importlib.import_module("knowflow.routers.memories")
    fake = FakeMemoryManager()
    memory_router.memory_manager = fake

    alice = TestClient(app_module.app)
    bob = TestClient(app_module.app)
    alice_id = register(alice, "memory-alice")
    bob_id = register(bob, "memory-bob")
    fake.items["memory-alice"]["user_id"] = alice_id

    session_id = runtime.ensure_session(
        None,
        None,
        None,
        alice_id,
    )
    runtime.save_message(session_id, "user", "记住Markdown偏好")
    assistant_id = runtime.save_message(
        session_id,
        "assistant",
        "我会尝试记录。",
    )
    _, write_id = runtime.memory_operation_store.create_for_message(
        user_id=alice_id,
        session_id=session_id,
        message_id=assistant_id,
        agent_run_id=None,
        recalled=[],
    )
    runtime.memory_operation_store.mark_failed(
        write_id,
        error_code="memory_upstream_unavailable",
        error_message="记忆服务暂时不可用。",
    )

    owned_activity = alice.get(
        f"/api/messages/{assistant_id}/memory-activity"
    )
    assert owned_activity.status_code == 200, owned_activity.text
    denied_activity = bob.get(
        f"/api/messages/{assistant_id}/memory-activity"
    )
    assert denied_activity.status_code == 404, denied_activity.text
    denied_retry = bob.post(
        f"/api/memory/operations/{write_id}/retry"
    )
    assert denied_retry.status_code == 404, denied_retry.text
    retried = alice.post(
        f"/api/memory/operations/{write_id}/retry"
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["status"] == "queued"
    conflict = alice.post(
        f"/api/memory/operations/{write_id}/retry"
    )
    assert conflict.status_code == 409, conflict.text
    runtime.memory_operation_store.mark_succeeded(
        write_id,
        [
            {
                "event": "ADD",
                "id": "memory-alice",
                "memory": "Alice偏好Markdown。",
            }
        ],
    )

    status = alice.get("/api/memory/settings")
    assert status.status_code == 200, status.text
    assert status.json()["data"] == {
        "provider": "mem0",
        "version": "2.0.14",
        "configured": True,
        "enabled": False,
        "available": True,
    }

    enabled = alice.put(
        "/api/memory/settings",
        json={"enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["enabled"] is True
    assert fake.enabled == {alice_id: True}

    memories = alice.get("/api/memories?limit=20")
    assert memories.status_code == 200, memories.text
    assert [item["id"] for item in memories.json()["data"]] == [
        "memory-alice"
    ]
    assert bob.get("/api/memories").json()["data"] == []

    denied_update = bob.put(
        "/api/memories/memory-alice",
        json={"content": "越权修改"},
    )
    assert denied_update.status_code == 404, denied_update.text
    denied_delete = bob.delete("/api/memories/memory-alice")
    assert denied_delete.status_code == 404, denied_delete.text

    updated = alice.put(
        "/api/memories/memory-alice",
        json={"content": "Alice偏好结构化Markdown。"},
    )
    assert updated.status_code == 200, updated.text
    assert (
        updated.json()["data"]["memory"]
        == "Alice偏好结构化Markdown。"
    )

    deleted = alice.delete("/api/memories/memory-alice")
    assert deleted.status_code == 200, deleted.text
    redacted = alice.get(
        f"/api/messages/{assistant_id}/memory-activity"
    ).json()["data"]
    assert redacted["operations"][1]["items"][0]["content"] == ""
    assert alice.get("/api/memories").json()["data"] == []

    fake.items["memory-new"] = {
        "id": "memory-new",
        "memory": "新记忆",
        "user_id": alice_id,
    }
    cleared = alice.delete("/api/memories")
    assert cleared.status_code == 200, cleared.text
    assert alice.get("/api/memories").json()["data"] == []
    assert bob_id not in fake.enabled

    print("memory API derives user scope from authentication")


if __name__ == "__main__":
    main()
