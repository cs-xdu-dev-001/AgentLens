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
        json={"username": username, "email": f"{username}@example.com", "password": "123456"},
    )
    assert response.status_code == 200, response.text


def create_chat_model(client: TestClient, name: str) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": name,
            "provider": "openai",
            "modelType": "chat",
            "baseUrl": "https://model.example/v1",
            "apiKey": "model-unit-test-key",
            "modelName": "test-model",
            "temperature": 0.2,
            "maxTokens": 800,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


class FakeProvider:
    def __init__(self):
        self.calls = []

    def search(self, query: str, top_k: int = 5):
        self.calls.append((query, top_k))
        return [
            {
                "title": "Current source",
                "url": "https://example.com/current",
                "snippet": "Current information",
                "score": 0.91,
                "published_at": "2026-07-24",
            }
        ]


class FakeComplete:
    def __init__(self):
        self.calls = []

    def __call__(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if not tools:
            return {"role": "assistant", "content": "No tools configured."}
        if messages[-1]["role"] == "tool":
            if event_callback is not None:
                event_callback(
                    {
                        "type": "text_delta",
                        "text": (
                            "See [Current source]"
                            "(https://example.com/current)."
                        ),
                    }
                )
            return {
                "role": "assistant",
                "content": "See [Current source](https://example.com/current).",
            }
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-search-1",
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "arguments": '{"query":"current release","top_k":3}',
                    },
                }
            ],
        }


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "agent-web-search.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "agent-flow-test-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    runtime = importlib.import_module("knowflow.runtime")
    extensions = importlib.import_module("knowflow.routers.extensions")
    alice = TestClient(app_module.app)
    bob = TestClient(app_module.app)
    register(alice, "agent-alice")
    register(bob, "agent-bob")
    alice_model = create_chat_model(alice, "Alice chat")
    bob_model = create_chat_model(bob, "Bob chat")

    saved = alice.put(
        "/api/tool-configs/web_search",
        json={"enabled": True, "apiKey": "search-unit-test-key"},
    )
    assert saved.status_code == 200, saved.text

    provider = FakeProvider()
    extensions.make_web_search_provider = lambda api_key: (
        provider if api_key == "search-unit-test-key" else None
    )
    complete = FakeComplete()
    extensions.gateway.complete = complete

    response = alice.post(
        "/api/chat",
        json={
            "question": "What is new?",
            "chatModelConfigId": alice_model,
            "enableTools": True,
            "autoAgent": False,
            "toolMode": "auto",
            "enabledTools": [],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["answer"] == "See [Current source](https://example.com/current)."
    assert data["toolCalls"][0]["toolName"] == "web_search"
    assert provider.calls == [("current release", 3)]
    assert complete.calls[0]["tool_choice"] == "auto"
    assert complete.calls[1]["messages"][-1]["role"] == "tool"
    assert "https://example.com/current" in complete.calls[1]["messages"][-1]["content"]

    tool_rows = runtime.fetch_all(
        "SELECT * FROM agent_tool_call WHERE message_id=:message_id",
        {"message_id": data["messageId"]},
    )
    assert len(tool_rows) == 1
    assert tool_rows[0]["tool_name"] == "web_search"

    bob_response = bob.post(
        "/api/chat",
        json={
            "question": "What is new?",
            "chatModelConfigId": bob_model,
            "enableTools": True,
            "autoAgent": False,
            "toolMode": "auto",
            "enabledTools": [],
        },
    )
    assert bob_response.status_code == 200, bob_response.text
    assert bob_response.json()["data"]["answer"] == "No tools configured."
    assert complete.calls[-1]["tools"] is None
    assert provider.calls == [("current release", 3)]
    print("native agent chat uses only the current user's web search tool")


if __name__ == "__main__":
    main()
