from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.memory import (
    Mem0MemoryProvider,
    MemoryManager,
    MemoryNotFoundError,
    redact_sensitive_text,
)


class FakeMem0Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.closed = False
        self.memories = {
            "alice-memory": {
                "id": "alice-memory",
                "memory": "Alice偏好Markdown。",
                "user_id": "7",
                "created_at": "2026-07-29 10:00:00",
            },
            "bob-memory": {
                "id": "bob-memory",
                "memory": "Bob偏好纯文本。",
                "user_id": "8",
                "created_at": "2026-07-29 10:00:00",
            },
        }

    def search(self, query, *, top_k, filters, threshold, rerank):
        self.calls.append(
            (
                "search",
                {
                    "query": query,
                    "top_k": top_k,
                    "filters": filters,
                    "threshold": threshold,
                    "rerank": rerank,
                },
            )
        )
        return {"results": [self.memories["alice-memory"]]}

    def get_all(self, *, filters, top_k):
        self.calls.append(("get_all", {"filters": filters, "top_k": top_k}))
        return {
            "results": [
                item
                for item in self.memories.values()
                if item["user_id"] == str(filters["user_id"])
            ]
        }

    def get(self, memory_id):
        self.calls.append(("get", memory_id))
        return self.memories.get(memory_id)

    def add(self, messages, *, user_id, metadata, infer):
        self.calls.append(
            (
                "add",
                {
                    "messages": messages,
                    "user_id": user_id,
                    "metadata": metadata,
                    "infer": infer,
                },
            )
        )
        return {"results": []}

    def update(self, memory_id, text=None, metadata=None):
        self.calls.append(
            (
                "update",
                {
                    "memory_id": memory_id,
                    "text": text,
                    "metadata": metadata,
                },
            )
        )
        self.memories[memory_id]["memory"] = text
        return self.memories[memory_id]

    def delete(self, memory_id):
        self.calls.append(("delete", memory_id))
        self.memories.pop(memory_id, None)

    def delete_all(self, user_id=None):
        self.calls.append(("delete_all", user_id))

    def close(self):
        self.closed = True


class ImmediateExecutor:
    def __init__(self) -> None:
        self.closed = False
        self.shutdown_options = None

    def submit(self, function, **kwargs):
        function(**kwargs)
        return None

    def shutdown(self, wait=False, cancel_futures=False):
        self.closed = True
        self.shutdown_options = (wait, cancel_futures)


def main() -> None:
    client = FakeMem0Client()
    provider = Mem0MemoryProvider(
        client=client,
        search_threshold=0.25,
    )

    results = provider.search(user_id=7, query="报告格式", limit=3)
    assert results[0]["id"] == "alice-memory"
    assert client.calls[-1] == (
        "search",
        {
            "query": "报告格式",
            "top_k": 3,
            "filters": {"user_id": "7"},
            "threshold": 0.25,
            "rerank": False,
        },
    )

    listed = provider.list(user_id=8, limit=10)
    assert [item["id"] for item in listed] == ["bob-memory"]
    assert client.calls[-1] == (
        "get_all",
        {"filters": {"user_id": "8"}, "top_k": 10},
    )

    provider.remember(
        user_id=7,
        messages=[
            {
                "role": "user",
                "content": "我的API key是sk-test-secret，报告默认使用Markdown。",
            },
            {
                "role": "assistant",
                "content": "已记录，Authorization: Bearer bearer-secret。",
            },
        ],
        metadata={
            "session_id": "session-alice",
            "message_id": 12,
            "operation_id": "memop-test",
        },
    )
    add_call = client.calls[-1][1]
    assert add_call["user_id"] == "7"
    assert add_call["infer"] is True
    assert add_call["metadata"] == {
        "source_session_id": "session-alice",
        "source_message_id": 12,
        "source_operation_id": "memop-test",
        "source": "knowflow_chat",
    }
    serialized = str(add_call)
    assert "sk-test-secret" not in serialized
    assert "bearer-secret" not in serialized
    assert "[敏感信息已移除]" in serialized

    updated = provider.update(
        user_id=7,
        memory_id="alice-memory",
        content="Alice偏好结构化Markdown。",
    )
    assert updated["memory"] == "Alice偏好结构化Markdown。"

    try:
        provider.update(
            user_id=8,
            memory_id="alice-memory",
            content="越权修改",
        )
        raise AssertionError("cross-user update should be rejected")
    except MemoryNotFoundError:
        pass

    try:
        provider.delete(user_id=8, memory_id="alice-memory")
        raise AssertionError("cross-user delete should be rejected")
    except MemoryNotFoundError:
        pass

    provider.delete(user_id=7, memory_id="alice-memory")
    assert "alice-memory" not in client.memories

    redacted = redact_sensitive_text(
        "password=hunter2 api_key=tvly-secret token: abcdefghijklmnop"
    )
    assert "hunter2" not in redacted
    assert "tvly-secret" not in redacted
    assert "abcdefghijklmnop" not in redacted
    assert redacted.count("[敏感信息已移除]") == 3

    client.memories["alice-memory"] = {
        "id": "alice-memory",
        "memory": "Alice偏好Markdown。",
        "user_id": "7",
        "created_at": "2026-07-29 10:00:00",
    }
    enabled_by_user: dict[int, bool] = {}
    executor = ImmediateExecutor()
    manager = MemoryManager(
        provider=provider,
        backend_enabled=True,
        default_enabled=False,
        get_user_enabled=lambda user_id: enabled_by_user.get(user_id),
        set_user_enabled=lambda user_id, enabled: enabled_by_user.__setitem__(
            user_id,
            enabled,
        ),
        executor=executor,
    )
    assert manager.settings(7)["enabled"] is False
    assert manager.active(7) is False
    assert manager.recall(7, "报告格式") == []
    manager.set_enabled(7, True)
    assert manager.settings(7)["enabled"] is True
    assert manager.active(7) is True
    assert manager.recall(7, "报告格式")[0]["id"] == "alice-memory"
    manager.remember_now(
        user_id=7,
        session_id="session-alice",
        message_id=98,
        question="优先给结论",
        answer="我会尝试记录。",
        operation_id="memop-now",
    )
    assert client.calls[-1][0] == "add"
    assert (
        client.calls[-1][1]["metadata"]["source_operation_id"]
        == "memop-now"
    )
    manager.remember_async(
        user_id=7,
        session_id="session-alice",
        message_id=99,
        question="以后使用Markdown",
        answer="好的",
    )
    assert client.calls[-1][0] == "add"
    assert client.calls[-1][1]["metadata"]["source_message_id"] == 99
    manager.close()
    assert client.closed is True
    assert executor.closed is True
    assert executor.shutdown_options == (True, False)

    print("Mem0 provider scopes every operation and redacts secrets")


if __name__ == "__main__":
    main()
