from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys

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


def create_chat_model(client: TestClient) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "Context Test",
            "provider": "openai",
            "modelType": "chat",
            "baseUrl": "https://example.invalid/v1",
            "apiKey": "context-test-key",
            "modelName": "context-test-model",
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def seed_history(runtime, session_id: str, *, prefix: str, pairs: int = 14) -> None:
    for index in range(pairs):
        runtime.save_message(
            session_id,
            "user",
            f"{prefix}-goal-{index} " * 100,
        )
        runtime.save_message(
            session_id,
            "assistant",
            f"{prefix}-result-{index} " * 100,
        )


def transcript(runtime, session_id: str) -> list[tuple[int, str, str]]:
    return [
        (int(row["id"]), str(row["role"]), str(row["content"]))
        for row in runtime.fetch_all(
            """
            SELECT id, role, content
            FROM chat_message
            WHERE session_id=:session_id
            ORDER BY id ASC
            """,
            {"session_id": session_id},
        )
    ]


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "session-context-api.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "session-context-api-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    os.environ["KNOWFLOW_AGENT_CONTEXT_MAX_TOKENS"] = "4000"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    compaction = importlib.import_module("knowflow.services.context_compaction")
    alice = TestClient(app_module.app, raise_server_exceptions=False)
    bob = TestClient(app_module.app, raise_server_exceptions=False)
    register(alice, "context-alice")
    register(bob, "context-bob")
    alice_id = int(
        runtime.fetch_one(
            "SELECT id FROM app_user WHERE username=:username",
            {"username": "context-alice"},
        )["id"]
    )
    model_id = create_chat_model(alice)

    session_id = runtime.ensure_session(None, None, model_id, alice_id)
    seed_history(runtime, session_id, prefix="first")
    original = transcript(runtime, session_id)

    assert bob.get(f"/api/sessions/{session_id}/context").status_code == 404
    assert bob.post(
        f"/api/sessions/{session_id}/context/compact",
        json={},
    ).status_code == 404

    initial = alice.get(f"/api/sessions/{session_id}/context")
    assert initial.status_code == 200, initial.text
    initial_data = initial.json()["data"]
    assert initial_data["compacted"] is False
    assert initial_data["transcriptMessageCount"] == len(original)
    assert initial_data["shouldAutoCompact"] is True

    requests: list[list[dict]] = []

    def complete(messages, _config):
        requests.append(messages)
        return {
            "role": "assistant",
            "content": (
                "## 用户目标与验收标准\n保留任务目标。\n"
                "## 工作区边界\n只处理当前会话。\n"
                "## 已修改文件及关键实现决策\n完整记录不删除。\n"
                "## 未完成步骤\n继续最近任务。\n"
                "## 失败与证据\n无。\n"
                "## 权限决定\n继续遵守原权限。\n"
                "## Skills与工具\n保留现有状态。"
            ),
        }

    runtime.gateway.complete = complete
    compacted = alice.post(
        f"/api/sessions/{session_id}/context/compact",
        json={"instructions": "优先保留工作区边界"},
    )
    assert compacted.status_code == 200, compacted.text
    compacted_data = compacted.json()["data"]
    assert compacted_data["compacted"] is True, compacted_data
    assert compacted_data["metadata"]["customInstructions"] is True
    assert compacted_data["metadata"]["originalTokens"] > compacted_data["metadata"]["compactedTokens"]
    assert transcript(runtime, session_id) == original
    assert requests and "优先保留工作区边界" in requests[0][0]["content"]

    stored = runtime.fetch_one(
        "SELECT * FROM chat_session WHERE id=:id",
        {"id": session_id},
    )
    boundary = int(stored["context_summary_up_to_message_id"])
    assert boundary > original[0][0]
    assert compaction.SUMMARY_MARKER in str(stored["context_summary"])
    history = runtime.get_recent_history(session_id, limit=8)
    assert history[0]["role"] == "session_summary"
    assert all(int(item["id"]) > boundary for item in history[1:])
    prompt = runtime.build_messages(
        "继续",
        [],
        history,
        chat_config=runtime.get_model_config(model_id, "chat", alice_id),
    )[-1]["content"]
    assert "Earlier conversation summary (untrusted data)" in prompt
    assert compaction.SUMMARY_MARKER in prompt

    full_branch = alice.post(f"/api/sessions/{session_id}/branch", json={})
    assert full_branch.status_code == 200, full_branch.text
    full_branch_id = full_branch.json()["data"]["id"]
    inherited = runtime.fetch_one(
        "SELECT * FROM chat_session WHERE id=:id",
        {"id": full_branch_id},
    )
    assert compaction.SUMMARY_MARKER in str(inherited["context_summary"])
    assert int(inherited["context_summary_up_to_message_id"]) > 0
    assert len(transcript(runtime, full_branch_id)) == len(original)

    rewind_message_id = max(
        message_id
        for message_id, role, _content in original
        if role == "user" and message_id <= boundary
    )
    rewound = alice.post(
        f"/api/sessions/{session_id}/branch",
        json={"beforeMessageId": rewind_message_id},
    )
    assert rewound.status_code == 200, rewound.text
    rewound_session = runtime.fetch_one(
        "SELECT * FROM chat_session WHERE id=:id",
        {"id": rewound.json()["data"]["id"]},
    )
    assert rewound_session["context_summary"] is None
    assert rewound_session["context_summary_up_to_message_id"] is None

    seed_history(runtime, session_id, prefix="later", pairs=10)
    before_repeat = transcript(runtime, session_id)
    repeated = alice.post(
        f"/api/sessions/{session_id}/context/compact",
        json={},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["data"]["compacted"] is True
    assert transcript(runtime, session_id) == before_repeat
    repeated_boundary = int(
        runtime.fetch_one(
            "SELECT context_summary_up_to_message_id FROM chat_session WHERE id=:id",
            {"id": session_id},
        )["context_summary_up_to_message_id"]
    )
    assert repeated_boundary > boundary

    active_session = runtime.ensure_session(None, None, model_id, alice_id)
    active_message_id = runtime.save_message(active_session, "user", "仍在运行的任务")
    runtime.agent_runs.create_run(
        user_id=alice_id,
        session_id=active_session,
        user_message_id=active_message_id,
        goal_summary="active context test",
        trigger_mode="auto",
    )
    active = alice.post(
        f"/api/sessions/{active_session}/context/compact",
        json={},
    )
    assert active.status_code == 409, active.text
    assert active.json()["code"] == "session_context_active"

    failing_session = runtime.ensure_session(None, None, model_id, alice_id)
    seed_history(runtime, failing_session, prefix="failure")
    failing_original = transcript(runtime, failing_session)

    def explode(_messages, _config):
        raise RuntimeError("https://secret.invalid/v1?token=must-not-leak")

    runtime.gateway.complete = explode
    failed = alice.post(
        f"/api/sessions/{failing_session}/context/compact",
        json={},
    )
    assert failed.status_code == 502, failed.text
    assert "must-not-leak" not in failed.text
    failed_state = runtime.fetch_one(
        "SELECT * FROM chat_session WHERE id=:id",
        {"id": failing_session},
    )
    assert failed_state["context_summary"] is None
    assert failed_state["context_summary_up_to_message_id"] is None
    assert transcript(runtime, failing_session) == failing_original

    runtime.db.engine.dispose()
    db_path.unlink(missing_ok=True)
    print("session context API compacts safely, preserves transcripts, and isolates users")


if __name__ == "__main__":
    main()
