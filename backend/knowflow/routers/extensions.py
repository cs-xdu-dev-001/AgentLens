import json
from collections.abc import Callable, Iterable
from queue import Queue
from threading import Event
from typing import Any
import uuid

from fastapi import APIRouter

from ..runtime import *
from ..services.agent_engine import build_agent_engine
from ..services.langgraph_checkpoint import LangGraphCheckpointError
from ..services.agent_loop import ToolRegistry
from ..services.agent_failure import classify_agent_failure
from ..services.agent_trace import (
    AgentTraceRecorder,
    sanitize_trace_value,
)
from ..services.approval import AgentApprovalGate
from ..services.skill_runtime import (
    SkillActivationSession,
    SkillRuntimeError,
)
from ..services.mcp_client import (
    McpClientError,
    McpRunSessionPool,
)
from ..services.web_search import TavilyWebSearch, WebSearchArguments
from ..services.task_planner import (
    parse_execution_mode,
    register_task_planner,
)

router = APIRouter()

EXTENSION_TAGS = ["Extensions"]


class McpToolConfigurationError(RuntimeError):
    code = "mcp_tool_configuration_invalid"


class AgentRunCancelled(RuntimeError):
    code = "agent_run_cancelled"


class TaskPlanCreated(RuntimeError):
    pass


class AgentStepExecutionError(RuntimeError):
    def __init__(self, failure: dict[str, Any]):
        self.failure = dict(failure)
        self.code = str(failure["code"])
        super().__init__(str(failure["summary"]))


def _raise_if_cancelled(cancel_event: Event | None) -> None:
    if cancel_event and cancel_event.is_set():
        raise AgentRunCancelled("Agent run was cancelled.")


class _CancellationAwareGateway:
    def __init__(self, delegate, cancel_event: Event | None):
        self.delegate = delegate
        self.cancel_event = cancel_event

    def complete(self, *args, **kwargs):
        _raise_if_cancelled(self.cancel_event)
        callback = kwargs.get("event_callback")
        if callback is not None:
            def guarded_callback(event):
                _raise_if_cancelled(self.cancel_event)
                callback(event)
                _raise_if_cancelled(self.cancel_event)

            kwargs["event_callback"] = guarded_callback
        result = self.delegate.complete(*args, **kwargs)
        _raise_if_cancelled(self.cancel_event)
        return result


def normalize_sync_task(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return {key: value for key, value in row.items() if key != "user_id"}


def make_web_search_provider(api_key: str) -> TavilyWebSearch:
    return TavilyWebSearch(
        api_key=api_key,
        post_json=post_model_json,
        timeout=WEB_SEARCH_TIMEOUT,
        max_results=WEB_SEARCH_MAX_RESULTS,
    )


def tool_risk(tool: dict[str, Any]) -> str:
    annotations = tool.get("annotations") or {}
    if annotations.get("destructiveHint") is True:
        return "destructive"
    if annotations.get("readOnlyHint") is True:
        return "read"
    if annotations.get("readOnlyHint") is False:
        return "write"
    return "unknown"


def _safe_public_value(value: Any) -> Any:
    summary = sanitize_trace_value(value, max_chars=4000)
    if summary is None:
        return None
    try:
        return json.loads(summary)
    except json.JSONDecodeError:
        return {"summary": summary}


def _exception_code(exc: Exception) -> str:
    code = str(getattr(exc, "code", "") or "").lower()
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    values = [
        code,
        str(status_code or ""),
        str(response_status or ""),
        str(exc).lower(),
    ]
    return " ".join(value for value in values if value)


def _is_unauthorized(exc: Exception) -> bool:
    code = _exception_code(exc)
    return "401" in code or "unauthorized" in code


def _is_transient_connection_error(exc: Exception) -> bool:
    code = _exception_code(exc)
    return any(
        marker in code
        for marker in (
            "connection",
            "connect",
            "timeout",
            "temporarily unavailable",
            "transport",
        )
    )


def call_mcp_tool(
    *,
    pool: McpRunSessionPool,
    oauth,
    user_id: int,
    server_id: int,
    remote_name: str,
    arguments: dict[str, Any],
    read_only: bool,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    def invoke() -> dict[str, Any]:
        _raise_if_cancelled(cancel_event)
        result = pool.call_tool(
            server_id,
            remote_name,
            arguments,
        )
        _raise_if_cancelled(cancel_event)
        safe = _safe_public_value(result)
        if isinstance(safe, dict):
            return safe
        return {"content": str(safe or "")}

    try:
        return invoke()
    except Exception as exc:
        if _is_unauthorized(exc):
            oauth.ensure_access_token(
                user_id,
                server_id,
                force_refresh=True,
            )
            _raise_if_cancelled(cancel_event)
            pool.invalidate(server_id)
            return invoke()
        if read_only and _is_transient_connection_error(exc):
            _raise_if_cancelled(cancel_event)
            pool.invalidate(server_id)
            return invoke()
        raise


def _load_mcp_server(user_id: int, server_id: int) -> dict[str, Any]:
    server = mcp_configs.secret(user_id, server_id)
    if (
        not server
        or not bool(server.get("enabled"))
        or server.get("status") != "connected"
    ):
        raise McpClientError(
            "MCP server is unavailable.",
            "mcp_server_unavailable",
        )
    credentials = dict(server.get("credentials") or {})
    headers = dict(credentials.get("headers") or {})
    if server.get("auth_type") == "oauth":
        headers.update(
            mcp_oauth.authorization_headers(user_id, server_id)
        )
    credentials["headers"] = headers
    return {**server, "credentials": credentials}


def build_tool_registry(
    user_id: int,
    enable_tools: bool,
    *,
    mcp_pool: McpRunSessionPool | None = None,
    approval_gate: AgentApprovalGate | None = None,
    cancel_event: Event | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    config = (
        tool_configs.secret(
            user_id,
            "web_search",
            require_enabled=True,
        )
        if enable_tools
        else None
    )
    registered_names: set[str] = set()
    if config:
        provider = make_web_search_provider(config["api_key"])

        def run_web_search(args: WebSearchArguments):
            _raise_if_cancelled(cancel_event)
            result = provider.search(args.query, args.top_k)
            _raise_if_cancelled(cancel_event)
            return {"results": result}

        registry.register(
            name="web_search",
            description=(
                "Search the public web for current or external information "
                "and return source URLs."
            ),
            arguments_model=WebSearchArguments,
            handler=run_web_search,
            read_only=True,
            engine_names={"current", "langgraph"},
        )
        registered_names.add("web_search")
    if not enable_tools or mcp_pool is None:
        return registry

    enabled_tools: list[dict[str, Any]] = []
    for server in mcp_configs.list_for_user(user_id):
        if (
            not server["enabled"]
            or server["status"] != "connected"
        ):
            continue
        selected = set(server.get("enabledTools") or [])
        for tool in server.get("tools") or []:
            if (
                not isinstance(tool, dict)
                or tool.get("name") not in selected
            ):
                continue
            enabled_tools.append(
                {
                    **tool,
                    "serverId": server["id"],
                    "serverName": server["name"],
                    "remoteName": (
                        tool.get("remoteName") or tool.get("name")
                    ),
                }
            )
    if len(enabled_tools) > MCP_MAX_EXPOSED_TOOLS:
        raise McpToolConfigurationError(
            "Too many MCP tools are enabled."
        )

    for tool in enabled_tools:
        name = str(tool.get("modelName") or "")
        remote_name = str(tool.get("remoteName") or "")
        input_schema = tool.get("inputSchema")
        if (
            not name
            or not remote_name
            or not isinstance(input_schema, dict)
            or name in registered_names
        ):
            raise McpToolConfigurationError(
                "The MCP tool snapshot is invalid."
            )
        read_only = (
            (tool.get("annotations") or {}).get("readOnlyHint")
            is True
            and (tool.get("annotations") or {}).get(
                "destructiveHint"
            )
            is not True
        )
        registry.register(
            name=name,
            description=str(tool.get("description") or "")[:1000],
            input_schema=input_schema,
            handler=lambda args, item=tool, safe_read=read_only: (
                call_mcp_tool(
                    pool=mcp_pool,
                    oauth=mcp_oauth,
                    user_id=user_id,
                    server_id=int(item["serverId"]),
                    remote_name=str(item["remoteName"]),
                    arguments=args,
                    read_only=safe_read,
                    cancel_event=cancel_event,
                )
            ),
            read_only=read_only,
            engine_names=(
                {"current", "langgraph"}
                if read_only
                else {"current"}
            ),
            trace_kind="mcp",
            risk=tool_risk(tool),
            server_name=str(tool["serverName"]),
        )
        registered_names.add(name)
    return registry


def execute_agent_chat(
    payload: ChatRequest,
    user_id: int,
    *,
    trace_emit: Callable[[dict[str, Any]], None] | None = None,
    approval_emit: Callable[[dict[str, Any]], None] | None = None,
    event_emit: Callable[[str, dict[str, Any]], None] | None = None,
    run_id: str | None = None,
    cancel_event: Event | None = None,
    existing_run_id: str | None = None,
    run_action: str | None = None,
    persisted_engine_name: str | None = None,
) -> dict[str, Any]:
    command_mode, normalized_question = parse_execution_mode(
        payload.question
    )
    execution_mode = (
        "plan_only"
        if command_mode == "plan_only"
        else payload.executionMode
    )
    if run_action in {"start", "resume", "restart"}:
        execution_mode = "auto"
    if not normalized_question:
        raise HTTPException(
            status_code=422,
            detail="A task is required after /plan.",
        )
    payload = payload.model_copy(
        update={
            "question": normalized_question,
            "executionMode": execution_mode,
        }
    )
    use_rag = bool(payload.knowledgeBaseId) or payload.useRag
    if use_rag and not payload.knowledgeBaseId:
        raise HTTPException(status_code=400, detail="knowledgeBaseId is required when RAG is enabled")
    if payload.knowledgeBaseId:
        get_kb(payload.knowledgeBaseId, user_id)
    durable_run_id = existing_run_id or run_id or (
        f"run_{uuid.uuid4().hex[:12]}"
    )
    selected_engine_name = normalize_agent_engine_name(
        persisted_engine_name or AGENT_ENGINE
    )
    if existing_run_id:
        durable_snapshot = agent_runs.get_snapshot(
            user_id,
            durable_run_id,
        )
        if durable_snapshot is None:
            raise HTTPException(
                status_code=404,
                detail="Agent run not found.",
            )
        session_id = str(durable_snapshot["sessionId"])
        get_session_for_user(session_id, user_id)
        payload = payload.model_copy(
            update={"sessionId": session_id}
        )
        user_message_id = durable_snapshot.get("userMessageId")
    else:
        session_id = ensure_session(
            payload.sessionId,
            payload.knowledgeBaseId,
            payload.chatModelConfigId,
            user_id,
        )
        open_run = agent_runs.get_open_run_for_session(
            user_id,
            session_id,
        )
        if open_run is not None:
            raise HTTPException(
                status_code=409,
                detail="This session already has an active Agent run.",
            )
        payload = payload.model_copy(
            update={"sessionId": session_id}
        )
        user_message_id = save_message(
            session_id,
            "user",
            payload.question,
        )
        stored_request = payload.model_dump(mode="json")
        stored_request["_agentEngine"] = selected_engine_name
        stored_request["attachments"] = [
            {**item, "previewUrl": None}
            for item in stored_request.get("attachments", [])
        ]
        durable_snapshot = agent_runs.create_run(
            user_id=user_id,
            session_id=session_id,
            user_message_id=user_message_id,
            goal_summary=(
                sanitize_trace_value(
                    payload.question,
                    max_chars=700,
                )
                or "Agent task"
            ),
            trigger_mode=execution_mode,
            request_payload=stored_request,
            run_id=durable_run_id,
        )

    def emit_named(
        event_name: str,
        value: dict[str, Any],
    ) -> None:
        if event_emit:
            event_emit(event_name, value)

    def publish_snapshot(event_name: str) -> dict[str, Any]:
        snapshot = agent_runs.get_snapshot(
            user_id,
            durable_run_id,
        )
        if snapshot is None:
            raise RuntimeError("Agent run snapshot is unavailable.")
        emit_named(event_name, {"run": snapshot})
        return snapshot

    emit_named("run_snapshot", {"run": durable_snapshot})

    history: list[dict[str, Any]] = []

    trace: AgentTraceRecorder

    def persist_trace(event: dict[str, Any]) -> None:
        agent_runs.update_trace(
            user_id,
            durable_run_id,
            trace.snapshot(),
        )
        if trace_emit:
            trace_emit(event)
        emit_named("agent_step", event)

    trace = AgentTraceRecorder(
        emit=persist_trace,
        run_id=durable_run_id,
    )
    root_step = trace.start_step(
        kind="system",
        name="agent_run",
        title="Agent is running",
    )
    calls: list[dict[str, Any]] = []
    retrieval_run: dict[str, Any] | None = None
    rag_quality: dict[str, Any] = {"enabled": False}
    chunks: list[dict[str, Any]] = []
    current_plan_step_id: str | None = None
    execution_records: list[tuple[Any, str | None]] = []
    plan_snapshot: dict[str, Any] | None = None
    run_failed = False
    try:
        if run_action == "replan":
            agent_runs.transition_run(
                user_id,
                durable_run_id,
                "planning",
            )
            publish_snapshot("run_updated")
        elif run_action in {"start", "resume"}:
            agent_runs.transition_run(
                user_id,
                durable_run_id,
                "running",
            )
            publish_snapshot("run_updated")
        if use_rag and payload.knowledgeBaseId:
            started_at = time.perf_counter()
            chunks = retrieve_chunks(
                payload.knowledgeBaseId,
                payload.question,
                DEFAULT_TOP_K,
                user_id,
            )
            chunks = enrich_retrieval_chunks(
                payload.question,
                chunks,
            )
            duration_ms = int(
                (time.perf_counter() - started_at) * 1000
            )
            rag_quality = assess_retrieval_quality(
                payload.question,
                chunks,
            )
            retrieval_run = record_retrieval_run(
                user_id=user_id,
                knowledge_base_id=payload.knowledgeBaseId,
                query=payload.question,
                top_k=DEFAULT_TOP_K,
                chunks=chunks,
                quality=rag_quality,
                duration_ms=duration_ms,
            )
            rag_quality = {
                **rag_quality,
                "retrievalRunId": retrieval_run.get("id"),
            }
        chat_config = get_model_config(
            payload.chatModelConfigId,
            "chat",
            user_id,
        )
        _raise_if_cancelled(cancel_event)
        with McpRunSessionPool(
            server_loader=lambda server_id: _load_mcp_server(
                user_id,
                int(server_id),
            ),
            oauth=mcp_oauth,
            connect_timeout=MCP_CONNECT_TIMEOUT,
            request_timeout=MCP_REQUEST_TIMEOUT,
            max_response_bytes=MCP_MAX_RESPONSE_BYTES,
            allow_private=MCP_ALLOW_PRIVATE_NETWORKS,
        ) as mcp_pool:
            registry = build_tool_registry(
                user_id,
                payload.enableTools,
                mcp_pool=mcp_pool,
                cancel_event=cancel_event,
            )
            available_skill_dependencies = set(registry.names())
            if payload.enableTools:
                available_skill_dependencies.update(
                    str(server.get("slug") or "")
                    for server in mcp_configs.list_for_user(user_id)
                    if server.get("enabled")
                    and server.get("status") == "connected"
                    and server.get("slug")
                )
            activation = SkillActivationSession(
                store=skills,
                user_id=user_id,
                available_tools=available_skill_dependencies,
            )
            run_parent_step = root_step
            explicit_activation = None
            if payload.skillId is not None:
                try:
                    explicit_activation = activation.activate(
                        payload.skillId
                    )
                except SkillRuntimeError as exc:
                    status_code = (
                        404
                        if exc.code == "skill_not_found"
                        else 409
                    )
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "code": exc.code,
                            "message": str(exc),
                            "data": None,
                        },
                    ) from exc
                activation.register_read_resource(registry)
                audit = explicit_activation.audit_output or {}
                run_parent_step = trace.start_step(
                    kind="skill",
                    name="activate_skill",
                    title="Activating Skill",
                    parent_id=root_step,
                    input_summary={"skillId": payload.skillId},
                    details=audit,
                )
                trace.finish_step(
                    run_parent_step,
                    status="success",
                    title="Skill activated",
                    output_summary=audit,
                )
            history = get_recent_history(session_id)

            def durable_approval_emit(
                event: dict[str, Any],
            ) -> None:
                nonlocal current_plan_step_id
                if current_plan_step_id:
                    if event["type"] == "approval_required":
                        agent_runs.transition_step(
                            user_id,
                            durable_run_id,
                            current_plan_step_id,
                            "waiting_approval",
                        )
                        agent_runs.transition_run(
                            user_id,
                            durable_run_id,
                            "waiting_approval",
                        )
                        publish_snapshot("step_updated")
                    elif event["type"] == "approval_resolved":
                        snapshot = agent_runs.get_snapshot(
                            user_id,
                            durable_run_id,
                        )
                        step = next(
                            (
                                item
                                for item in (snapshot or {}).get(
                                    "steps", []
                                )
                                if item["id"]
                                == current_plan_step_id
                            ),
                            None,
                        )
                        if (
                            step
                            and step["status"]
                            == "waiting_approval"
                        ):
                            decision = event.get("decision")
                            if decision == "allow_once":
                                agent_runs.transition_step(
                                    user_id,
                                    durable_run_id,
                                    current_plan_step_id,
                                    "running",
                                )
                                agent_runs.transition_run(
                                    user_id,
                                    durable_run_id,
                                    "running",
                                )
                            else:
                                agent_runs.transition_step(
                                    user_id,
                                    durable_run_id,
                                    current_plan_step_id,
                                    "failed",
                                    error_code=(
                                        "approval_timeout"
                                        if decision == "timeout"
                                        else "permission_denied"
                                    ),
                                )
                            publish_snapshot("step_updated")
                if approval_emit:
                    approval_emit(event)
                emit_named(str(event["type"]), event)

            approval_gate = (
                AgentApprovalGate(
                    broker=approval_broker,
                    user_id=user_id,
                    run_id=trace.run_id,
                    emit=durable_approval_emit,
                    trace=trace,
                    parent_step_id=run_parent_step,
                )
                if approval_emit or event_emit
                else None
            )
            catalog = []
            if payload.skillId is None:
                catalog = activation.catalog()
                if catalog:
                    activation.register_activation_tool(registry)
            memory_active = memory_manager.active(user_id)
            memories = []
            if memory_active:
                memory_recall_step = trace.start_step(
                    kind="memory",
                    name="memory_recall",
                    title="Recalling long-term memory",
                    parent_id=run_parent_step,
                )
                memories = memory_manager.recall(
                    user_id,
                    payload.question,
                )
                trace.finish_step(
                    memory_recall_step,
                    status="success",
                    title="Long-term memory recall completed",
                    output_summary={"recalled": len(memories)},
                )
            base_messages = build_messages(
                payload.question,
                chunks,
                history,
                agent_mode=bool(registry.schemas()),
                use_rag=use_rag,
                chat_config=chat_config,
                attachments=payload.attachments,
                memories=memories if memory_active else None,
            )
            if catalog:
                base_messages[0]["content"] += (
                    "\nAvailable Skills (activate at most one with "
                    "activate_skill): "
                    + json.dumps(catalog, ensure_ascii=False)
                )
            if activation.active is not None:
                base_messages.insert(
                    1,
                    {
                        "role": "system",
                        "content": activation.active.system_message,
                    },
                )

            def capture_plan(value: dict[str, Any]) -> None:
                nonlocal plan_snapshot
                plan_snapshot = value

            should_plan = (
                existing_run_id is None
                or run_action in {"replan", "restart"}
            ) and (
                payload.autoAgent
                or execution_mode == "plan_only"
                or (
                    activation.active is not None
                    and activation.active.planning == "required"
                )
            )
            if should_plan:
                register_task_planner(registry, capture_plan)

            def record_execution(execution, tool_step_id) -> None:
                if (
                    execution.tool_name == "create_task_plan"
                    and execution.status == "success"
                    and plan_snapshot is not None
                ):
                    steps = agent_runs.replace_plan(
                        user_id,
                        durable_run_id,
                        plan_snapshot["steps"],
                    )
                    target_status = (
                        "waiting_start"
                        if execution_mode == "plan_only"
                        else "running"
                    )
                    agent_runs.transition_run(
                        user_id,
                        durable_run_id,
                        target_status,
                    )
                    publish_snapshot("plan_created")
                    raise TaskPlanCreated()
                execution_records.append(
                    (execution, current_plan_step_id)
                )

            def forward_model_event(event: dict[str, Any]) -> None:
                if (
                    event.get("type") == "text_delta"
                    and event.get("text")
                ):
                    emit_named(
                        "message",
                        {
                            "type": "answer",
                            "content": str(event["text"]),
                        },
                    )

            engine = build_agent_engine(
                selected_engine_name,
                gateway=_CancellationAwareGateway(
                    gateway,
                    cancel_event,
                ),
                max_tool_rounds=3,
                checkpoint_db_path=LANGGRAPH_CHECKPOINT_DB,
            )
            answer = ""
            run_result = None
            try:
                if run_action in {"start", "resume"}:
                    planned = agent_runs.get_snapshot(
                        user_id,
                        durable_run_id,
                    )
                    plan_created = bool(
                        (planned or {}).get("steps")
                    )
                    if (
                        run_action == "resume"
                        and not plan_created
                        and engine.name == "langgraph"
                    ):
                        run_result = engine.run(
                            user_id=user_id,
                            run_id=durable_run_id,
                            messages=[],
                            config=chat_config,
                            registry=registry,
                            trace=trace,
                            parent_step_id=run_parent_step,
                            approval_gate=approval_gate,
                            skill_snapshot=(
                                activation.active.snapshot()
                                if activation.active is not None
                                else None
                            ),
                            execution_callback=record_execution,
                            model_event_callback=forward_model_event,
                            resume_from_checkpoint=True,
                        )
                        answer = run_result.answer
                else:
                    planning_messages = [
                        dict(message)
                        for message in base_messages
                    ]
                    if execution_mode == "plan_only":
                        planning_messages.insert(
                            1,
                            {
                                "role": "system",
                                "content": (
                                    "You must call create_task_plan. "
                                    "Do not execute the plan yet."
                                ),
                            },
                        )
                    try:
                        run_result = engine.run(
                            user_id=user_id,
                            run_id=durable_run_id,
                            messages=planning_messages,
                            config=chat_config,
                            registry=registry,
                            trace=trace,
                            parent_step_id=run_parent_step,
                            approval_gate=approval_gate,
                            skill_snapshot=(
                                activation.active.snapshot()
                                if activation.active is not None
                                else None
                            ),
                            execution_callback=record_execution,
                            model_event_callback=forward_model_event,
                        )
                        answer = run_result.answer
                        plan_created = False
                    except TaskPlanCreated:
                        plan_created = True

                if plan_created and execution_mode == "plan_only":
                    answer = "The plan is ready and waiting to start."
                elif plan_created:
                    planned = agent_runs.get_snapshot(
                        user_id,
                        durable_run_id,
                    )
                    completed_context: list[str] = []
                    for step in (planned or {}).get("steps", []):
                        if step["status"] == "completed":
                            if step.get("outputSummary"):
                                completed_context.append(
                                    str(step["outputSummary"])
                                )
                            continue
                        if step["status"] not in {
                            "pending",
                            "failed",
                        }:
                            continue
                        _raise_if_cancelled(cancel_event)
                        current_plan_step_id = step["id"]
                        agent_runs.transition_step(
                            user_id,
                            durable_run_id,
                            current_plan_step_id,
                            "running",
                        )
                        publish_snapshot("step_updated")
                        plan_trace_step = trace.start_step(
                            kind="system",
                            name="task_plan_step",
                            title=step["title"],
                            parent_id=run_parent_step,
                            details={
                                "planStepId": current_plan_step_id
                            },
                        )
                        if approval_gate:
                            approval_gate.set_parent_step_id(
                                plan_trace_step
                            )
                        step_messages = [
                            dict(message)
                            for message in base_messages
                        ]
                        step_messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Current public plan step: "
                                    f"{step['title']}\n"
                                    "Complete only this step. Return a "
                                    "concise public result. Never reveal "
                                    "private chain-of-thought.\n"
                                    "Completed public results: "
                                    + json.dumps(
                                        completed_context,
                                        ensure_ascii=False,
                                    )
                                ),
                            }
                        )
                        record_start = len(execution_records)
                        step_result = engine.run(
                            user_id=user_id,
                            run_id=durable_run_id,
                            messages=step_messages,
                            config=chat_config,
                            registry=registry,
                            trace=trace,
                            parent_step_id=plan_trace_step,
                            approval_gate=approval_gate,
                            skill_snapshot=(
                                activation.active.snapshot()
                                if activation.active is not None
                                else None
                            ),
                            execution_callback=record_execution,
                        )
                        new_records = execution_records[
                            record_start:
                        ]
                        failed_execution = next(
                            (
                                execution
                                for execution, _ in new_records
                                if execution.status != "success"
                            ),
                            None,
                        )
                        if failed_execution is not None:
                            raise AgentStepExecutionError(
                                classify_agent_failure(
                                    code=failed_execution.error_code,
                                    source="tool",
                                )
                            )
                        public_result = (
                            sanitize_trace_value(
                                step_result.answer,
                                max_chars=700,
                            )
                            or "Step completed."
                        )
                        trace.finish_step(
                            plan_trace_step,
                            status="success",
                            title=f"{step['title']} completed",
                            output_summary=public_result,
                        )
                        agent_runs.transition_step(
                            user_id,
                            durable_run_id,
                            current_plan_step_id,
                            "completed",
                            output_summary=public_result,
                        )
                        publish_snapshot("step_updated")
                        completed_context.append(public_result)
                        answer = step_result.answer
                    current_plan_step_id = None
                else:
                    agent_runs.transition_run(
                        user_id,
                        durable_run_id,
                        "running",
                    )
                    publish_snapshot("run_updated")
                _raise_if_cancelled(cancel_event)
            except Exception as exc:
                if isinstance(exc, (AgentRunCancelled, TaskPlanCreated)):
                    raise
                failure = (
                    exc.failure
                    if isinstance(exc, AgentStepExecutionError)
                    else classify_agent_failure(exc)
                )
                run_failed = True
                if current_plan_step_id:
                    snapshot = agent_runs.get_snapshot(
                        user_id,
                        durable_run_id,
                    )
                    current = next(
                        (
                            item
                            for item in (snapshot or {}).get(
                                "steps", []
                            )
                            if item["id"] == current_plan_step_id
                        ),
                        None,
                    )
                    if current and current["status"] in {
                        "running",
                        "waiting_approval",
                    }:
                        agent_runs.transition_step(
                            user_id,
                            durable_run_id,
                            current_plan_step_id,
                            "failed",
                            output_summary=str(failure["summary"]),
                            error_code=str(failure["code"]),
                        )
                trace.finish_step(
                    root_step,
                    status="failed",
                    title="Agent run failed",
                    output_summary=failure["summary"],
                    error_code=str(failure["code"]),
                )
                if isinstance(exc, LangGraphCheckpointError):
                    answer = exc.message
                elif has_remote_model_config(chat_config):
                    answer = remote_model_error_answer(
                        chat_config,
                        exc,
                    )
                else:
                    answer = fallback_answer(
                        payload.question,
                        chunks,
                        history,
                        agent_mode=bool(registry.schemas()),
                        use_rag=use_rag,
                        attachments=payload.attachments,
                    )
        _raise_if_cancelled(cancel_event)
        skill_snapshot = (
            activation.active.snapshot()
            if activation.active is not None
            else None
        )
        for execution, execution_step_id in execution_records:
            if execution.tool_name == "create_task_plan":
                continue
            safe_arguments = _safe_public_value(
                (
                    {}
                    if execution.tool_name
                    in {"activate_skill", "read_skill_resource"}
                    else execution.arguments
                )
            )
            if not isinstance(safe_arguments, dict):
                safe_arguments = {
                    "summary": str(safe_arguments or "")
                }
            safe_output = (
                sanitize_trace_value(
                    execution.public_output(),
                    max_chars=4000,
                )
                or ""
            )
            safe_error = sanitize_trace_value(
                execution.error_message,
                max_chars=1000,
            )
            calls.append(
                log_tool_call(
                    session_id,
                    None,
                    execution.tool_name,
                    safe_arguments,
                    safe_output,
                    status=execution.status,
                    error_message=safe_error,
                    latency_ms=execution.latency_ms,
                    skill_snapshot=execution.skill_snapshot,
                    run_id=durable_run_id,
                    run_step_id=execution_step_id,
                )
            )
        final_snapshot = agent_runs.get_snapshot(
            user_id,
            durable_run_id,
        )
        waiting_start = (
            final_snapshot is not None
            and final_snapshot["status"] == "waiting_start"
        )
        if trace.steps[root_step]["status"] == "running":
            trace.finish_step(
                root_step,
                status="failed" if run_failed else "success",
                title=(
                    "Agent run failed"
                    if run_failed
                    else (
                        "Agent plan ready"
                        if waiting_start
                        else "Agent run completed"
                    )
                ),
                error_code=(
                    "agent_run_failed" if run_failed else None
                ),
            )
        _raise_if_cancelled(cancel_event)
        trace_snapshot = trace.snapshot()
        current_snapshot = agent_runs.get_snapshot(
            user_id,
            durable_run_id,
        )
        existing_message_id = (
            current_snapshot.get("assistantMessageId")
            if current_snapshot
            else None
        )
        if existing_message_id:
            execute(
                """
                UPDATE chat_message
                SET content=:content, trace_json=:trace_json
                WHERE id=:message_id AND session_id=:session_id
                """,
                {
                    "content": answer,
                    "trace_json": json.dumps(
                        trace_snapshot,
                        ensure_ascii=False,
                    ),
                    "message_id": existing_message_id,
                    "session_id": session_id,
                },
            )
            message_id = int(existing_message_id)
        else:
            message_id = save_message(
                session_id,
                "assistant",
                answer,
                trace=trace_snapshot,
                skill_snapshot=skill_snapshot,
            )
            agent_runs.attach_assistant_message(
                user_id,
                durable_run_id,
                message_id,
            )
        memory_activity = None
        if memory_active:
            _, memory_write_id = memory_operation_store.create_for_message(
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                agent_run_id=durable_run_id,
                recalled=memories,
            )
            trace.start_step(
                kind="memory",
                name="memory_write",
                title="Waiting for long-term memory write",
                parent_id=root_step,
                status="waiting",
                details={"operationId": memory_write_id},
            )
            trace_snapshot = trace.snapshot()
            execute(
                """
                UPDATE chat_message
                SET trace_json=:trace_json
                WHERE id=:message_id AND session_id=:session_id
                """,
                {
                    "trace_json": json.dumps(
                        trace_snapshot,
                        ensure_ascii=False,
                    ),
                    "message_id": message_id,
                    "session_id": session_id,
                },
            )
            memory_operation_runner.wake()
            memory_activity = (
                memory_operation_store.activity_for_message(
                    user_id=user_id,
                    message_id=message_id,
                )
            )
        update_retrieval_run_message(
            retrieval_run.get("id") if retrieval_run else None,
            message_id,
        )
        refs = save_references(message_id, chunks)
        for call in calls:
            execute(
                """
                UPDATE agent_tool_call
                SET message_id=:message_id
                WHERE id=:id AND session_id=:session_id
                """,
                {
                    "message_id": message_id,
                    "id": call["id"],
                    "session_id": session_id,
                },
            )
        latest = agent_runs.get_snapshot(
            user_id,
            durable_run_id,
        )
        if latest and not waiting_start:
            if run_failed:
                if latest["status"] in {
                    "planning",
                    "running",
                    "waiting_approval",
                }:
                    agent_runs.transition_run(
                        user_id,
                        durable_run_id,
                        "failed",
                    )
            elif latest["status"] != "completed":
                agent_runs.transition_run(
                    user_id,
                    durable_run_id,
                    "completed",
                )
        final_snapshot = publish_snapshot("run_updated")
        return {
            "sessionId": session_id,
            "messageId": message_id,
            "answer": answer,
            "references": refs,
            "toolCalls": calls,
            "ragQuality": rag_quality,
            "retrievalRun": retrieval_run,
            "trace": trace_snapshot,
            "runId": durable_run_id,
            "run": final_snapshot,
            "memoryActivity": memory_activity,
        }
    except AgentRunCancelled:
        snapshot = agent_runs.get_snapshot(user_id, durable_run_id)
        if current_plan_step_id and snapshot:
            step = next(
                (
                    item
                    for item in snapshot.get("steps", [])
                    if item["id"] == current_plan_step_id
                ),
                None,
            )
            if step and step["status"] in {
                "running",
                "waiting_approval",
            }:
                agent_runs.transition_step(
                    user_id,
                    durable_run_id,
                    current_plan_step_id,
                    "cancelled",
                )
        snapshot = agent_runs.get_snapshot(user_id, durable_run_id)
        if snapshot and snapshot["status"] not in {
            "completed",
            "failed",
            "cancelled",
        }:
            agent_runs.transition_run(
                user_id,
                durable_run_id,
                "cancelled",
            )
        if trace.steps[root_step]["status"] == "running":
            trace.finish_step(
                root_step,
                status="cancelled",
                title="Agent run cancelled",
                error_code="agent_run_cancelled",
            )
        publish_snapshot("cancelled")
        raise
    except Exception as exc:
        failure = classify_agent_failure(exc)
        if trace.steps[root_step]["status"] == "running":
            trace.finish_step(
                root_step,
                status="failed",
                title="Agent run failed",
                output_summary=failure["summary"],
                error_code=str(failure["code"]),
            )
        snapshot = agent_runs.get_snapshot(user_id, durable_run_id)
        if snapshot and snapshot["status"] in {
            "planning",
            "running",
            "waiting_approval",
        }:
            agent_runs.transition_run(
                user_id,
                durable_run_id,
                "failed",
            )
        publish_snapshot("run_updated")
        raise


@router.post("/api/agent/chat", tags=EXTENSION_TAGS, summary="Create an agent chat answer")
def agent_chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
    return api_success(
        execute_agent_chat(
            payload,
            current_user_id(request),
        )
    )


def _agent_done_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "done",
        "runId": result["runId"],
        "sessionId": result["sessionId"],
        "messageId": result["messageId"],
        "trace": result["trace"],
        "run": result.get("run"),
        "memoryActivity": result.get("memoryActivity"),
    }


def _publish_agent_result(
    result: dict[str, Any],
    publish: Callable[[dict[str, Any]], None],
) -> None:
    for call in result.get("toolCalls", []):
        publish({"type": "tool", **call})
    for index in range(0, len(result["answer"]), 12):
        publish(
            {
                "type": "answer",
                "content": result["answer"][index : index + 12],
            }
        )
    for reference in result.get("references", []):
        publish({"type": "reference", **reference})
    if result.get("ragQuality", {}).get("enabled"):
        publish(
            {
                "type": "quality",
                "ragQuality": result["ragQuality"],
                "retrievalRun": result.get("retrievalRun"),
            }
        )
    publish(_agent_done_payload(result))


def execute_persisted_agent_run(
    user_id: int,
    run_id: str,
    action: str,
    cancel_event: Event,
    publish: Callable[[dict[str, Any]], None],
) -> None:
    request_payload = agent_runs.load_request(user_id, run_id)
    if request_payload is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    persisted_engine_name = request_payload.pop("_agentEngine", None)
    payload = ChatRequest.model_validate(request_payload)
    result = execute_agent_chat(
        payload,
        user_id,
        existing_run_id=run_id,
        run_action=action,
        persisted_engine_name=persisted_engine_name,
        cancel_event=cancel_event,
        event_emit=lambda name, value: publish(
            {"type": name, **value}
        ),
    )
    _publish_agent_result(result, publish)


@router.post("/api/agent/chat/stream", tags=EXTENSION_TAGS, summary="Stream an agent chat")
def agent_chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    user_id = current_user_id(request)
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    def generate() -> Iterable[str]:
        queue: Queue[tuple[str, Any]] = Queue()
        streamed_answer = False
        def enqueue(
            event_name: str,
            payload_value: dict[str, Any],
        ) -> None:
            safe = _safe_public_value(
                {
                    "type": event_name,
                    **payload_value,
                }
            )
            if isinstance(safe, dict):
                queue.put((event_name, safe))

        def worker(
            cancel_event: Event,
            publish: Callable[[dict[str, Any]], None],
        ) -> None:
            def emit_both(
                event_name: str,
                value: dict[str, Any],
            ) -> None:
                enqueue(event_name, value)
                publish({"type": event_name, **value})

            try:
                result = execute_agent_chat(
                    payload,
                    user_id,
                    run_id=run_id,
                    event_emit=emit_both,
                    cancel_event=cancel_event,
                )
                queue.put(("result", result))
                _publish_agent_result(result, publish)
            except Exception as exc:
                if isinstance(exc, AgentRunCancelled):
                    queue.put(
                        (
                            "cancelled",
                            {
                                "code": "agent_run_cancelled",
                                "message": "Agent run was cancelled.",
                            },
                        )
                    )
                    return
                failure = classify_agent_failure(
                    exc,
                    source=(
                        "mcp"
                        if isinstance(exc, McpToolConfigurationError)
                        else "agent"
                    ),
                )
                queue.put(
                    (
                        "error",
                        {
                            "code": failure["code"],
                            "message": failure["summary"],
                        },
                    )
                )

        if not agent_run_coordinator.start(run_id, worker):
            yield sse_event(
                "error",
                {
                    "type": "error",
                    "code": "agent_run_conflict",
                    "message": "Agent run is already active.",
                },
            )
            return
        try:
            while True:
                event_name, value = queue.get()
                if event_name in {
                    "agent_step",
                    "run_snapshot",
                    "plan_created",
                    "run_updated",
                    "step_updated",
                    "approval_required",
                    "approval_resolved",
                }:
                    yield sse_event(event_name, value)
                    continue
                if event_name == "message":
                    streamed_answer = True
                    yield sse_event("message", value)
                    continue
                if event_name == "error":
                    yield sse_event(
                        "error",
                        {
                            "type": "error",
                            **value,
                        },
                    )
                    break
                if event_name == "cancelled":
                    yield sse_event(
                        "cancelled",
                        {"type": "cancelled", **value},
                    )
                    break
                result = value
                for call in result.get("toolCalls", []):
                    yield sse_event(
                        "tool",
                        {"type": "tool", **call},
                    )
                if not streamed_answer:
                    for index in range(
                        0,
                        len(result["answer"]),
                        12,
                    ):
                        yield sse_event(
                            "message",
                            {
                                "type": "answer",
                                "content": result["answer"][
                                    index : index + 12
                                ],
                            },
                        )
                for ref in result["references"]:
                    yield sse_event(
                        "reference",
                        {"type": "reference", **ref},
                    )
                if result.get("ragQuality", {}).get("enabled"):
                    yield sse_event(
                        "quality",
                        {
                            "type": "quality",
                            "ragQuality": result["ragQuality"],
                            "retrievalRun": result.get(
                                "retrievalRun"
                            ),
                        },
                    )
                yield sse_event(
                    "done",
                    _agent_done_payload(result),
                )
                break
        finally:
            pass

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/sessions/{session_id}/tool-calls", tags=EXTENSION_TAGS, summary="Read session tool calls")
def read_session_tool_calls(session_id: str, request: Request) -> dict[str, Any]:
    get_session_for_user(session_id, current_user_id(request))
    return api_success(fetch_all("SELECT * FROM agent_tool_call WHERE session_id=:session_id ORDER BY id DESC", {"session_id": session_id}))


@router.get("/api/messages/{message_id}/tool-calls", tags=EXTENSION_TAGS, summary="Read answer tool calls")
def read_message_tool_calls(message_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    if not fetch_one(
        """
        SELECT cm.id
        FROM chat_message cm
        JOIN chat_session cs ON cs.id = cm.session_id
        WHERE cm.id=:message_id AND cs.user_id=:user_id
        """,
        {"message_id": message_id, "user_id": user_id},
    ):
        raise HTTPException(status_code=404, detail="Message not found.")
    return api_success(fetch_all("SELECT * FROM agent_tool_call WHERE message_id=:message_id ORDER BY id DESC", {"message_id": message_id}))


@router.post("/api/sync/tasks", tags=EXTENSION_TAGS, summary="Create a sync task record")
def create_sync_task(payload: SyncTaskIn, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    if payload.knowledgeBaseId is not None:
        get_kb(payload.knowledgeBaseId, user_id)
    task_id = execute(
        """
        INSERT INTO sync_task(user_id, source_type, source_url, target_type, knowledge_base_id, status, result_message, created_at, updated_at)
        VALUES (:user_id, :source_type, :source_url, :target_type, :knowledge_base_id, 'pending', :result_message, :created_at, :updated_at)
        """,
        {
            "user_id": user_id,
            "source_type": payload.sourceType,
            "source_url": payload.sourceUrl,
            "target_type": payload.targetType,
            "knowledge_base_id": payload.knowledgeBaseId,
            "result_message": "Sync task recorded. Real execution is available after Notion or GitHub authorization is connected.",
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    row = fetch_one("SELECT * FROM sync_task WHERE id=:id AND user_id=:user_id", {"id": task_id, "user_id": user_id})
    return api_success(normalize_sync_task(row))


@router.get("/api/sync/tasks", tags=EXTENSION_TAGS, summary="List sync tasks")
def list_sync_tasks(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rows = fetch_all("SELECT * FROM sync_task WHERE user_id=:user_id ORDER BY id DESC", {"user_id": user_id})
    return api_success([normalize_sync_task(row) for row in rows])


@router.get("/api/sync/tasks/{task_id}", tags=EXTENSION_TAGS, summary="Read sync task details")
def read_sync_task(task_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    row = fetch_one("SELECT * FROM sync_task WHERE id=:id AND user_id=:user_id", {"id": task_id, "user_id": user_id})
    if not row:
        raise HTTPException(status_code=404, detail="Sync task not found.")
    return api_success(normalize_sync_task(row))


@router.post("/api/publish/github", tags=EXTENSION_TAGS, summary="Reserved GitHub publish endpoint")
def publish_github(payload: GithubPublishIn) -> dict[str, Any]:
    return api_success(
        {
            "repo": payload.repo,
            "branch": payload.branch,
            "path": payload.path,
            "status": "recorded",
            "message": "Publish request recorded. Real publishing is available after a GitHub token is connected.",
        }
    )
