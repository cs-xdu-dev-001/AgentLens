from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from .agent_loop import (
    AgentLoopLimitError,
    AgentRunResult,
    ToolExecution,
    ToolRegistry,
)
from .langgraph_checkpoint import (
    LangGraphCheckpointError,
    LangGraphCheckpointStore,
)
from .agent_trace import sanitize_trace_value
from .memory import append_long_term_memory_context


class LangGraphState(TypedDict):
    schema_version: int
    messages: list[dict[str, Any]]
    answer: str
    executions: list[dict[str, Any]]
    tool_rounds: int
    pending_tool_calls: list[dict[str, Any]]
    tool_call_index: int
    skill_snapshot: dict[str, Any] | None
    memories: list[dict[str, Any]]
    memory_recalled: bool


@dataclass(frozen=True)
class LangGraphRunContext:
    gateway: Any
    config: dict[str, Any] | None
    registry: ToolRegistry
    max_tool_rounds: int
    user_id: int
    run_id: str
    tool_operation_store: Any = None
    trace: Any = None
    parent_step_id: str | None = None
    execution_callback: (
        Callable[[ToolExecution, str | None], None] | None
    ) = None
    model_event_callback: (
        Callable[[dict[str, Any]], None] | None
    ) = None
    skill_restore: Callable[[dict[str, Any]], None] | None = None
    memory_recall: (
        Callable[[], list[dict[str, Any]]] | None
    ) = None


class LangGraphAgentEngine:
    name = "langgraph"

    def __init__(
        self,
        *,
        gateway,
        checkpoint_db_path: Path | None,
        max_tool_rounds: int = 3,
    ):
        self._gateway = gateway
        self._max_tool_rounds = max(0, max_tool_rounds)
        if checkpoint_db_path is None:
            raise LangGraphCheckpointError(
                "langgraph_checkpoint_unavailable",
                "LangGraph checkpoint存储暂不可用。",
            )
        self._checkpoints = LangGraphCheckpointStore(
            checkpoint_db_path
        )
        self._builder = StateGraph(
            LangGraphState,
            context_schema=LangGraphRunContext,
        )
        self._builder.add_node("memory_recall", self._recall_memory)
        self._builder.add_node("model", self._call_model)
        self._builder.add_node("tools", self._call_tools)
        self._builder.add_edge(START, "memory_recall")
        self._builder.add_edge("memory_recall", "model")
        self._builder.add_conditional_edges(
            "model",
            self._route_after_model,
            {"tools": "tools", "end": END},
        )
        self._builder.add_conditional_edges(
            "tools",
            self._route_after_tools,
            {"tools": "tools", "model": "model", "end": END},
        )
        self._graph = self._builder.compile()

    @staticmethod
    def _recall_memory(
        state: LangGraphState,
        runtime: Runtime[LangGraphRunContext],
    ) -> dict[str, Any]:
        if state.get("memory_recalled"):
            return {}
        context = runtime.context
        if context.memory_recall is None:
            return {"memory_recalled": True, "memories": []}
        trace = context.trace
        memory_step = (
            trace.start_step(
                kind="memory",
                name="memory_recall",
                title="Recalling long-term memory",
                parent_id=context.parent_step_id,
            )
            if trace
            else None
        )
        try:
            recalled = context.memory_recall()
            memories = [
                dict(item)
                for item in recalled
                if isinstance(item, dict)
            ]
        except Exception:
            if trace and memory_step:
                trace.finish_step(
                    memory_step,
                    status="failed",
                    title="Long-term memory recall unavailable",
                    output_summary={"recalled": 0, "degraded": True},
                    error_code="memory_recall_failed",
                )
            return {"memory_recalled": True, "memories": []}
        if trace and memory_step:
            trace.finish_step(
                memory_step,
                status="success",
                title="Long-term memory recall completed",
                output_summary={"recalled": len(memories)},
            )
        return {
            "memory_recalled": True,
            "memories": memories,
            "messages": append_long_term_memory_context(
                state["messages"],
                memories,
            ),
        }

    @staticmethod
    def _restore_skill(
        state: LangGraphState,
        context: LangGraphRunContext,
    ) -> dict[str, Any] | None:
        snapshot = state.get("skill_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return None
        normalized = json.loads(json.dumps(snapshot, ensure_ascii=False))
        if context.skill_restore is None:
            raise ValueError("Skill restore callback is unavailable.")
        context.skill_restore(normalized)
        return normalized

    @staticmethod
    def _call_model(
        state: LangGraphState,
        runtime: Runtime[LangGraphRunContext],
    ) -> dict[str, Any]:
        context = runtime.context
        config = context.config or {}
        trace = context.trace
        LangGraphAgentEngine._restore_skill(state, context)
        allowed_names = set(
            context.registry.eligible_names("langgraph")
        )
        schemas = context.registry.schemas(
            allowed_names,
            engine_name="langgraph",
        )
        model_step = (
            trace.start_step(
                kind="model",
                name="model_completion",
                title="Model is analyzing",
                parent_id=context.parent_step_id,
                input_summary={
                    "messageCount": len(state["messages"]),
                    "toolCount": len(schemas),
                },
                details={
                    "modelName": str(config.get("model_name") or ""),
                    "apiMode": str(
                        config.get("api_mode") or "chat_completions"
                    ),
                    "engineName": "langgraph",
                },
            )
            if trace
            else None
        )
        completion_options: dict[str, Any] = {
            "tools": schemas or None,
            "tool_choice": "auto" if schemas else None,
        }
        if context.model_event_callback is not None:
            completion_options["event_callback"] = (
                context.model_event_callback
            )
        try:
            message = context.gateway.complete(
                state["messages"],
                context.config,
                **completion_options,
            )
        except Exception:
            if trace and model_step:
                trace.finish_step(
                    model_step,
                    status="failed",
                    title="Model request failed",
                    error_code="model_request_failed",
                )
            raise

        tool_calls = message.get("tool_calls") or []
        answer = str(message.get("content") or "").strip()
        if trace and model_step:
            trace.finish_step(
                model_step,
                status="success" if tool_calls or answer else "failed",
                title=(
                    "Model selected a tool"
                    if tool_calls
                    else (
                        "Model generated an answer"
                        if answer
                        else "Model response was invalid"
                    )
                ),
                output_summary=(
                    {"toolCallCount": len(tool_calls)}
                    if tool_calls or answer
                    else None
                ),
                error_code=(
                    None
                    if tool_calls or answer
                    else "invalid_model_response"
                ),
            )
        if tool_calls:
            if int(state.get("tool_rounds") or 0) >= (
                context.max_tool_rounds
            ):
                raise AgentLoopLimitError(
                    "Agent exceeded the maximum tool-call rounds."
                )
            assistant_message = {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": json.loads(
                    json.dumps(tool_calls, ensure_ascii=False)
                ),
            }
            if message.get("_response_items"):
                assistant_message["_response_items"] = json.loads(
                    json.dumps(
                        message["_response_items"],
                        ensure_ascii=False,
                    )
                )
            return {
                "messages": [*state["messages"], assistant_message],
                "answer": "",
                "pending_tool_calls": json.loads(
                    json.dumps(tool_calls, ensure_ascii=False)
                ),
                "tool_call_index": 0,
            }
        if not answer:
            raise ValueError("Model returned neither text nor tool calls.")
        return {"answer": answer}

    @staticmethod
    def _route_after_model(state: LangGraphState) -> str:
        if str(state.get("answer") or "").strip():
            return "end"
        messages = state.get("messages") or []
        if messages and (messages[-1].get("tool_calls") or []):
            return "tools"
        raise ValueError("LangGraph model state cannot be routed.")

    @staticmethod
    def _route_after_tools(state: LangGraphState) -> str:
        if str(state.get("answer") or "").strip():
            return "end"
        calls = state.get("pending_tool_calls") or []
        index = int(state.get("tool_call_index") or 0)
        return "tools" if index < len(calls) else "model"

    @staticmethod
    def _call_tools(
        state: LangGraphState,
        runtime: Runtime[LangGraphRunContext],
    ) -> dict[str, Any]:
        context = runtime.context
        trace = context.trace
        messages = [dict(message) for message in state["messages"]]
        calls = list(state.get("pending_tool_calls") or [])
        if not calls:
            assistant = next(
                (
                    message
                    for message in reversed(messages)
                    if message.get("role") == "assistant"
                    and message.get("tool_calls")
                ),
                None,
            )
            calls = list((assistant or {}).get("tool_calls") or [])
        call_index = int(state.get("tool_call_index") or 0)
        if call_index >= len(calls):
            raise ValueError("LangGraph tool state cannot be routed.")
        executions = list(state.get("executions") or [])
        current_skill_snapshot = LangGraphAgentEngine._restore_skill(
            state,
            context,
        )
        allowed_names = set(
            context.registry.eligible_names("langgraph")
        )
        prepared = context.registry.prepare(
            calls[call_index],
            allowed_names=allowed_names,
            engine_name="langgraph",
        )
        definition = prepared.definition
        execution = prepared.error
        if execution is None and definition is not None and not definition.read_only:
            decision_value = interrupt(
                {
                    "type": "tool_approval",
                    "toolCallId": prepared.call_id,
                    "toolName": prepared.tool_name,
                    "serverName": definition.server_name or "MCP",
                    "risk": definition.risk,
                    "inputSummary": sanitize_trace_value(
                        prepared.arguments
                    ),
                }
            )
            decision = (
                str(decision_value.get("decision") or "")
                if isinstance(decision_value, dict)
                else str(decision_value or "")
            )
            if decision != "allow_once":
                execution = context.registry._failure(
                    prepared.call_id,
                    prepared.tool_name,
                    prepared.arguments,
                    "permission_denied",
                    "Tool execution was denied.",
                    time.perf_counter(),
                )
            else:
                store = context.tool_operation_store
                operation = (
                    store.get_for_call(
                        context.user_id,
                        context.run_id,
                        prepared.call_id,
                    )
                    if store is not None
                    else None
                )
                if operation and operation["status"] in {
                    "succeeded",
                    "failed",
                } and isinstance(operation.get("execution"), dict):
                    execution = LangGraphAgentEngine._execution_from_state(
                        operation["execution"]
                    )
                elif operation and operation["status"] == "approved":
                    claimed = store.claim_execution(
                        context.user_id,
                        operation["approvalId"],
                    )
                    if claimed is not None:
                        execution = context.registry.invoke(prepared)
                        store.finish_execution(
                            context.user_id,
                            operation["approvalId"],
                            LangGraphAgentEngine._execution_to_state(
                                execution
                            ),
                        )
                if execution is None:
                    execution = context.registry._failure(
                        prepared.call_id,
                        prepared.tool_name,
                        prepared.arguments,
                        "tool_execution_indeterminate",
                        "The write tool state is indeterminate and was not repeated.",
                        time.perf_counter(),
                    )
        if execution is None:
            execution = context.registry.invoke(prepared)
        activation_succeeded = bool(
            execution.status == "success"
            and definition is not None
            and definition.becomes_parent_on_success
            and execution.skill_snapshot
        )
        if activation_succeeded:
            current_skill_snapshot = dict(execution.skill_snapshot or {})
        elif current_skill_snapshot:
            execution.skill_snapshot = dict(current_skill_snapshot)
        tool_step = (
            trace.start_step(
                kind=(
                    definition.trace_kind
                    if definition is not None
                    else "tool"
                ),
                name=prepared.tool_name,
                title=f"Running {prepared.tool_name}",
                parent_id=context.parent_step_id,
                input_summary=(
                    None
                    if definition is not None and definition.internal
                    else prepared.arguments
                ),
            )
            if trace
            else None
        )
        if trace and tool_step:
            trace.finish_step(
                tool_step,
                status=(
                    "success" if execution.status == "success" else "failed"
                ),
                title=(
                    f"{prepared.tool_name} completed"
                    if execution.status == "success"
                    else f"{prepared.tool_name} failed"
                ),
                output_summary=(
                    execution.public_output()
                    if execution.status == "success"
                    else execution.error_message
                ),
                error_code=(
                    None
                    if execution.status == "success"
                    else execution.error_code
                ),
            )
        if context.execution_callback is not None:
            context.execution_callback(execution, tool_step)
        if (
            execution.status == "success"
            and definition is not None
            and definition.remove_after_success
        ):
            context.registry.unregister(definition.name)
        ends_run = bool(
            execution.status == "success"
            and definition is not None
            and definition.ends_run_on_success
        )
        executions.append(LangGraphAgentEngine._execution_to_state(execution))
        messages.append(
            {
                "role": "tool",
                "tool_call_id": execution.call_id,
                "name": execution.tool_name,
                "content": execution.model_content(),
            }
        )
        return {
            "messages": messages,
            "executions": executions,
            "tool_rounds": (
                int(state.get("tool_rounds") or 0) + 1
                if call_index + 1 >= len(calls)
                else int(state.get("tool_rounds") or 0)
            ),
            "pending_tool_calls": calls,
            "tool_call_index": call_index + 1,
            "skill_snapshot": current_skill_snapshot,
            "answer": (
                "The task plan was created."
                if ends_run
                else str(state.get("answer") or "")
            ),
        }

    @staticmethod
    def _execution_to_state(
        execution: ToolExecution,
    ) -> dict[str, Any]:
        return {
            "call_id": execution.call_id,
            "tool_name": execution.tool_name,
            "arguments": execution.arguments,
            "output": execution.output,
            "status": execution.status,
            "error_code": execution.error_code,
            "error_message": execution.error_message,
            "latency_ms": execution.latency_ms,
            "audit_output": execution.audit_output,
            "skill_snapshot": execution.skill_snapshot,
        }

    @staticmethod
    def _execution_from_state(value: dict[str, Any]) -> ToolExecution:
        arguments = value.get("arguments")
        output = value.get("output")
        audit_output = value.get("audit_output")
        skill_snapshot = value.get("skill_snapshot")
        return ToolExecution(
            call_id=str(value.get("call_id") or ""),
            tool_name=str(value.get("tool_name") or "unknown"),
            arguments=arguments if isinstance(arguments, dict) else {},
            output=output if isinstance(output, dict) else {},
            status=str(value.get("status") or "failed"),
            error_code=(
                str(value["error_code"])
                if value.get("error_code") is not None
                else None
            ),
            error_message=(
                str(value["error_message"])
                if value.get("error_message") is not None
                else None
            ),
            latency_ms=int(value.get("latency_ms") or 0),
            audit_output=(
                audit_output if isinstance(audit_output, dict) else None
            ),
            skill_snapshot=(
                skill_snapshot
                if isinstance(skill_snapshot, dict)
                else None
            ),
        )

    def run(
        self,
        *,
        user_id: int,
        run_id: str,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        approval_gate=None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback=None,
        model_event_callback=None,
        resume_from_checkpoint: bool = False,
        tool_operation_store=None,
        approval_decision: str | None = None,
        skill_restore: Callable[[dict[str, Any]], None] | None = None,
        memory_recall: (
            Callable[[], list[dict[str, Any]]] | None
        ) = None,
        memory_enabled: bool = False,
    ) -> AgentRunResult:
        del approval_gate
        if int(user_id) <= 0:
            raise ValueError("A valid user_id is required.")
        thread_id = self._checkpoints.thread_id(user_id, run_id)

        graph_config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": max(4, self._max_tool_rounds * 2 + 4),
        }
        context = LangGraphRunContext(
            gateway=self._gateway,
            config=config,
            registry=registry,
            max_tool_rounds=self._max_tool_rounds,
            user_id=user_id,
            run_id=run_id,
            tool_operation_store=tool_operation_store,
            trace=trace,
            parent_step_id=parent_step_id,
            execution_callback=execution_callback,
            model_event_callback=model_event_callback,
            skill_restore=skill_restore,
            memory_recall=memory_recall,
        )
        with self._checkpoints.open(
            create=not resume_from_checkpoint
        ) as saver:
            if saver is None:
                raise self._checkpoint_not_found()
            graph = self._builder.compile(checkpointer=saver)
            if resume_from_checkpoint:
                snapshot = graph.get_state(graph_config)
                values = snapshot.values or {}
                if values.get("schema_version") != 1:
                    raise self._checkpoint_not_found()
                if snapshot.next:
                    output = graph.invoke(
                        (
                            Command(resume=approval_decision)
                            if approval_decision is not None
                            else None
                        ),
                        graph_config,
                        context=context,
                    )
                else:
                    output = values
            else:
                previous_snapshot = graph.get_state(graph_config)
                previous_values = previous_snapshot.values or {}
                reused_memory = bool(
                    memory_enabled
                    and previous_values.get("schema_version") == 1
                    and previous_values.get("memory_recalled")
                )
                reused_memories = [
                    dict(item)
                    for item in (previous_values.get("memories") or [])
                    if isinstance(item, dict)
                ] if reused_memory else []
                initial_messages = [
                    dict(message) for message in messages
                ]
                if reused_memory:
                    initial_messages = append_long_term_memory_context(
                        initial_messages,
                        reused_memories,
                    )
                output = graph.invoke(
                    {
                        "schema_version": 1,
                        "messages": initial_messages,
                        "answer": "",
                        "executions": [],
                        "tool_rounds": 0,
                        "pending_tool_calls": [],
                        "tool_call_index": 0,
                        "skill_snapshot": (
                            dict(skill_snapshot)
                            if skill_snapshot
                            else None
                        ),
                        "memories": reused_memories,
                        "memory_recalled": (
                            reused_memory or not memory_enabled
                        ),
                    },
                    graph_config,
                    context=context,
                )
        interrupts = output.get("__interrupt__") or []
        interrupt_value = (
            getattr(interrupts[0], "value", None)
            if interrupts
            else None
        )
        return AgentRunResult(
            answer=str(output.get("answer") or ""),
            executions=[
                self._execution_from_state(value)
                for value in (output.get("executions") or [])
                if isinstance(value, dict)
            ],
            trace=trace.snapshot() if trace else [],
            paused=bool(interrupts),
            interrupt=(
                dict(interrupt_value)
                if isinstance(interrupt_value, dict)
                else None
            ),
            memories=[
                dict(item)
                for item in (output.get("memories") or [])
                if isinstance(item, dict)
            ],
            memory_recalled=bool(output.get("memory_recalled")),
        )

    @staticmethod
    def _checkpoint_not_found() -> LangGraphCheckpointError:
        return LangGraphCheckpointError(
            "langgraph_checkpoint_not_found",
            "LangGraph checkpoint不存在，无法继续任务。",
        )
