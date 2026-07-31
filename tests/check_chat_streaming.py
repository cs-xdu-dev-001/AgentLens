from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def parse_sse(payload: str) -> list[dict]:
    events: list[dict] = []
    for block in payload.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[6:]
            for line in block.splitlines()
            if line.startswith("data: ")
        ]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def register(client: TestClient) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": "chat-stream-user",
            "email": "chat-stream-user@example.com",
            "password": "123456",
        },
    )
    assert response.status_code == 200, response.text


def create_model(client: TestClient) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "Responses stream",
            "provider": "openai",
            "modelType": "chat",
            "apiMode": "responses",
            "baseUrl": "https://model.example/v1",
            "apiKey": "stream-unit-test-key",
            "modelName": "stream-model",
            "temperature": 0.2,
            "maxTokens": 800,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


class FakeComplete:
    def __call__(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        assert tools is None
        assert tool_choice is None
        assert event_callback is not None
        event_callback({"type": "text_delta", "text": "alpha"})
        event_callback({"type": "text_delta", "text": "beta"})
        return {"role": "assistant", "content": "alphabeta"}


class FailingComplete:
    def __call__(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        assert event_callback is not None
        event_callback({"type": "text_delta", "text": "partial"})
        raise RuntimeError(
            "upstream failed for sk-live-secret "
            "Authorization: Bearer hidden-token"
        )


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "chat-streaming.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "chat-streaming-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    client = TestClient(app_module.app)
    register(client)
    model_id = create_model(client)
    runtime.gateway.complete = FakeComplete()

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "question": "Stream this answer.",
            "chatModelConfigId": model_id,
            "enableTools": False,
            "autoAgent": False,
        },
    ) as response:
        assert response.status_code == 200, response.text
        events = parse_sse("".join(response.iter_text()))

    answer_events = [
        event["content"]
        for event in events
        if event.get("type") == "answer"
    ]
    assert answer_events == ["alpha", "beta"], answer_events
    done = next(
        event for event in events if event.get("type") == "done"
    )
    message = runtime.fetch_one(
        "SELECT content FROM chat_message WHERE id=:id",
        {"id": done["messageId"]},
    )
    assert message["content"] == "alphabeta"

    assistant_count = runtime.fetch_one(
        "SELECT COUNT(*) AS count FROM chat_message WHERE role='assistant'"
    )["count"]
    runtime.gateway.complete = FailingComplete()
    with client.stream(
        "POST",
        "/api/chat/stream",
        json={
            "question": "Fail after one delta.",
            "chatModelConfigId": model_id,
            "enableTools": False,
            "autoAgent": False,
        },
    ) as response:
        assert response.status_code == 200, response.text
        failed_events = parse_sse("".join(response.iter_text()))
    assert [
        event["content"]
        for event in failed_events
        if event.get("type") == "answer"
    ] == ["partial"]
    error = next(
        event for event in failed_events if event.get("type") == "error"
    )
    assert "RuntimeError" in error["message"]
    assert "sk-live-secret" not in error["message"]
    assert "hidden-token" not in error["message"]
    assert runtime.fetch_one(
        "SELECT COUNT(*) AS count FROM chat_message WHERE role='assistant'"
    )["count"] == assistant_count
    print("normal chat forwards upstream response deltas without duplication")


if __name__ == "__main__":
    main()
