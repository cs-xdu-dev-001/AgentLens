from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.langgraph_agent_engine import (
    LangGraphAgentEngine,
    LangGraphToolCallError,
)


class FakeGateway:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(
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
                "config": config,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if event_callback:
            event_callback({"type": "text_delta", "text": "hello"})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def main() -> None:
    tool_calls = []
    registry = ToolRegistry()
    registry.register(
        name="echo",
        description="Echo text.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=lambda arguments: tool_calls.append(arguments),
    )
    gateway = FakeGateway(
        {"role": "assistant", "content": "hello", "tool_calls": []}
    )
    config = {
        "model_name": "gpt-test",
        "api_mode": "responses",
    }
    trace = AgentTraceRecorder(run_id="run_langgraph_model")
    model_events = []
    execution_events = []
    engine = LangGraphAgentEngine(gateway=gateway)
    graph = engine._graph.get_graph().to_json()
    assert [node["id"] for node in graph["nodes"]] == [
        "__start__",
        "model",
        "__end__",
    ]
    assert [
        (edge["source"], edge["target"])
        for edge in graph["edges"]
    ] == [
        ("__start__", "model"),
        ("model", "__end__"),
    ]

    result = engine.run(
        messages=[{"role": "user", "content": "Say hello"}],
        config=config,
        registry=registry,
        trace=trace,
        parent_step_id="step_root",
        execution_callback=lambda *args: execution_events.append(args),
        model_event_callback=model_events.append,
    )

    assert engine.name == "langgraph"
    assert result.answer == "hello"
    assert result.executions == []
    assert result.trace == trace.snapshot()
    assert gateway.calls == [
        {
            "messages": [{"role": "user", "content": "Say hello"}],
            "config": config,
            "tools": None,
            "tool_choice": None,
        }
    ]
    assert model_events == [{"type": "text_delta", "text": "hello"}]
    assert tool_calls == []
    assert execution_events == []
    assert len(result.trace) == 1
    model_step = result.trace[0]
    assert model_step["kind"] == "model"
    assert model_step["name"] == "model_completion"
    assert model_step["status"] == "success"
    assert model_step["parentId"] == "step_root"
    assert model_step["details"]["engineName"] == "langgraph"
    assert model_step["details"]["modelName"] == "gpt-test"
    assert model_step["details"]["apiMode"] == "responses"

    empty_trace = AgentTraceRecorder(run_id="run_langgraph_empty")
    try:
        LangGraphAgentEngine(
            gateway=FakeGateway({"role": "assistant", "content": None})
        ).run(
            messages=[{"role": "user", "content": "Return nothing"}],
            config={},
            registry=registry,
            trace=empty_trace,
        )
        raise AssertionError("empty model response should fail")
    except ValueError:
        empty_step = empty_trace.snapshot()[0]
        assert empty_step["status"] == "failed"
        assert empty_step["errorCode"] == "invalid_model_response"

    tool_trace = AgentTraceRecorder(run_id="run_langgraph_tool")
    try:
        LangGraphAgentEngine(
            gateway=FakeGateway(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_echo_1",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": '{"text":"hello"}',
                            },
                        }
                    ],
                }
            )
        ).run(
            messages=[{"role": "user", "content": "Use echo"}],
            config={},
            registry=registry,
            trace=tool_trace,
        )
        raise AssertionError("tool calls should fail in model-only mode")
    except LangGraphToolCallError as exc:
        assert exc.code == "langgraph_tools_not_supported"
        tool_step = tool_trace.snapshot()[0]
        assert tool_step["status"] == "failed"
        assert tool_step["errorCode"] == "langgraph_tools_not_supported"
        assert tool_calls == []

    failure_trace = AgentTraceRecorder(run_id="run_langgraph_failure")
    try:
        LangGraphAgentEngine(
            gateway=FakeGateway(RuntimeError("cancelled"))
        ).run(
            messages=[{"role": "user", "content": "Cancel"}],
            config={},
            registry=registry,
            trace=failure_trace,
        )
        raise AssertionError("gateway errors should propagate")
    except RuntimeError as exc:
        assert str(exc) == "cancelled"
        failure_step = failure_trace.snapshot()[0]
        assert failure_step["status"] == "failed"
        assert failure_step["errorCode"] == "model_request_failed"

    print("langgraph model-only engine preserves the public engine contract")


if __name__ == "__main__":
    main()
