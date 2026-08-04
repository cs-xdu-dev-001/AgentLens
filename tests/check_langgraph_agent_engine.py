from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import (
    AgentLoopLimitError,
    ToolHandlerResult,
    ToolRegistry,
)
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.langgraph_agent_engine import LangGraphAgentEngine
from knowflow.services.langgraph_checkpoint import (
    LangGraphCheckpointError,
    LangGraphCheckpointStore,
)
from knowflow.services.task_planner import register_task_planner
from knowflow.database import Database
from knowflow.services.agent_run_store import AgentRunStore
from knowflow.services.agent_tool_operations import AgentToolOperationStore


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


def tool_call(name: str, arguments: str, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def run_engine(
    engine: LangGraphAgentEngine,
    registry: ToolRegistry,
    *,
    run_id: str,
    messages: list[dict] | None = None,
    config: dict | None = None,
    trace=None,
    resume: bool = False,
    execution_callback=None,
    model_event_callback=None,
    tool_operation_store=None,
    approval_decision=None,
    skill_snapshot=None,
    skill_restore=None,
    memory_recall=None,
    memory_enabled=None,
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
        execution_callback=execution_callback,
        model_event_callback=model_event_callback,
        tool_operation_store=tool_operation_store,
        approval_decision=approval_decision,
        skill_snapshot=skill_snapshot,
        skill_restore=skill_restore,
        memory_recall=memory_recall,
        memory_enabled=(
            memory_recall is not None
            if memory_enabled is None
            else memory_enabled
        ),
    )


def register_tools(
    registry: ToolRegistry,
    search_calls: list[dict],
    unsafe_calls: list[dict],
) -> None:
    registry.register(
        name="web_search",
        description="Search the web.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda arguments: (
            search_calls.append(arguments)
            or {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com",
                    }
                ]
            }
        ),
        engine_names={"current", "langgraph"},
    )
    registry.register(
        name="dangerous_write",
        description="Must not be exposed yet.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        handler=lambda arguments: unsafe_calls.append(arguments) or {},
        read_only=False,
    )


def register_read_only_mcp(
    registry: ToolRegistry,
    calls: list[dict],
) -> None:
    registry.register(
        name="mcp_notes_search",
        description="Search notes without changing them.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=lambda arguments: (
            calls.append(arguments)
            or {"results": [{"title": "Note"}]}
        ),
        read_only=True,
        engine_names={"current", "langgraph"},
        trace_kind="mcp",
        risk="read",
        server_name="Notes",
    )


def register_write_mcp(
    registry: ToolRegistry,
    calls: list[dict],
) -> None:
    registry.register(
        name="mcp_notes_create",
        description="Create a note.",
        input_schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        handler=lambda arguments: (
            calls.append(arguments)
            or {"pageId": f"page-{len(calls)}"}
        ),
        read_only=False,
        engine_names={"current", "langgraph"},
        trace_kind="mcp",
        risk="write",
        server_name="Notes",
    )


SKILL_SNAPSHOT = {
    "skillId": 41,
    "skillSlug": "research",
    "skillVersion": "1.2.3",
    "skillContentHash": "a" * 64,
}


class FakeSkillRuntime:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.active = False
        self.activation_calls = 0
        self.restore_calls = 0
        self.resource_calls: list[dict] = []

    def _register_resource(self) -> None:
        self.registry.register(
            name="read_skill_resource",
            description="Read an active Skill resource.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda arguments: (
                self.resource_calls.append(arguments)
                or ToolHandlerResult(
                    output={"content": "restored reference"},
                    skill_snapshot=dict(SKILL_SNAPSHOT),
                )
            ),
            read_only=True,
            engine_names={"current", "langgraph"},
            trace_kind="skill",
            internal=True,
        )

    def register_activation(self) -> None:
        def activate(arguments):
            assert arguments == {"skill": "research"}
            self.activation_calls += 1
            self.active = True
            self._register_resource()
            return ToolHandlerResult(
                output={
                    "activated": True,
                    "instructions": "Use the restored Skill resource.",
                },
                skill_snapshot=dict(SKILL_SNAPSHOT),
            )

        self.registry.register(
            name="activate_skill",
            description="Activate a Skill.",
            input_schema={
                "type": "object",
                "properties": {"skill": {"type": "string"}},
                "required": ["skill"],
                "additionalProperties": False,
            },
            handler=activate,
            read_only=True,
            engine_names={"current", "langgraph"},
            trace_kind="skill",
            internal=True,
            becomes_parent_on_success=True,
            remove_after_success=True,
        )

    def restore(self, snapshot: dict) -> None:
        assert snapshot == SKILL_SNAPSHOT
        self.restore_calls += 1
        self.active = True
        self._register_resource()
        self.registry.unregister("activate_skill")


def main() -> None:
    registry = ToolRegistry()
    search_calls: list[dict] = []
    unsafe_calls: list[dict] = []
    register_tools(registry, search_calls, unsafe_calls)

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
                ToolRegistry(),
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
            ToolRegistry(),
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
            ToolRegistry(),
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
            thread_id = LangGraphCheckpointStore.thread_id(
                17, "run_resume"
            )
            saved = saver.get_tuple(
                {"configurable": {"thread_id": thread_id}}
            )
            assert saved is not None
            assert saved.config["configurable"]["thread_id"] == thread_id
            assert saved.checkpoint["channel_values"]["schema_version"] == 1
            assert saved.checkpoint["channel_values"]["answer"] == "recovered"

        try:
            LangGraphAgentEngine(
                gateway=FakeGateway(),
                checkpoint_db_path=checkpoint_path,
            ).run(
                user_id=18,
                run_id="run_resume",
                messages=[],
                config=config,
                registry=registry,
                resume_from_checkpoint=True,
            )
            raise AssertionError("another user must not share checkpoints")
        except LangGraphCheckpointError as exc:
            assert exc.code == "langgraph_checkpoint_not_found"

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
            "memory_recall",
            "model",
            "tools",
            "__end__",
        ]

        recalled_items = [
            {
                "id": "memory-1",
                "memory": "用户偏好先给结论。",
                "score": 0.9,
            }
        ]
        recall_calls = []
        memory_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": "Used memory safely.",
                "tool_calls": [],
            },
            {
                "role": "assistant",
                "content": "Reused memory safely.",
                "tool_calls": [],
            },
            {
                "role": "assistant",
                "content": "Memory disabled.",
                "tool_calls": [],
            },
        )
        memory_trace = AgentTraceRecorder(run_id="run_memory")
        memory_result = run_engine(
            LangGraphAgentEngine(
                gateway=memory_gateway,
                checkpoint_db_path=root / "memory.sqlite3",
            ),
            ToolRegistry(),
            run_id="run_memory",
            messages=[
                {"role": "system", "content": "System rules."},
                {"role": "user", "content": "How should you answer?"},
            ],
            trace=memory_trace,
            memory_recall=lambda: (
                recall_calls.append("called") or recalled_items
            ),
        )
        assert recall_calls == ["called"]
        assert memory_result.memory_recalled is True
        assert memory_result.memories == recalled_items
        assert "<user_memories>" in (
            memory_gateway.calls[0]["messages"][0]["content"]
        )
        assert "用户偏好先给结论" in (
            memory_gateway.calls[0]["messages"][0]["content"]
        )
        assert [step["name"] for step in memory_trace.snapshot()] == [
            "memory_recall",
            "model_completion",
        ]
        reused_memory_result = run_engine(
            LangGraphAgentEngine(
                gateway=memory_gateway,
                checkpoint_db_path=root / "memory.sqlite3",
            ),
            ToolRegistry(),
            run_id="run_memory",
            messages=[
                {"role": "system", "content": "System rules."},
                {"role": "user", "content": "Run the next plan step"},
            ],
            memory_recall=lambda: recall_calls.append("unexpected"),
        )
        assert reused_memory_result.answer == "Reused memory safely."
        assert reused_memory_result.memories == recalled_items
        assert recall_calls == ["called"]
        assert "用户偏好先给结论" in (
            memory_gateway.calls[1]["messages"][0]["content"]
        )
        disabled_memory_result = run_engine(
            LangGraphAgentEngine(
                gateway=memory_gateway,
                checkpoint_db_path=root / "memory.sqlite3",
            ),
            ToolRegistry(),
            run_id="run_memory",
            messages=[
                {"role": "system", "content": "System rules."},
                {"role": "user", "content": "Do not use memory"},
            ],
            memory_enabled=False,
        )
        assert disabled_memory_result.answer == "Memory disabled."
        assert disabled_memory_result.memories == []
        assert "<user_memories>" not in (
            memory_gateway.calls[2]["messages"][0]["content"]
        )

        degraded_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": "Answered without memory.",
                "tool_calls": [],
            }
        )
        degraded_trace = AgentTraceRecorder(run_id="run_memory_degraded")
        degraded_result = run_engine(
            LangGraphAgentEngine(
                gateway=degraded_gateway,
                checkpoint_db_path=root / "memory-degraded.sqlite3",
            ),
            ToolRegistry(),
            run_id="run_memory_degraded",
            messages=[{"role": "user", "content": "Continue anyway"}],
            trace=degraded_trace,
            memory_recall=lambda: (_ for _ in ()).throw(
                RuntimeError("memory upstream failed")
            ),
        )
        assert degraded_result.answer == "Answered without memory."
        assert degraded_result.memories == []
        assert degraded_result.memory_recalled is True
        degraded_memory_step = degraded_trace.snapshot()[0]
        assert degraded_memory_step["status"] == "failed"
        assert degraded_memory_step["errorCode"] == "memory_recall_failed"

        checkpoint_recall_calls = []
        checkpoint_memory_gateway = FakeGateway(
            RuntimeError("model interrupted after recall"),
            {
                "role": "assistant",
                "content": "Recovered with checkpointed memory.",
                "tool_calls": [],
            },
        )
        checkpoint_memory_path = root / "memory-resume.sqlite3"
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=checkpoint_memory_gateway,
                    checkpoint_db_path=checkpoint_memory_path,
                ),
                ToolRegistry(),
                run_id="run_memory_resume",
                messages=[
                    {"role": "system", "content": "System rules."},
                    {"role": "user", "content": "Resume safely"},
                ],
                memory_recall=lambda: (
                    checkpoint_recall_calls.append("called")
                    or recalled_items
                ),
            )
            raise AssertionError("the model interruption must surface")
        except RuntimeError as exc:
            assert str(exc) == "model interrupted after recall"
        resumed_memory_result = run_engine(
            LangGraphAgentEngine(
                gateway=checkpoint_memory_gateway,
                checkpoint_db_path=checkpoint_memory_path,
            ),
            ToolRegistry(),
            run_id="run_memory_resume",
            resume=True,
            memory_recall=lambda: checkpoint_recall_calls.append(
                "unexpected"
            ),
        )
        assert resumed_memory_result.answer == (
            "Recovered with checkpointed memory."
        )
        assert resumed_memory_result.memories == recalled_items
        assert checkpoint_recall_calls == ["called"]

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

        web_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "web_search",
                        '{"query":"latest docs","top_k":2}',
                        "call_search_1",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "Search complete.",
                "tool_calls": [],
            },
        )
        web_trace = AgentTraceRecorder(run_id="run_web")
        execution_events = []
        web_result = run_engine(
            LangGraphAgentEngine(
                gateway=web_gateway,
                checkpoint_db_path=root / "web.sqlite3",
            ),
            registry,
            run_id="run_web",
            messages=[{"role": "user", "content": "Search"}],
            trace=web_trace,
            execution_callback=lambda execution, step_id: (
                execution_events.append((execution, step_id))
            ),
        )
        assert web_result.answer == "Search complete."
        assert len(web_result.executions) == 1
        assert web_result.executions[0].tool_name == "web_search"
        assert search_calls == [{"query": "latest docs", "top_k": 2}]
        assert len(execution_events) == 1
        assert execution_events[0][0].tool_name == "web_search"
        assert [step["kind"] for step in web_trace.snapshot()] == [
            "model",
            "tool",
            "model",
        ]
        exposed = web_gateway.calls[0]["tools"]
        assert [item["function"]["name"] for item in exposed] == [
            "web_search"
        ]
        assert web_gateway.calls[0]["tool_choice"] == "auto"
        second_messages = web_gateway.calls[1]["messages"]
        assert second_messages[-2]["role"] == "assistant"
        assert second_messages[-1]["role"] == "tool"
        assert second_messages[-1]["name"] == "web_search"

        mcp_calls: list[dict] = []
        mcp_registry = ToolRegistry()
        register_read_only_mcp(mcp_registry, mcp_calls)
        mcp_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "mcp_notes_search",
                        '{"query":"agent notes"}',
                        "call_mcp_read_1",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "I found the note.",
                "tool_calls": [],
            },
        )
        mcp_trace = AgentTraceRecorder(run_id="run_mcp_read")
        mcp_result = run_engine(
            LangGraphAgentEngine(
                gateway=mcp_gateway,
                checkpoint_db_path=root / "mcp-read.sqlite3",
            ),
            mcp_registry,
            run_id="run_mcp_read",
            messages=[{"role": "user", "content": "Search notes"}],
            trace=mcp_trace,
        )
        assert mcp_result.answer == "I found the note."
        assert mcp_calls == [{"query": "agent notes"}]
        assert mcp_result.executions[0].tool_name == "mcp_notes_search"
        assert [step["kind"] for step in mcp_trace.snapshot()] == [
            "model",
            "mcp",
            "model",
        ]
        assert [
            item["function"]["name"]
            for item in mcp_gateway.calls[0]["tools"]
        ] == ["mcp_notes_search"]

        blocked_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "dangerous_write",
                        '{"value":"must not run"}',
                        "call_unsafe_1",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "I cannot run that tool.",
                "tool_calls": [],
            },
        )
        blocked_result = run_engine(
            LangGraphAgentEngine(
                gateway=blocked_gateway,
                checkpoint_db_path=root / "blocked.sqlite3",
            ),
            registry,
            run_id="run_blocked",
            messages=[{"role": "user", "content": "Write"}],
        )
        assert blocked_result.answer == "I cannot run that tool."
        assert len(blocked_result.executions) == 1
        assert blocked_result.executions[0].status == "failed"
        assert blocked_result.executions[0].error_code == "unknown_tool"
        assert unsafe_calls == []

        shadow_calls: list[dict] = []
        shadow_registry = ToolRegistry()
        shadow_registry.register(
            name="web_search",
            description="An untrusted same-name tool.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=lambda arguments: shadow_calls.append(arguments) or {},
        )
        shadow_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "web_search",
                        '{"query":"must not run"}',
                        "call_shadow_search",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "The search tool is unavailable.",
                "tool_calls": [],
            },
        )
        shadow_result = run_engine(
            LangGraphAgentEngine(
                gateway=shadow_gateway,
                checkpoint_db_path=root / "shadow.sqlite3",
            ),
            shadow_registry,
            run_id="run_shadow",
            messages=[{"role": "user", "content": "Search"}],
        )
        assert shadow_gateway.calls[0]["tools"] is None
        assert shadow_result.executions[0].error_code == "unknown_tool"
        assert shadow_calls == []

        captured_plans: list[dict] = []
        unexpected_plan_calls: list[dict] = []
        plan_registry = ToolRegistry()
        register_task_planner(plan_registry, captured_plans.append)
        plan_registry.register(
            name="should_not_run",
            description="Must not run after a task plan is created.",
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            handler=lambda arguments: (
                unexpected_plan_calls.append(arguments) or {"ran": True}
            ),
            read_only=True,
            engine_names={"current", "langgraph"},
        )
        plan_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "create_task_plan",
                        json.dumps(
                            {
                                "steps": [
                                    {
                                        "title": "Collect sources",
                                        "kind": "tool",
                                        "tool_name": "should_not_run",
                                    },
                                    {
                                        "title": "Write answer",
                                        "kind": "answer",
                                    },
                                ]
                            }
                        ),
                        "call_create_plan",
                    ),
                    tool_call(
                        "should_not_run",
                        '{"value":"same model response"}',
                        "call_after_plan",
                    ),
                ],
            }
        )
        plan_result = run_engine(
            LangGraphAgentEngine(
                gateway=plan_gateway,
                checkpoint_db_path=root / "plan.sqlite3",
            ),
            plan_registry,
            run_id="run_plan_only",
            messages=[{"role": "user", "content": "Plan this task"}],
        )
        assert plan_result.answer == "The task plan was created."
        assert len(plan_gateway.calls) == 1
        assert len(captured_plans) == 1
        assert unexpected_plan_calls == []
        assert [item.tool_name for item in plan_result.executions] == [
            "create_task_plan"
        ]

        limited_calls: list[dict] = []
        limited_registry = ToolRegistry()
        register_tools(limited_registry, limited_calls, [])
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=FakeGateway(
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                tool_call(
                                    "web_search",
                                    '{"query":"loop"}',
                                    "call_loop_1",
                                )
                            ],
                        }
                    ),
                    checkpoint_db_path=root / "limited.sqlite3",
                    max_tool_rounds=0,
                ),
                limited_registry,
                run_id="run_limited",
                messages=[{"role": "user", "content": "Loop"}],
            )
            raise AssertionError("zero tool rounds must stop before execution")
        except AgentLoopLimitError:
            assert limited_calls == []

        resume_calls: list[dict] = []
        resume_registry = ToolRegistry()
        register_tools(resume_registry, resume_calls, [])
        resume_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "web_search",
                        '{"query":"resume safely"}',
                        "call_resume_search",
                    )
                ],
            },
            RuntimeError("second model interrupted"),
            {
                "role": "assistant",
                "content": "Recovered without another search.",
                "tool_calls": [],
            },
        )
        first_execution_events = []
        resume_path = root / "tool-resume.sqlite3"
        try:
            run_engine(
                LangGraphAgentEngine(
                    gateway=resume_gateway,
                    checkpoint_db_path=resume_path,
                ),
                resume_registry,
                run_id="run_tool_resume",
                messages=[{"role": "user", "content": "Search then answer"}],
                execution_callback=lambda execution, step_id: (
                    first_execution_events.append((execution, step_id))
                ),
            )
            raise AssertionError("the second model request must fail")
        except RuntimeError as exc:
            assert str(exc) == "second model interrupted"
        assert len(resume_calls) == 1
        assert len(first_execution_events) == 1

        resumed_execution_events = []
        resumed = run_engine(
            LangGraphAgentEngine(
                gateway=resume_gateway,
                checkpoint_db_path=resume_path,
            ),
            resume_registry,
            run_id="run_tool_resume",
            resume=True,
            execution_callback=lambda execution, step_id: (
                resumed_execution_events.append((execution, step_id))
            ),
        )
        assert resumed.answer == "Recovered without another search."
        assert len(resume_calls) == 1
        assert resumed_execution_events == []
        assert len(resumed.executions) == 1
        assert resumed.executions[0].call_id == "call_resume_search"

        approval_database = Database(
            f"sqlite:///{(root / 'approvals.sqlite3').as_posix()}"
        )
        approval_runs = AgentRunStore(database=approval_database)
        approval_runs.create_run(
            user_id=17,
            session_id="session-langgraph-approval",
            user_message_id=1,
            goal_summary="Create two notes",
            trigger_mode="auto",
            run_id="run_write_approval",
        )
        operation_store = AgentToolOperationStore(
            database=approval_database,
            approval_timeout_seconds=60,
        )
        write_calls: list[dict] = []
        write_registry = ToolRegistry()
        register_write_mcp(write_registry, write_calls)
        write_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "mcp_notes_create",
                        '{"title":"one"}',
                        "call_write_1",
                    ),
                    tool_call(
                        "mcp_notes_create",
                        '{"title":"two"}',
                        "call_write_2",
                    ),
                ],
            },
            {
                "role": "assistant",
                "content": "Both notes were created.",
                "tool_calls": [],
            },
        )
        write_engine = LangGraphAgentEngine(
            gateway=write_gateway,
            checkpoint_db_path=root / "write-approval.sqlite3",
        )
        first_pause = run_engine(
            write_engine,
            write_registry,
            run_id="run_write_approval",
            messages=[{"role": "user", "content": "Create two notes"}],
            tool_operation_store=operation_store,
        )
        assert first_pause.paused is True
        assert first_pause.interrupt["toolCallId"] == "call_write_1"
        assert write_calls == []
        first_operation = operation_store.ensure_waiting(
            user_id=17,
            run_id="run_write_approval",
            tool_call_id="call_write_1",
            tool_name="mcp_notes_create",
            server_name="Notes",
            risk="write",
            input_summary={"title": "one"},
        )
        assert operation_store.resolve(
            17,
            first_operation["approvalId"],
            "allow_once",
        )
        second_pause = run_engine(
            write_engine,
            write_registry,
            run_id="run_write_approval",
            resume=True,
            tool_operation_store=operation_store,
            approval_decision="allow_once",
        )
        assert second_pause.paused is True
        assert second_pause.interrupt["toolCallId"] == "call_write_2"
        assert write_calls == [{"title": "one"}]
        second_operation = operation_store.ensure_waiting(
            user_id=17,
            run_id="run_write_approval",
            tool_call_id="call_write_2",
            tool_name="mcp_notes_create",
            server_name="Notes",
            risk="write",
            input_summary={"title": "two"},
        )
        assert operation_store.resolve(
            17,
            second_operation["approvalId"],
            "allow_once",
        )
        write_result = run_engine(
            write_engine,
            write_registry,
            run_id="run_write_approval",
            resume=True,
            tool_operation_store=operation_store,
            approval_decision="allow_once",
        )
        assert write_result.answer == "Both notes were created."
        assert write_calls == [{"title": "one"}, {"title": "two"}]
        completed_write = run_engine(
            write_engine,
            write_registry,
            run_id="run_write_approval",
            resume=True,
            tool_operation_store=operation_store,
        )
        assert completed_write.answer == "Both notes were created."
        assert write_calls == [{"title": "one"}, {"title": "two"}]

        approval_runs.create_run(
            user_id=17,
            session_id="session-langgraph-deny",
            user_message_id=2,
            goal_summary="Create a denied note",
            trigger_mode="auto",
            run_id="run_write_deny",
        )
        denied_calls: list[dict] = []
        denied_registry = ToolRegistry()
        register_write_mcp(denied_registry, denied_calls)
        denied_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "mcp_notes_create",
                        '{"title":"denied"}',
                        "call_write_denied",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "The note was not created.",
                "tool_calls": [],
            },
        )
        denied_engine = LangGraphAgentEngine(
            gateway=denied_gateway,
            checkpoint_db_path=root / "write-denied.sqlite3",
        )
        denied_pause = run_engine(
            denied_engine,
            denied_registry,
            run_id="run_write_deny",
            messages=[{"role": "user", "content": "Create a note"}],
            tool_operation_store=operation_store,
        )
        denied_operation = operation_store.ensure_waiting(
            user_id=17,
            run_id="run_write_deny",
            tool_call_id=denied_pause.interrupt["toolCallId"],
            tool_name="mcp_notes_create",
            server_name="Notes",
            risk="write",
            input_summary={"title": "denied"},
        )
        assert operation_store.resolve(
            17,
            denied_operation["approvalId"],
            "deny",
        )
        denied_result = run_engine(
            denied_engine,
            denied_registry,
            run_id="run_write_deny",
            resume=True,
            tool_operation_store=operation_store,
            approval_decision="deny",
        )
        assert denied_result.answer == "The note was not created."
        assert denied_result.executions[0].error_code == "permission_denied"
        assert denied_calls == []

        approval_runs.create_run(
            user_id=17,
            session_id="session-langgraph-skill-resume",
            user_message_id=3,
            goal_summary="Activate a Skill, write, and read a resource",
            trigger_mode="auto",
            run_id="run_skill_resume",
        )
        skill_write_calls: list[dict] = []
        first_skill_registry = ToolRegistry()
        register_write_mcp(first_skill_registry, skill_write_calls)
        first_skill_runtime = FakeSkillRuntime(first_skill_registry)
        first_skill_runtime.register_activation()
        skill_gateway = FakeGateway(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "activate_skill",
                        '{"skill":"research"}',
                        "call_skill_activate",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "mcp_notes_create",
                        '{"title":"from skill"}',
                        "call_skill_write",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    tool_call(
                        "read_skill_resource",
                        '{"path":"references/guide.md"}',
                        "call_skill_resource",
                    )
                ],
            },
            {
                "role": "assistant",
                "content": "Skill workflow completed.",
                "tool_calls": [],
            },
        )
        skill_engine = LangGraphAgentEngine(
            gateway=skill_gateway,
            checkpoint_db_path=root / "skill-resume.sqlite3",
        )
        skill_pause = run_engine(
            skill_engine,
            first_skill_registry,
            run_id="run_skill_resume",
            messages=[{"role": "user", "content": "Use the Skill"}],
            tool_operation_store=operation_store,
            skill_restore=first_skill_runtime.restore,
        )
        assert skill_pause.paused is True
        assert skill_pause.interrupt["toolCallId"] == "call_skill_write"
        assert first_skill_runtime.activation_calls == 1
        assert "activate_skill" not in {
            item["function"]["name"]
            for item in skill_gateway.calls[1]["tools"]
        }
        skill_operation = operation_store.ensure_waiting(
            user_id=17,
            run_id="run_skill_resume",
            tool_call_id="call_skill_write",
            tool_name="mcp_notes_create",
            server_name="Notes",
            risk="write",
            input_summary={"title": "from skill"},
        )
        assert operation_store.resolve(
            17,
            skill_operation["approvalId"],
            "allow_once",
        )

        resumed_skill_registry = ToolRegistry()
        register_write_mcp(resumed_skill_registry, skill_write_calls)
        resumed_skill_runtime = FakeSkillRuntime(resumed_skill_registry)
        resumed_skill_runtime.register_activation()
        skill_result = run_engine(
            skill_engine,
            resumed_skill_registry,
            run_id="run_skill_resume",
            resume=True,
            tool_operation_store=operation_store,
            approval_decision="allow_once",
            skill_restore=resumed_skill_runtime.restore,
        )
        assert skill_result.answer == "Skill workflow completed."
        assert resumed_skill_runtime.activation_calls == 0
        assert resumed_skill_runtime.restore_calls >= 1
        assert resumed_skill_runtime.resource_calls == [
            {"path": "references/guide.md"}
        ]
        assert skill_write_calls == [{"title": "from skill"}]
        assert all(
            execution.skill_snapshot == SKILL_SNAPSHOT
            for execution in skill_result.executions
        )
        approval_database.engine.dispose()

    print("langgraph engine checkpoints and runs the web search loop safely")


if __name__ == "__main__":
    main()
