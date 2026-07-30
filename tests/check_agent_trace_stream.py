from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def register(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "trace-user",
            "email": "trace-user@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text


def create_chat_model(client: TestClient) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "Trace chat",
            "provider": "openai",
            "modelType": "chat",
            "baseUrl": "https://model.example/v1",
            "apiKey": "model-trace-unit-test-key",
            "modelName": "test-model",
            "temperature": 0.2,
            "maxTokens": 800,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


class FakeProvider:
    def search(self, query: str, top_k: int = 5):
        assert query == "current release"
        assert top_k == 3
        return [
            {
                "title": "Current source",
                "url": "https://example.com/current",
                "snippet": "Current information",
                "score": 0.91,
            }
        ]


class FakeComplete:
    def __call__(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
    ):
        assert tools
        assert tool_choice == "auto"
        if messages[-1]["role"] == "tool":
            return {
                "role": "assistant",
                "content": (
                    "See [Current source]"
                    "(https://example.com/current)."
                ),
            }
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-search-trace",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": (
                            '{"query":"current release","top_k":3}'
                        ),
                    },
                }
            ],
        }


class FakeMemoryManager:
    def active(self, user_id: int) -> bool:
        return True

    def recall(self, user_id: int, query: str):
        return []


class FakeMemoryOperationStore:
    def create_for_message(self, **kwargs):
        return "recall-operation", "write-operation"

    def activity_for_message(self, *, user_id, message_id):
        return {
            "messageId": message_id,
            "summary": {
                "recalled": 0,
                "added": 0,
                "updated": 0,
                "deleted": 0,
            },
            "operations": [
                {
                    "id": "write-operation",
                    "kind": "write",
                    "status": "queued",
                    "attemptCount": 0,
                    "items": [],
                }
            ],
        }


class FakeMemoryOperationRunner:
    def wake(self):
        return None


def parse_sse(text_value: str) -> list[dict]:
    events = []
    for block in text_value.split("\n\n"):
        data_line = next(
            (
                line
                for line in block.splitlines()
                if line.startswith("data: ")
            ),
            None,
        )
        if data_line:
            events.append(json.loads(data_line[6:]))
    return events


def main() -> None:
    db_path = (
        ROOT / "data" / "test-dbs" / "agent-trace-stream.db"
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = (
        f"sqlite:///{db_path.as_posix()}"
    )
    os.environ["KNOWFLOW_SECRET_KEY"] = "trace-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    extensions = importlib.import_module(
        "knowflow.routers.extensions"
    )
    client = TestClient(app_module.app)
    register(client)
    model_id = create_chat_model(client)
    saved = client.put(
        "/api/tool-configs/web_search",
        json={
            "enabled": True,
            "apiKey": "search-trace-unit-test-key",
        },
    )
    assert saved.status_code == 200, saved.text

    extensions.make_web_search_provider = (
        lambda api_key: FakeProvider()
    )
    extensions.gateway.complete = FakeComplete()
    extensions.memory_manager = FakeMemoryManager()
    extensions.memory_operation_store = FakeMemoryOperationStore()
    extensions.memory_operation_runner = FakeMemoryOperationRunner()
    request_payload = {
        "question": "What is new?",
        "chatModelConfigId": model_id,
        "enableTools": True,
        "autoAgent": True,
        "toolMode": "auto",
        "enabledTools": [],
    }
    with client.stream(
        "POST",
        "/api/chat/stream",
        json=request_payload,
    ) as response:
        assert response.status_code == 200, response.text
        events = parse_sse("".join(response.iter_text()))

    steps = [
        event
        for event in events
        if event.get("type") == "agent_step"
    ]
    assert steps
    assert steps[0]["status"] == "running"
    assert any(
        step["kind"] == "tool"
        and step["name"] == "web_search"
        and step["status"] == "running"
        for step in steps
    )
    assert any(
        step["kind"] == "tool"
        and step["name"] == "web_search"
        and step["status"] == "success"
        for step in steps
    )
    first_answer = next(
        index
        for index, event in enumerate(events)
        if event.get("type") == "answer"
    )
    last_trace_event = max(
        index
        for index, event in enumerate(events)
        if event.get("type") == "agent_step"
    )
    assert last_trace_event < first_answer
    done = next(
        event
        for event in events
        if event.get("type") == "done"
    )
    assert done["runId"] == steps[0]["runId"]
    assert done["memoryActivity"]["operations"][0]["status"] == "queued"
    assert done["trace"]
    assert all(
        (
            step["kind"] == "memory"
            and step["name"] == "memory_write"
            and step["status"] == "waiting"
        )
        or step["status"] in {
            "success", "failed", "cancelled"
        }
        for step in done["trace"]
    )

    runtime.execute(
        """
        INSERT INTO chat_message(
            session_id, role, content, trace_json, created_at
        )
        VALUES (
            :session_id, 'assistant', 'Legacy answer', NULL,
            :created_at
        )
        """,
        {
            "session_id": done["sessionId"],
            "created_at": runtime.now_str(),
        },
    )
    history_response = client.get(
        f"/api/sessions/{done['sessionId']}/messages"
    )
    assert history_response.status_code == 200
    history = history_response.json()["data"]
    assistant = next(
        message
        for message in history
        if message["id"] == done["messageId"]
    )
    assert assistant["trace"] == done["trace"]
    legacy = next(
        message
        for message in history
        if message["content"] == "Legacy answer"
    )
    assert legacy["trace"] == []
    serialized = json.dumps(
        assistant["trace"],
        ensure_ascii=False,
    )
    assert "search-trace-unit-test-key" not in serialized
    assert "model-trace-unit-test-key" not in serialized
    print("agent trace streams live and replays from message history")


if __name__ == "__main__":
    main()
