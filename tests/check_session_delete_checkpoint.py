from __future__ import annotations

import atexit
import importlib
import os
import shutil
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.base import empty_checkpoint


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TEST_ROOT = ROOT / "data" / "test-dbs" / "session-delete-checkpoint"


def cleanup() -> None:
    runtime = sys.modules.get("knowflow.runtime")
    if runtime is not None:
        runtime.db.engine.dispose()
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


atexit.register(cleanup)


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


def write_checkpoint(store, user_id: int, run_id: str) -> None:
    with store.open() as saver:
        assert saver is not None
        saver.put(
            {
                "configurable": {
                    "thread_id": store.thread_id(user_id, run_id),
                    "checkpoint_ns": "",
                }
            },
            empty_checkpoint(),
            {},
            {},
        )


def has_checkpoint(store, user_id: int, run_id: str) -> bool:
    with store.open(create=False) as saver:
        return bool(
            saver
            and saver.get_tuple(
                {
                    "configurable": {
                        "thread_id": store.thread_id(user_id, run_id)
                    }
                }
            )
        )


def main() -> None:
    cleanup()
    TEST_ROOT.mkdir(parents=True)
    db_path = TEST_ROOT / "knowflow.db"
    checkpoint_path = TEST_ROOT / "checkpoints.sqlite3"
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_LANGGRAPH_CHECKPOINT_DB"] = str(checkpoint_path)
    os.environ["KNOWFLOW_SECRET_KEY"] = "session-checkpoint-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    chat_router = importlib.import_module("knowflow.routers.chat")
    checkpoint_module = importlib.import_module(
        "knowflow.services.langgraph_checkpoint"
    )
    store = checkpoint_module.LangGraphCheckpointStore(checkpoint_path)

    alice = TestClient(app_module.app, raise_server_exceptions=False)
    bob = TestClient(app_module.app, raise_server_exceptions=False)
    alice_id = register(alice, "checkpoint-delete-alice")
    bob_id = register(bob, "checkpoint-delete-bob")

    alice_session = runtime.ensure_session(
        "session-checkpoint-alice", None, None, alice_id
    )
    bob_session = runtime.ensure_session(
        "session-checkpoint-bob", None, None, bob_id
    )
    alice_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id=alice_session,
        user_message_id=None,
        goal_summary="Alice checkpoint",
        trigger_mode="auto",
        run_id="run_checkpoint_alice",
    )
    bob_run = runtime.agent_runs.create_run(
        user_id=bob_id,
        session_id=bob_session,
        user_message_id=None,
        goal_summary="Bob checkpoint",
        trigger_mode="auto",
        run_id="run_checkpoint_bob",
    )
    alice_operation = runtime.agent_tool_operations.ensure_waiting(
        user_id=alice_id,
        run_id=alice_run["id"],
        tool_call_id="call-alice-delete",
        tool_name="mcp__notion__create_page",
        server_name="Notion",
        risk="write",
        input_summary={"title": "Alice"},
    )
    bob_operation = runtime.agent_tool_operations.ensure_waiting(
        user_id=bob_id,
        run_id=bob_run["id"],
        tool_call_id="call-bob-keep",
        tool_name="mcp__notion__create_page",
        server_name="Notion",
        risk="write",
        input_summary={"title": "Bob"},
    )
    runtime.agent_runs.transition_run(
        alice_id, alice_run["id"], "running"
    )
    runtime.agent_runs.transition_run(
        alice_id, alice_run["id"], "completed"
    )
    runtime.agent_runs.transition_run(
        bob_id, bob_run["id"], "running"
    )
    runtime.agent_runs.transition_run(
        bob_id, bob_run["id"], "completed"
    )
    write_checkpoint(store, alice_id, alice_run["id"])
    write_checkpoint(store, bob_id, bob_run["id"])

    deleted = alice.delete(f"/api/sessions/{alice_session}")
    assert deleted.status_code == 200, deleted.text
    assert not has_checkpoint(store, alice_id, alice_run["id"])
    assert has_checkpoint(store, bob_id, bob_run["id"])
    assert runtime.fetch_one(
        "SELECT id FROM chat_session WHERE id=:id",
        {"id": alice_session},
    ) is None
    assert runtime.fetch_one(
        "SELECT id FROM chat_session WHERE id=:id",
        {"id": bob_session},
    ) is not None
    assert runtime.fetch_one(
        "SELECT id FROM agent_tool_operation WHERE id=:id",
        {"id": alice_operation["approvalId"]},
    ) is None
    assert runtime.fetch_one(
        "SELECT id FROM agent_tool_operation WHERE id=:id",
        {"id": bob_operation["approvalId"]},
    ) is not None

    retry_session = runtime.ensure_session(
        "session-checkpoint-retry", None, None, alice_id
    )
    retry_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id=retry_session,
        user_message_id=None,
        goal_summary="Retry checkpoint cleanup",
        trigger_mode="auto",
        run_id="run_checkpoint_retry",
    )
    runtime.agent_runs.transition_run(
        alice_id, retry_run["id"], "running"
    )
    runtime.agent_runs.transition_run(
        alice_id, retry_run["id"], "completed"
    )
    write_checkpoint(store, alice_id, retry_run["id"])

    class FailingStore:
        def delete_threads(self, user_id, run_ids):
            del user_id, run_ids
            raise checkpoint_module.LangGraphCheckpointError(
                "langgraph_checkpoint_unavailable",
                "LangGraph checkpoint存储暂不可用。",
            )

    original_store = chat_router.langgraph_checkpoints
    chat_router.langgraph_checkpoints = FailingStore()
    try:
        failed = alice.delete(f"/api/sessions/{retry_session}")
    finally:
        chat_router.langgraph_checkpoints = original_store

    assert failed.status_code == 503, failed.text
    assert str(checkpoint_path) not in failed.text
    assert runtime.fetch_one(
        "SELECT id FROM chat_session WHERE id=:id",
        {"id": retry_session},
    ) is not None
    assert runtime.fetch_one(
        "SELECT id FROM agent_run WHERE id=:id",
        {"id": retry_run["id"]},
    ) is not None
    assert has_checkpoint(store, alice_id, retry_run["id"])

    active_session = runtime.ensure_session(
        "session-checkpoint-active", None, None, alice_id
    )
    active_run = runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id=active_session,
        user_message_id=None,
        goal_summary="Active synchronous run",
        trigger_mode="auto",
        run_id="run_checkpoint_active",
    )
    runtime.agent_runs.transition_run(
        alice_id, active_run["id"], "running"
    )
    write_checkpoint(store, alice_id, active_run["id"])
    active_delete = alice.delete(f"/api/sessions/{active_session}")
    assert active_delete.status_code == 409, active_delete.text
    assert "agent_run_still_active" in active_delete.text
    assert runtime.fetch_one(
        "SELECT id FROM chat_session WHERE id=:id",
        {"id": active_session},
    ) is not None
    assert has_checkpoint(store, alice_id, active_run["id"])

    cleanup()
    print("session deletion cleans owned LangGraph checkpoints safely")


if __name__ == "__main__":
    main()
