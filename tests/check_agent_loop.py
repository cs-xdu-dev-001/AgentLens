from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import (
    AgentLoopLimitError,
    AgentRunner,
    ToolRegistry,
)
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.web_search import WebSearchArguments


def tool_call(name: str = "web_search", arguments: str = '{"query":"today","top_k":3}'):
    return {
        "id": "call-search-1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class FakeGateway:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, config, *, tools=None, tool_choice=None):
        self.calls.append(
            {
                "messages": [dict(message) for message in messages],
                "config": config,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        return self.responses.pop(0)


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        name="web_search",
        description="Search the public web.",
        arguments_model=WebSearchArguments,
        handler=lambda args: {
            "results": [
                {
                    "title": "Current source",
                    "url": "https://example.com/current",
                    "snippet": args.query,
                }
            ]
        },
        read_only=True,
    )
    return registry


def main() -> None:
    gateway = FakeGateway(
        [
            {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
            {
                "role": "assistant",
                "content": "See [source](https://example.com/current).",
            },
        ]
    )
    trace = AgentTraceRecorder(run_id="run_agent_loop")
    result = AgentRunner(gateway=gateway, max_tool_rounds=3).run(
        messages=[{"role": "user", "content": "What changed today?"}],
        config={"model_name": "fake"},
        registry=make_registry(),
        trace=trace,
        parent_step_id="step_root",
    )
    assert result.answer == "See [source](https://example.com/current)."
    assert len(result.executions) == 1
    assert result.executions[0].status == "success"
    assert gateway.calls[0]["tool_choice"] == "auto"
    tool_message = gateway.calls[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-search-1"
    assert "https://example.com/current" in tool_message["content"]
    assert result.trace == trace.snapshot()
    assert [
        (step["kind"], step["status"])
        for step in result.trace
    ] == [
        ("model", "success"),
        ("tool", "success"),
        ("model", "success"),
    ]
    assert all(
        step["parentId"] == "step_root"
        for step in result.trace
    )

    class StreamingGateway:
        def __init__(self):
            self.round = 0

        def complete(
            self,
            messages,
            config,
            *,
            tools=None,
            tool_choice=None,
            event_callback=None,
        ):
            self.round += 1
            if self.round == 1:
                return {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [tool_call()],
                }
            assert messages[-1]["role"] == "tool"
            if event_callback:
                event_callback({"type": "text_delta", "text": "final "})
                event_callback({"type": "text_delta", "text": "answer"})
                event_callback(
                    {
                        "type": "completed",
                        "message": {
                            "role": "assistant",
                            "content": "final answer",
                            "tool_calls": [],
                        },
                    }
                )
            return {
                "role": "assistant",
                "content": "final answer",
                "tool_calls": [],
            }

    model_events = []
    streaming = AgentRunner(gateway=StreamingGateway()).run(
        messages=[{"role": "user", "content": "Search then answer"}],
        config={"model_name": "fake"},
        registry=make_registry(),
        model_event_callback=model_events.append,
    )
    assert streaming.answer == "final answer"
    assert len(streaming.executions) == 1
    assert [event["text"] for event in model_events if event["type"] == "text_delta"] == [
        "final ",
        "answer",
    ]

    direct_gateway = FakeGateway(
        [{"role": "assistant", "content": "No search needed."}]
    )
    direct = AgentRunner(gateway=direct_gateway).run(
        messages=[{"role": "user", "content": "Say hello"}],
        config={"model_name": "fake"},
        registry=make_registry(),
    )
    assert direct.answer == "No search needed."
    assert direct.executions == []

    unknown_gateway = FakeGateway(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call(name="delete_everything")],
            },
            {"role": "assistant", "content": "The requested tool is unavailable."},
        ]
    )
    unknown = AgentRunner(gateway=unknown_gateway).run(
        messages=[{"role": "user", "content": "Use an unknown tool"}],
        config={"model_name": "fake"},
        registry=make_registry(),
    )
    assert unknown.executions[0].status == "failed"
    assert unknown.executions[0].error_code == "unknown_tool"

    invalid = make_registry().execute(
        tool_call(arguments="{not-json")
    )
    assert invalid.status == "failed"
    assert invalid.error_code == "invalid_arguments"

    limited_gateway = FakeGateway(
        [
            {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
            {"role": "assistant", "content": None, "tool_calls": [tool_call()]},
        ]
    )
    try:
        AgentRunner(gateway=limited_gateway, max_tool_rounds=1).run(
            messages=[{"role": "user", "content": "Loop forever"}],
            config={"model_name": "fake"},
            registry=make_registry(),
        )
        raise AssertionError("tool-call limit should stop the agent")
    except AgentLoopLimitError:
        pass

    failing_trace = AgentTraceRecorder(run_id="run_model_failure")
    class RaisingGateway:
        def complete(self, *args, **kwargs):
            raise RuntimeError("boom")
    try:
        AgentRunner(gateway=RaisingGateway()).run(
            messages=[{"role": "user", "content": "x"}], config={},
            registry=make_registry(), trace=failing_trace,
        )
        raise AssertionError("model failure should raise")
    except RuntimeError:
        step = failing_trace.snapshot()[0]
        assert step["status"] == "failed"
        assert step["title"] == "Model request failed"
        assert step["errorCode"] == "model_request_failed"

    empty_trace = AgentTraceRecorder(run_id="run_invalid_model")
    try:
        AgentRunner(gateway=FakeGateway([{"role": "assistant", "content": None}])).run(
            messages=[{"role": "user", "content": "x"}], config={},
            registry=make_registry(), trace=empty_trace,
        )
        raise AssertionError("empty model response should raise")
    except ValueError:
        step = empty_trace.snapshot()[0]
        assert step["status"] == "failed"
        assert step["title"] == "Model response was invalid"
        assert step["errorCode"] == "invalid_model_response"

    print("agent loop executes registered tools and stops safely")


if __name__ == "__main__":
    main()
