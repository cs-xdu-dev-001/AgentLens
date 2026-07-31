from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.agent_loop import AgentRunner, ToolRegistry


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class FakeGateway:
    @staticmethod
    def complete(messages, config, **options):
        return {"content": "done", "tool_calls": []}


def main() -> None:
    emitted = []
    clock = FakeClock()
    trace = AgentTraceRecorder(
        emit=emitted.append,
        run_id="run_test",
        clock=clock,
    )
    root = trace.start_step(
        kind="system",
        name="agent_run",
        title="开始处理",
    )
    tool = trace.start_step(
        kind="tool",
        name="web_search",
        title="正在联网搜索",
        parent_id=root,
        input_summary={
            "query": "latest release",
            "apiKey": "search-super-secret",
        },
    )
    clock.value = 100.125
    trace.finish_step(
        tool,
        status="success",
        title="联网搜索完成",
        output_summary={
            "count": 3,
            "authorization": "credential-value",
        },
    )
    trace.finish_step(root, status="success", title="处理完成")
    memory = trace.start_step(
        kind="memory",
        name="memory_write",
        title="正在整理长期记忆",
    )
    trace.finish_step(
        memory,
        status="success",
        title="记忆写入完成",
        output_summary={"added": 1},
    )

    assert emitted[0]["status"] == "running"
    assert emitted[1]["parentId"] == root
    assert emitted[2]["stepId"] == tool
    assert emitted[2]["status"] == "success"
    assert emitted[2]["durationMs"] == 125
    serialized = json.dumps(emitted, ensure_ascii=False)
    assert "search-super-secret" not in serialized
    assert "credential-value" not in serialized
    assert "[REDACTED]" in serialized
    snapshot = trace.snapshot()
    assert [step["stepId"] for step in snapshot] == [
        root,
        tool,
        memory,
    ]
    assert all(step["status"] == "success" for step in snapshot)

    model_trace = AgentTraceRecorder(run_id="run_model_trace")
    AgentRunner(gateway=FakeGateway(), max_tool_rounds=0).run(
        messages=[{"role": "user", "content": "hello"}],
        config={
            "model_name": "gpt-safe-display",
            "api_mode": "responses",
            "api_key": "model-super-secret",
            "base_url": "https://private.example/v1",
        },
        registry=ToolRegistry(),
        trace=model_trace,
    )
    model_step = next(
        step
        for step in model_trace.snapshot()
        if step["name"] == "model_completion"
    )
    assert model_step["details"] == {
        "modelName": "gpt-safe-display",
        "apiMode": "responses",
    }
    serialized_model = json.dumps(model_step, ensure_ascii=False)
    assert "model-super-secret" not in serialized_model
    assert "private.example" not in serialized_model

    extension_source = (
        ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
    ).read_text(encoding="utf-8")
    assert 'kind="memory"' in extension_source
    assert "memory_operation_store.create_for_message(" in extension_source
    print("agent trace events are ordered, merged, and sanitized")


if __name__ == "__main__":
    main()
