from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import (
    AgentLoopLimitError,
    ToolRegistry,
)
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.web_search import WebSearchArguments
from langgraph_test_helper import run_langgraph_agent


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
    result = run_langgraph_agent(
        gateway=gateway,
        max_tool_rounds=3,
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
    streaming = run_langgraph_agent(
        gateway=StreamingGateway(),
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
    direct = run_langgraph_agent(
        gateway=direct_gateway,
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
    unknown = run_langgraph_agent(
        gateway=unknown_gateway,
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
        run_langgraph_agent(
            gateway=limited_gateway,
            max_tool_rounds=1,
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
        run_langgraph_agent(
            gateway=RaisingGateway(),
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
        run_langgraph_agent(
            gateway=FakeGateway([{"role": "assistant", "content": None}]),
            messages=[{"role": "user", "content": "x"}], config={},
            registry=make_registry(), trace=empty_trace,
        )
        raise AssertionError("empty model response should raise")
    except ValueError:
        step = empty_trace.snapshot()[0]
        assert step["status"] == "failed"
        assert step["title"] == "Model response was invalid"
        assert step["errorCode"] == "invalid_model_response"

    barrier = threading.Barrier(2, timeout=3)
    concurrent_threads: list[int] = []
    serial_calls: list[str] = []

    def concurrent_read(label: str):
        def run(_args):
            concurrent_threads.append(threading.get_ident())
            barrier.wait()
            return {"label": label}

        return run

    parallel_registry = ToolRegistry()
    for name in ("read_alpha", "read_beta"):
        parallel_registry.register(
            name=name,
            description=f"Read {name}.",
            input_schema={"type": "object", "properties": {}},
            handler=concurrent_read(name),
            read_only=True,
            concurrency_safe=True,
        )
    parallel_registry.register(
        name="serial_boundary",
        description="Run after the safe read batch.",
        input_schema={"type": "object", "properties": {}},
        handler=lambda _args: (
            serial_calls.append("serial") or {"serial": True}
        ),
        read_only=True,
        concurrency_safe=False,
    )

    def empty_call(name: str, call_id: str) -> dict:
        return {
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": "{}"},
        }

    parallel_gateway = FakeGateway(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    empty_call("read_alpha", "call-alpha"),
                    empty_call("read_beta", "call-beta"),
                    empty_call("serial_boundary", "call-serial"),
                ],
            },
            {
                "role": "assistant",
                "content": "Parallel reads completed.",
            },
        ]
    )
    parallel_result = run_langgraph_agent(
        gateway=parallel_gateway,
        messages=[{"role": "user", "content": "Read both sources."}],
        config={"model_name": "fake"},
        registry=parallel_registry,
    )
    assert parallel_result.answer == "Parallel reads completed."
    assert [item.tool_name for item in parallel_result.executions] == [
        "read_alpha",
        "read_beta",
        "serial_boundary",
    ]
    assert len(set(concurrent_threads)) == 2
    assert serial_calls == ["serial"]

    print(
        "agent loop batches safe reads and keeps serial boundaries"
    )


if __name__ == "__main__":
    main()
