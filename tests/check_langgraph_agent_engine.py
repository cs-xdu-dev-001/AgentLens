from __future__ import annotations

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.langgraph_agent_engine import (
    LangGraphAgentEngine,
    LangGraphToolCallError,
)
from knowflow.services.langgraph_checkpoint import (
    LangGraphCheckpointError,
    LangGraphCheckpointStore,
)


class FakeGateway:
    def __init__(self, *responses):
        self.responses = list(responses)
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
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def run_engine(
    engine: LangGraphAgentEngine,
    registry: ToolRegistry,
    *,
    run_id: str,
    messages: list[dict] | None = None,
    config: dict | None = None,
    trace=None,
    resume: bool = False,
    model_event_callback=None,
):
    return engine.run(
        user_id=17,
        run_id=run_id,
        messages=messages or [],
        config=config or {},
        registry=registry,
        trace=trace,
        parent_step_id="step_root",
        resume_from_checkpoint=resume,
        model_event_callback=model_event_callback,
    )


def main() -> None:
    registry = ToolRegistry()
    tool_calls = []
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

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        checkpoint_path = root / "checkpoints.sqlite3"
        secret = "sk-checkpoint-must-not-store-this"
        config = {
            "model_name": "gpt-test",
            "api_mode": "responses",
            "api_key": secret,
        }
        gateway = FakeGateway(
            RuntimeError("gateway interrupted"),
            {"role": "assistant", "content": "recovered", "tool_calls": []},
        )
        first_trace = AgentTraceRecorder(run_id="run_resume")
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=gateway,
                    checkpoint_db_path=checkpoint_path,
                ),
                registry,
                run_id="run_resume",
                messages=[{"role": "user", "content": "Say hello"}],
                config=config,
                trace=first_trace,
            )
            raise AssertionError("the first model call must fail")
        except RuntimeError as exc:
            assert str(exc) == "gateway interrupted"
            assert first_trace.snapshot()[0]["status"] == "failed"

        assert checkpoint_path.is_file()
        assert secret.encode() not in checkpoint_path.read_bytes()

        model_events = []
        second_trace = AgentTraceRecorder(run_id="run_resume")
        result = run_engine(
            LangGraphAgentEngine(
                gateway=gateway,
                checkpoint_db_path=checkpoint_path,
            ),
            registry,
            run_id="run_resume",
            config=config,
            trace=second_trace,
            resume=True,
            model_event_callback=model_events.append,
        )
        assert result.answer == "recovered"
        assert len(gateway.calls) == 2
        assert gateway.calls[-1]["config"] is config
        assert gateway.calls[-1]["tools"] is None
        assert model_events == [{"type": "text_delta", "text": "hello"}]
        assert second_trace.snapshot()[0]["details"] == {
            "modelName": "gpt-test",
            "apiMode": "responses",
            "engineName": "langgraph",
        }

        completed = run_engine(
            LangGraphAgentEngine(
                gateway=gateway,
                checkpoint_db_path=checkpoint_path,
            ),
            registry,
            run_id="run_resume",
            config=config,
            resume=True,
        )
        assert completed.answer == "recovered"
        assert len(gateway.calls) == 2

        with LangGraphCheckpointStore(checkpoint_path).open(
            create=False
        ) as saver:
            assert saver is not None
            saved = saver.get_tuple(
                {"configurable": {"thread_id": "run_resume"}}
            )
            assert saved is not None
            assert saved.config["configurable"]["thread_id"] == "run_resume"
            assert saved.checkpoint["channel_values"]["schema_version"] == 1
            assert saved.checkpoint["channel_values"]["answer"] == "recovered"

        missing_path = root / "missing.sqlite3"
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=FakeGateway(),
                    checkpoint_db_path=missing_path,
                ),
                registry,
                run_id="run_missing",
                resume=True,
            )
            raise AssertionError("missing checkpoint should fail")
        except LangGraphCheckpointError as exc:
            assert exc.code == "langgraph_checkpoint_not_found"
        assert not missing_path.exists()

        topology_engine = LangGraphAgentEngine(
            gateway=FakeGateway(
                {"role": "assistant", "content": "unused"}
            ),
            checkpoint_db_path=root / "topology.sqlite3",
        )
        graph = topology_engine._graph.get_graph().to_json()
        assert [node["id"] for node in graph["nodes"]] == [
            "__start__",
            "model",
            "__end__",
        ]

        empty_trace = AgentTraceRecorder(run_id="run_empty")
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=FakeGateway(
                        {"role": "assistant", "content": None}
                    ),
                    checkpoint_db_path=root / "empty.sqlite3",
                ),
                registry,
                run_id="run_empty",
                messages=[{"role": "user", "content": "Return nothing"}],
                trace=empty_trace,
            )
            raise AssertionError("empty model response should fail")
        except ValueError:
            empty_step = empty_trace.snapshot()[0]
            assert empty_step["status"] == "failed"
            assert empty_step["errorCode"] == "invalid_model_response"

        tool_trace = AgentTraceRecorder(run_id="run_tool")
        try:
            run_engine(
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
                    ),
                    checkpoint_db_path=root / "tool.sqlite3",
                ),
                registry,
                run_id="run_tool",
                messages=[{"role": "user", "content": "Use echo"}],
                trace=tool_trace,
            )
            raise AssertionError("tool calls should fail in model-only mode")
        except LangGraphToolCallError as exc:
            assert exc.code == "langgraph_tools_not_supported"
            assert tool_trace.snapshot()[0]["status"] == "failed"
            assert tool_calls == []

    print("langgraph engine checkpoints and resumes model-only runs")


if __name__ == "__main__":
    main()
