from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_engine import (
    AgentEngineSelectionError,
    AgentEngineUnavailableError,
    build_agent_engine,
)
from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.langgraph_agent_engine import LangGraphAgentEngine


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
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint_path = Path(temporary) / "langgraph.sqlite3"
        engine = build_agent_engine(
            "langgraph",
            gateway=FakeGateway(),
            max_tool_rounds=3,
            checkpoint_db_path=checkpoint_path,
        )

        assert isinstance(engine, LangGraphAgentEngine)
        assert engine.name == "langgraph"
        result = engine.run(
            user_id=17,
            run_id="run_engine_contract",
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
        assert checkpoint_path.exists()

    assert result.answer == "done"
    assert len(result.executions) == 1
    assert result.executions[0].tool_name == "echo"
    assert executions[0][0] == result.executions[0]
    assert model_events == [{"type": "text_delta", "text": "done"}]
    assert result.trace == trace.snapshot()
    assert [step["kind"] for step in result.trace] == [
        "model",
        "tool",
        "model",
    ]

    for retired in ("current", "unknown", ""):
        try:
            build_agent_engine(retired, gateway=FakeGateway())
            raise AssertionError("unsupported engine should fail explicitly")
        except AgentEngineSelectionError as exc:
            assert exc.engine_name == (retired or "unknown")

    missing_dependency = ModuleNotFoundError(
        "No module named 'langgraph'",
        name="langgraph",
    )
    with patch(
        "knowflow.services.agent_engine.importlib.import_module",
        side_effect=missing_dependency,
    ):
        try:
            build_agent_engine("langgraph", gateway=FakeGateway())
            raise AssertionError("missing dependency should fail explicitly")
        except AgentEngineUnavailableError as exc:
            assert exc.engine_name == "langgraph"

    print("LangGraph is the only supported agent engine")


if __name__ == "__main__":
    main()
