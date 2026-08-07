from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt

from .agent_loop import (
    AgentLoopLimitError,
    AgentRunResult,
    PreparedToolCall,
    ToolDefinition,
    ToolExecution,
    ToolRegistry,
)
from .langgraph_checkpoint import (
    LangGraphCheckpointError,
    LangGraphCheckpointStore,
)
from .agent_trace import sanitize_trace_value
from .memory import append_long_term_memory_context
from .model_context_window import prepare_model_context


LANGGRAPH_STATE_SCHEMA_VERSION = 2
SUPPORTED_LANGGRAPH_STATE_SCHEMA_VERSIONS = frozenset({1, 2})


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
    retrieval_chunks: list[dict[str, Any]]
    retrieval_quality: dict[str, Any]
    retrieval_run: dict[str, Any] | None
    retrieval_completed: bool


@dataclass(frozen=True)
class LangGraphRunContext:
    gateway: Any
    config: dict[str, Any] | None
    registry: ToolRegistry
    max_tool_rounds: int
    user_id: int
    run_id: str
    max_tool_concurrency: int
    max_context_tokens: int
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
    retrieval_context: Callable[[], dict[str, Any]] | None = None


class LangGraphAgentEngine:
    name = "langgraph"

    def __init__(
        self,
        *,
        gateway,
        checkpoint_db_path: Path | None,
        max_tool_rounds: int = 3,
        max_tool_concurrency: int = 4,
        max_context_tokens: int = 96_000,
    ):
        self._gateway = gateway
        self._max_tool_rounds = max(0, max_tool_rounds)
        self._max_tool_concurrency = max(1, int(max_tool_concurrency))
        self._max_context_tokens = max(1_000, int(max_context_tokens))
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
        self._builder.add_node(
            "retrieval_context",
            self._retrieve_context,
        )
        self._builder.add_node("model", self._call_model)
        self._builder.add_node("tools", self._call_tools)
        self._builder.add_edge(START, "retrieval_context")
        self._builder.add_edge("retrieval_context", "memory_recall")
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
    def _append_retrieval_context(
        messages: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not chunks:
            return messages
        context = "\n\n".join(
            f"[Reference {idx}] File: {chunk.get('filename', '')}\n"
            f"Content: {chunk.get('chunk_text', '')}"
            for idx, chunk in enumerate(chunks, start=1)
        )
        updated = [dict(message) for message in messages]
        marker = "References:\nNo relevant references"
        for message in updated:
            if message.get("role") != "user":
                continue
            content = str(message.get("content") or "")
            if marker in content:
                message["content"] = content.replace(
                    marker,
                    f"References:\n{context}",
                    1,
                )
        return updated

    @staticmethod
    def _retrieve_context(
        state: LangGraphState,
        runtime: Runtime[LangGraphRunContext],
    ) -> dict[str, Any]:
        if state.get("retrieval_completed"):
            return {}
        context = runtime.context
        if context.retrieval_context is None:
            return {
                "retrieval_completed": True,
                "retrieval_chunks": [],
                "retrieval_quality": {"enabled": False},
                "retrieval_run": None,
            }
        trace = context.trace
        retrieval_step = (
            trace.start_step(
                kind="system",
                name="retrieval_context",
                title="Retrieving knowledge context",
                parent_id=context.parent_step_id,
            )
            if trace
            else None
        )
        try:
            payload = context.retrieval_context() or {}
            chunks = [
                dict(item)
                for item in (payload.get("chunks") or [])
                if isinstance(item, dict)
            ]
            quality = (
                dict(payload.get("quality"))
                if isinstance(payload.get("quality"), dict)
                else {"enabled": True}
            )
            retrieval_run = (
                dict(payload.get("retrievalRun"))
                if isinstance(payload.get("retrievalRun"), dict)
                else None
            )
            messages = LangGraphAgentEngine._append_retrieval_context(
                state["messages"],
                chunks,
            )
        except Exception:
            if trace and retrieval_step:
                trace.finish_step(
                    retrieval_step,
                    status="failed",
                    title="Knowledge retrieval unavailable",
                    output_summary={"hitCount": 0, "degraded": True},
                    error_code="retrieval_failed",
                )
            return {
                "retrieval_completed": True,
                "retrieval_chunks": [],
                "retrieval_quality": {
                    "enabled": True,
                    "qualityLevel": "unavailable",
                    "hitCount": 0,
                    "reason": "Knowledge-base retrieval is unavailable.",
                },
                "retrieval_run": None,
            }
        retrieval_degraded = quality.get("qualityLevel") == "unavailable"
        if trace and retrieval_step:
            trace.finish_step(
                retrieval_step,
                status="failed" if retrieval_degraded else "success",
                title=(
                    "Knowledge retrieval unavailable"
                    if retrieval_degraded
                    else "Knowledge context retrieved"
                ),
                output_summary={
                    "hitCount": len(chunks),
                    "qualityLevel": quality.get("qualityLevel"),
                    "degraded": retrieval_degraded,
                },
                error_code=(
                    "retrieval_failed" if retrieval_degraded else None
                ),
            )
        return {
            "retrieval_completed": True,
            "retrieval_chunks": chunks,
            "retrieval_quality": quality,
            "retrieval_run": retrieval_run,
            "messages": messages,
        }

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
        model_context = prepare_model_context(
            state["messages"],
            max_tokens=context.max_context_tokens,
        )
        model_step = (
            trace.start_step(
                kind="model",
                name="model_completion",
                title="Model is analyzing",
                parent_id=context.parent_step_id,
                input_summary={
                    "messageCount": len(state["messages"]),
                    "modelMessageCount": len(model_context.messages),
                    "estimatedTokenCount": model_context.sent_tokens,
                    "contextTrimmed": model_context.trimmed,
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
                model_context.messages,
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
    def _concurrent_tool_batch(
        context: LangGraphRunContext,
        calls: list[dict[str, Any]],
        start_index: int,
        first: PreparedToolCall,
        allowed_names: set[str],
    ) -> list[PreparedToolCall]:
        definition = first.definition
        if (
            first.error is not None
            or definition is None
            or not definition.can_run_concurrently(first.arguments)
        ):
            return [first]
        prepared_batch = [first]
        for tool_call in calls[start_index + 1 :]:
            candidate = context.registry.prepare(
                tool_call,
                allowed_names=allowed_names,
                engine_name="langgraph",
            )
            candidate_definition = candidate.definition
            if (
                candidate.error is not None
                or candidate_definition is None
                or not candidate_definition.can_run_concurrently(
                    candidate.arguments
                )
            ):
                break
            prepared_batch.append(candidate)
            if len(prepared_batch) >= context.max_tool_concurrency:
                break
        return prepared_batch

    @staticmethod
    def _record_tool_execution(
        context: LangGraphRunContext,
        definition: ToolDefinition | None,
        prepared: PreparedToolCall,
        execution: ToolExecution,
        current_skill_snapshot: dict[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, bool]:
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
        trace = context.trace
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
                details={
                    "readOnly": bool(definition and definition.read_only),
                    "destructive": bool(
                        definition and definition.destructive
                    ),
                    "concurrencySafe": bool(
                        definition
                        and definition.can_run_concurrently(
                            prepared.arguments
                        )
                    ),
                },
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
        return current_skill_snapshot, ends_run

    @staticmethod
    def _tool_state_update(
        state: LangGraphState,
        *,
        messages: list[dict[str, Any]],
        executions: list[dict[str, Any]],
        calls: list[dict[str, Any]],
        next_index: int,
        skill_snapshot: dict[str, Any] | None,
        ends_run: bool,
    ) -> dict[str, Any]:
        return {
            "messages": messages,
            "executions": executions,
            "tool_rounds": (
                int(state.get("tool_rounds") or 0) + 1
                if next_index >= len(calls)
                else int(state.get("tool_rounds") or 0)
            ),
            "pending_tool_calls": calls,
            "tool_call_index": next_index,
            "skill_snapshot": skill_snapshot,
            "answer": (
                "The task plan was created."
                if ends_run
                else str(state.get("answer") or "")
            ),
        }

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
        concurrent_batch = LangGraphAgentEngine._concurrent_tool_batch(
            context,
            calls,
            call_index,
            prepared,
            allowed_names,
        )
        if len(concurrent_batch) > 1:
            with ThreadPoolExecutor(
                max_workers=min(
                    context.max_tool_concurrency,
                    len(concurrent_batch),
                ),
                thread_name_prefix="knowflow-agent-tool",
            ) as executor:
                batch_executions = list(
                    executor.map(
                        context.registry.invoke,
                        concurrent_batch,
                    )
                )
            ends_run = False
            for batch_prepared, batch_execution in zip(
                concurrent_batch,
                batch_executions,
                strict=True,
            ):
                current_skill_snapshot, batch_ends_run = (
                    LangGraphAgentEngine._record_tool_execution(
                        context,
                        batch_prepared.definition,
                        batch_prepared,
                        batch_execution,
                        current_skill_snapshot,
                    )
                )
                ends_run = ends_run or batch_ends_run
                executions.append(
                    LangGraphAgentEngine._execution_to_state(
                        batch_execution
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": batch_execution.call_id,
                        "name": batch_execution.tool_name,
                        "content": batch_execution.model_content(),
                    }
                )
            return LangGraphAgentEngine._tool_state_update(
                state,
                messages=messages,
                executions=executions,
                calls=calls,
                next_index=call_index + len(concurrent_batch),
                skill_snapshot=current_skill_snapshot,
                ends_run=ends_run,
            )
        definition = prepared.definition
        execution = prepared.error
        if (
            execution is None
            and definition is not None
            and definition.requires_approval
        ):
            decision_value = interrupt(
                {
                    "type": "tool_approval",
                    "toolCallId": prepared.call_id,
                    "toolName": prepared.tool_name,
                    "serverName": definition.server_name or "MCP",
                    "risk": definition.risk,
                    "readOnly": definition.read_only,
                    "destructive": definition.destructive,
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
                timed_out = decision == "timeout"
                execution = context.registry._failure(
                    prepared.call_id,
                    prepared.tool_name,
                    prepared.arguments,
                    (
                        "approval_timeout"
                        if timed_out
                        else "permission_denied"
                    ),
                    (
                        "Tool approval timed out."
                        if timed_out
                        else "Tool execution was denied."
                    ),
                    time.perf_counter(),
                )
            else:
                store = context.tool_operation_store
                if store is None:
                    execution = context.registry.invoke(prepared)
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
        current_skill_snapshot, ends_run = (
            LangGraphAgentEngine._record_tool_execution(
                context,
                definition,
                prepared,
                execution,
                current_skill_snapshot,
            )
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
        return LangGraphAgentEngine._tool_state_update(
            state,
            messages=messages,
            executions=executions,
            calls=calls,
            next_index=call_index + 1,
            skill_snapshot=current_skill_snapshot,
            ends_run=ends_run,
        )

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
        retrieval_context: Callable[[], dict[str, Any]] | None = None,
    ) -> AgentRunResult:
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
            max_tool_concurrency=self._max_tool_concurrency,
            max_context_tokens=self._max_context_tokens,
            tool_operation_store=tool_operation_store,
            trace=trace,
            parent_step_id=parent_step_id,
            execution_callback=execution_callback,
            model_event_callback=model_event_callback,
            skill_restore=skill_restore,
            memory_recall=memory_recall,
            retrieval_context=retrieval_context,
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
                if values.get("schema_version") not in (
                    SUPPORTED_LANGGRAPH_STATE_SCHEMA_VERSIONS
                ):
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
                    and previous_values.get("schema_version")
                    in SUPPORTED_LANGGRAPH_STATE_SCHEMA_VERSIONS
                    and previous_values.get("memory_recalled")
                )
                reused_memories = [
                    dict(item)
                    for item in (previous_values.get("memories") or [])
                    if isinstance(item, dict)
                ] if reused_memory else []
                previous_retrieval_quality = previous_values.get(
                    "retrieval_quality"
                )
                retrieval_was_unavailable = (
                    isinstance(previous_retrieval_quality, dict)
                    and previous_retrieval_quality.get("qualityLevel")
                    == "unavailable"
                )
                reused_retrieval = bool(
                    previous_values.get("schema_version")
                    in SUPPORTED_LANGGRAPH_STATE_SCHEMA_VERSIONS
                    and previous_values.get("retrieval_completed")
                    and not retrieval_was_unavailable
                )
                reused_retrieval_chunks = [
                    dict(item)
                    for item in (
                        previous_values.get("retrieval_chunks") or []
                    )
                    if isinstance(item, dict)
                ] if reused_retrieval else []
                reused_retrieval_quality = (
                    dict(previous_values.get("retrieval_quality") or {})
                    if reused_retrieval
                    else {"enabled": False}
                )
                reused_retrieval_run = (
                    dict(previous_values.get("retrieval_run"))
                    if reused_retrieval
                    and isinstance(
                        previous_values.get("retrieval_run"),
                        dict,
                    )
                    else None
                )
                initial_messages = [
                    dict(message) for message in messages
                ]
                if reused_memory:
                    initial_messages = append_long_term_memory_context(
                        initial_messages,
                        reused_memories,
                    )
                if reused_retrieval:
                    initial_messages = (
                        self._append_retrieval_context(
                            initial_messages,
                            reused_retrieval_chunks,
                        )
                    )
                output = graph.invoke(
                    {
                        "schema_version": LANGGRAPH_STATE_SCHEMA_VERSION,
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
                        "retrieval_chunks": reused_retrieval_chunks,
                        "retrieval_quality": reused_retrieval_quality,
                        "retrieval_run": reused_retrieval_run,
                        "retrieval_completed": (
                            reused_retrieval
                            or retrieval_context is None
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
            retrieval_chunks=[
                dict(item)
                for item in (output.get("retrieval_chunks") or [])
                if isinstance(item, dict)
            ],
            retrieval_quality=(
                dict(output.get("retrieval_quality") or {})
                if isinstance(output.get("retrieval_quality"), dict)
                else None
            ),
            retrieval_run=(
                dict(output.get("retrieval_run"))
                if isinstance(output.get("retrieval_run"), dict)
                else None
            ),
            retrieval_completed=bool(
                output.get("retrieval_completed")
            ),
        )

    @staticmethod
    def _checkpoint_not_found() -> LangGraphCheckpointError:
        return LangGraphCheckpointError(
            "langgraph_checkpoint_not_found",
            "LangGraph checkpoint不存在，无法继续任务。",
        )
