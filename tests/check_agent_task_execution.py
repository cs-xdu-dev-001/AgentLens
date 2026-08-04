from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import time

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


def create_model(client: TestClient) -> int:
    response = client.post(
        "/api/model-configs",
        json={
            "name": "Task model",
            "provider": "openai",
            "modelType": "chat",
            "baseUrl": "https://model.example/v1",
            "apiKey": "model-test-key",
            "modelName": "task-model",
            "temperature": 0.2,
            "maxTokens": 800,
        },
    )
    assert response.status_code == 200, response.text
    return int(response.json()["data"]["id"])


def sse_payloads(response) -> list[dict]:
    payloads = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                payloads.append(json.loads(line[6:]))
    return payloads


class FakeProvider:
    def search(self, query: str, top_k: int = 5):
        return [
            {
                "title": "Task source",
                "url": "https://example.com/task",
                "snippet": "Durable task result",
                "score": 0.9,
                "published_at": "2026-07-28",
            }
        ]


class FakeComplete:
    def __init__(self):
        self.message_batches = []

    def __call__(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        self.message_batches.append(
            [dict(message) for message in messages]
        )
        names = {
            item["function"]["name"]
            for item in (tools or [])
        }
        joined = "\n".join(
            str(message.get("content") or "")
            for message in messages
        )
        if "create_task_plan" in names:
            if "简单问候" in joined:
                if event_callback is not None:
                    event_callback(
                        {"type": "text_delta", "text": "你好！"}
                    )
                return {"role": "assistant", "content": "你好！"}
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "create-plan-1",
                        "type": "function",
                        "function": {
                            "name": "create_task_plan",
                            "arguments": json.dumps(
                                {
                                    "steps": [
                                        {
                                            "title": "搜索资料",
                                            "kind": "tool",
                                            "tool_name": "web_search",
                                        },
                                        {
                                            "title": "整理回答",
                                            "kind": "answer",
                                        },
                                    ]
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        if "Current public plan step: 搜索资料" in joined:
            if messages[-1]["role"] == "tool":
                return {
                    "role": "assistant",
                    "content": "已找到可靠来源。",
                }
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "task-search-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": (
                                '{"query":"durable agent tasks","top_k":2}'
                            ),
                        },
                    }
                ],
            }
        if "Current public plan step: 整理回答" in joined:
            return {
                "role": "assistant",
                "content": (
                    "任务执行完成。[来源](https://example.com/task)"
                ),
            }
        return {"role": "assistant", "content": "未识别步骤。"}


class FakeMemoryManager:
    def __init__(self):
        self.recall_queries = []

    @staticmethod
    def active(user_id: int) -> bool:
        return True

    def recall_now(self, user_id: int, query: str):
        self.recall_queries.append(query)
        return [
            {
                "id": "agent-memory-1",
                "memory": "用户偏好简洁的中文回答。",
                "score": 0.9,
            }
        ]


class FakeMemoryRunner:
    def __init__(self):
        self.wake_count = 0

    def wake(self):
        self.wake_count += 1


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "agent-task-execution.db"
    checkpoint_path = (
        ROOT / "data" / "test-dbs" / "agent-task-execution-checkpoints.db"
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    checkpoint_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_SECRET_KEY"] = "agent-task-execution-secret"
    os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    os.environ["KNOWFLOW_LANGGRAPH_CHECKPOINT_DB"] = str(
        checkpoint_path
    )
    sys.path.insert(0, str(BACKEND))

    app_module = importlib.import_module("main")
    extensions = importlib.import_module("knowflow.routers.extensions")
    runtime = importlib.import_module("knowflow.runtime")
    client = TestClient(app_module.app)
    register(client, "task-execution-user")
    model_id = create_model(client)
    saved = client.put(
        "/api/tool-configs/web_search",
        json={"enabled": True, "apiKey": "task-search-key"},
    )
    assert saved.status_code == 200, saved.text
    extensions.make_web_search_provider = lambda api_key: FakeProvider()
    fake_complete = FakeComplete()
    fake_memory = FakeMemoryManager()
    fake_memory_runner = FakeMemoryRunner()
    extensions.gateway.complete = fake_complete
    extensions.memory_manager = fake_memory
    extensions.memory_operation_runner = fake_memory_runner

    simple = client.post(
        "/api/chat/stream",
        json={
            "question": "简单问候",
            "chatModelConfigId": model_id,
            "enableTools": True,
            "autoAgent": True,
        },
    )
    assert simple.status_code == 200, simple.text
    simple_done = next(
        item
        for item in sse_payloads(simple)
        if item["type"] == "done"
    )
    simple_run = client.get(
        f"/api/agent/runs/{simple_done['runId']}"
    ).json()["data"]
    assert simple_run["status"] == "completed"
    assert simple_run["steps"] == []
    assert fake_memory.recall_queries == ["简单问候"]
    assert "用户偏好简洁的中文回答" in json.dumps(
        fake_complete.message_batches[0],
        ensure_ascii=False,
    )

    planned = client.post(
        "/api/chat/stream",
        json={
            "question": "/plan 买菜",
            "chatModelConfigId": model_id,
            "enableTools": True,
            "autoAgent": True,
        },
    )
    assert planned.status_code == 200, planned.text
    planned_events = sse_payloads(planned)
    assert planned_events[0]["type"] == "run_snapshot"
    assert any(item["type"] == "plan_created" for item in planned_events)
    planned_done = next(
        item for item in planned_events if item["type"] == "done"
    )
    run_id = planned_done["runId"]
    snapshot = client.get(
        f"/api/agent/runs/{run_id}"
    ).json()["data"]
    assert snapshot["status"] == "waiting_start"
    assert [step["title"] for step in snapshot["steps"]] == [
        "搜索资料",
        "整理回答",
    ]

    started = client.post(f"/api/agent/runs/{run_id}/start")
    assert started.status_code == 200, started.text
    for _ in range(200):
        snapshot = client.get(
            f"/api/agent/runs/{run_id}"
        ).json()["data"]
        if snapshot["status"] == "completed":
            break
        time.sleep(0.01)
    assert snapshot["status"] == "completed", snapshot
    assert fake_memory.recall_queries == ["简单问候", "买菜"]
    assert fake_memory_runner.wake_count >= 2
    assert [step["status"] for step in snapshot["steps"]] == [
        "completed",
        "completed",
    ]
    assert snapshot["assistantMessageId"]
    message = runtime.fetch_one(
        "SELECT content FROM chat_message WHERE id=:id",
        {"id": snapshot["assistantMessageId"]},
    )
    assert message
    assert "任务执行完成" in message["content"]
    calls = runtime.fetch_all(
        "SELECT * FROM agent_tool_call WHERE run_id=:run_id",
        {"run_id": run_id},
    )
    assert len(calls) == 1
    assert calls[0]["run_step_id"] == snapshot["steps"][0]["id"]
    history = client.get(
        f"/api/sessions/{snapshot['sessionId']}/messages"
    )
    assert history.status_code == 200, history.text
    assistant = next(
        item
        for item in history.json()["data"]
        if item["id"] == snapshot["assistantMessageId"]
    )
    assert assistant["run"]["id"] == run_id
    deleted = client.delete(
        f"/api/sessions/{snapshot['sessionId']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert runtime.fetch_one(
        "SELECT id FROM agent_run WHERE id=:run_id",
        {"run_id": run_id},
    ) is None
    assert assistant["run"]["status"] == "completed"
    print("durable Agent task planning and execution work")


if __name__ == "__main__":
    main()
