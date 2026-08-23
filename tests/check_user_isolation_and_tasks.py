from __future__ import annotations

import importlib
import os
import shutil
import sys
import time
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:
    TestClient = None


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def register(client: TestClient, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "123456"},
    )
    assert response.status_code == 200, response.text


def create_embedding_model(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": name,
            "provider": "local",
            "modelType": "embedding",
            "baseUrl": "local://embedding",
            "apiKey": "",
            "modelName": "local-embedding",
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def wait_document(client: TestClient, document_id: int) -> dict:
    latest = {}
    for _ in range(30):
        response = client.get(f"/api/documents/{document_id}")
        assert response.status_code == 200, response.text
        latest = response.json()["data"]
        task = latest.get("latestTask") or {}
        if latest["parse_status"] in {"success", "failed"} and task.get("status") in {"success", "failed"}:
            return latest
        time.sleep(0.05)
    return latest


def main() -> None:
    if TestClient is None:
        print("skipped: fastapi test client is not installed in this interpreter")
        return

    db_path = ROOT / "data" / "test-dbs" / "isolation.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    upload_dir = ROOT / "data" / "test-uploads" / "user-isolation"
    shutil.rmtree(upload_dir, ignore_errors=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_UPLOAD_DIR"] = str(upload_dir)
    os.environ["KNOWFLOW_SECRET_KEY"] = "user-isolation-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    os.environ["KNOWFLOW_ADOPT_LEGACY_DATA"] = "0"
    sys.path.insert(0, str(BACKEND))
    main_module = importlib.import_module("main")

    runtime = importlib.import_module("knowflow.runtime")
    runtime.execute(
        """
        INSERT INTO model_config(
          user_id, name, provider, model_type, base_url, api_key_cipher,
          model_name, is_default, status, created_at, updated_at
        )
        VALUES (
          NULL, 'Unowned Legacy Model', 'local', 'embedding', 'local://embedding', '',
          'legacy-embedding', 0, 'untested', :created_at, :updated_at
        )
        """,
        {"created_at": runtime.now_str(), "updated_at": runtime.now_str()},
    )

    alice = TestClient(main_module.app)
    bob = TestClient(main_module.app)
    register(alice, "alice")
    register(bob, "bob")

    assert alice.get("/api/model-configs").json()["data"] == []
    assert bob.get("/api/model-configs").json()["data"] == []

    model_id = create_embedding_model(alice, "Alice Embedding")
    kb = alice.post(
        "/api/knowledge-bases",
        json={"name": "Alice KB", "description": "private", "embeddingModelConfigId": model_id},
    )
    assert kb.status_code == 200, kb.text
    kb_data = kb.json()["data"]
    assert "user_id" not in kb_data, kb_data
    kb_id = int(kb_data["id"])

    uploaded = alice.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("alice.md", b"# Alice private RAG note\nretrieval content", "text/markdown")},
    )
    assert uploaded.status_code == 200, uploaded.text
    upload_data = uploaded.json()["data"]
    assert upload_data["parseStatus"] == "parsing", upload_data
    assert isinstance(upload_data["taskId"], int), upload_data

    document = wait_document(alice, int(upload_data["documentId"]))
    assert document["parse_status"] == "success", document
    for private_field in ("user_id", "storage_path", "file_md5"):
        assert private_field not in document, document
    latest_task = document.get("latestTask") or {}
    assert "userId" not in latest_task, latest_task
    assert latest_task["status"] == "success", latest_task
    assert latest_task["stage"] == "done", latest_task
    assert latest_task["progress"] == 100, latest_task

    assert bob.get("/api/model-configs").json()["data"] == []
    assert bob.get("/api/knowledge-bases").json()["data"] == []
    assert bob.get(f"/api/knowledge-bases/{kb_id}").status_code == 404
    assert bob.get(f"/api/documents/{upload_data['documentId']}").status_code == 404
    assert bob.get(f"/api/documents/{upload_data['documentId']}/tasks").status_code == 404

    chat = alice.post(
        "/api/chat",
        json={"knowledgeBaseId": kb_id, "question": "Summarize Alice note", "chatModelConfigId": None},
    )
    assert chat.status_code == 200, chat.text
    chat_data = chat.json()["data"]
    assert "userId" not in (chat_data.get("retrievalRun") or {}), chat_data
    session_id = chat_data["sessionId"]
    session = alice.get("/api/sessions").json()["data"][0]
    assert session["id"] == session_id
    assert "user_id" not in session, session
    assert bob.get("/api/sessions").json()["data"] == []
    assert bob.get(f"/api/sessions/{session_id}/messages").status_code == 404
    assert bob.post(f"/api/sessions/{session_id}/branch", json={}).status_code == 404
    assert bob.get(f"/api/sessions/{session_id}/export").status_code == 404

    exported = alice.get(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    export_data = exported.json()["data"]
    assert export_data["filename"].endswith(".md"), export_data
    assert "Summarize Alice note" in export_data["content"], export_data
    assert "trace_json" not in export_data["content"], export_data

    branched = alice.post(f"/api/sessions/{session_id}/branch", json={})
    assert branched.status_code == 200, branched.text
    branch_data = branched.json()["data"]
    assert branch_data["id"] != session_id, branch_data
    assert branch_data["sourceSessionId"] == session_id, branch_data
    assert "分支" in branch_data["title"], branch_data
    branch_messages = alice.get(
        f"/api/sessions/{branch_data['id']}/messages"
    )
    assert branch_messages.status_code == 200, branch_messages.text
    assert len(branch_messages.json()["data"]) == branch_data["messageCount"]
    assert bob.get(
        f"/api/sessions/{branch_data['id']}/messages"
    ).status_code == 404

    sync_task = alice.post(
        "/api/sync/tasks",
        json={"sourceType": "github", "sourceUrl": "https://example.invalid/repo", "targetType": "knowledge_base"},
    )
    assert sync_task.status_code == 200, sync_task.text
    sync_data = sync_task.json()["data"]
    assert "user_id" not in sync_data, sync_data
    assert "user_id" not in alice.get("/api/sync/tasks").json()["data"][0]
    assert "user_id" not in alice.get(f"/api/sync/tasks/{sync_data['id']}").json()["data"]

    shutil.rmtree(upload_dir, ignore_errors=True)
    print("user-owned data is isolated and document tasks are observable")


if __name__ == "__main__":
    main()
