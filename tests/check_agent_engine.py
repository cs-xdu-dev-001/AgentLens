from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_engine import (
    AgentEngineSelectionError,
    CurrentAgentEngine,
    build_agent_engine,
)
from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder


class FakeGateway:
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
        if event_callback:
            event_callback({"type": "text_delta", "text": "done"})
        return {
            "role": "assistant",
            "content": "done",
            "tool_calls": [],
        }


def main() -> None:
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
        handler=lambda arguments: {"text": arguments["text"]},
    )
    trace = AgentTraceRecorder(run_id="run_engine_contract")
    executions = []
    model_events = []
    engine = build_agent_engine(
        "current",
        gateway=FakeGateway(),
        max_tool_rounds=3,
    )

    assert isinstance(engine, CurrentAgentEngine)
    assert engine.name == "current"
    result = engine.run(
        messages=[{"role": "user", "content": "Echo hello"}],
        config={"model_name": "fake"},
        registry=registry,
        trace=trace,
        parent_step_id="step_root",
        execution_callback=lambda execution, parent_id: executions.append(
            (execution, parent_id)
        ),
        model_event_callback=model_events.append,
    )

    assert result.answer == "done"
    assert len(result.executions) == 1
    assert result.executions[0].tool_name == "echo"
    assert executions[0][0] is result.executions[0]
    assert model_events == [{"type": "text_delta", "text": "done"}]
    assert result.trace == trace.snapshot()
    assert [step["kind"] for step in result.trace] == [
        "model",
        "tool",
        "model",
    ]

    try:
        build_agent_engine("langgraph", gateway=FakeGateway())
        raise AssertionError("unsupported engine should fail explicitly")
    except AgentEngineSelectionError as exc:
        assert exc.engine_name == "langgraph"

    print("current agent engine preserves the existing runner contract")


if __name__ == "__main__":
    main()
