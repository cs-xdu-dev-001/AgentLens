import json
from queue import Empty, Queue
from threading import Event, Thread
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

from ..runtime import *
from ..services.session_portability import (
    render_session_markdown,
    safe_export_filename,
    unique_branch_title,
)
from ..services.context_compaction import (
    ContextCompactionError,
    SUMMARY_MARKER,
    compact_context,
    context_status,
)
from ..services.workspace_references import has_workspace_references
from .extensions import agent_chat, agent_chat_stream

router = APIRouter()

CHAT_TAGS = ["Chat"]
SESSION_TAGS = ["Sessions"]


def _session_run_duration_ms(row: dict[str, Any]) -> int:
    def timestamp(value: Any) -> float | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00")
            )
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    started = timestamp(row.get("started_at") or row.get("created_at"))
    if started is None:
        return 0
    finished = timestamp(row.get("finished_at"))
    if finished is None and str(row.get("status") or "") not in {
        "planning",
        "running",
        "waiting_approval",
        "waiting_input",
    }:
        finished = timestamp(row.get("updated_at"))
    end = finished if finished is not None else datetime.now(timezone.utc).timestamp()
    return max(0, int((end - started) * 1000))


def _latest_session_runs(user_id: int) -> dict[str, dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT current.id, current.session_id, current.goal_summary,
               current.status, current.started_at, current.finished_at,
               current.created_at, current.updated_at,
               (
                 SELECT COUNT(*) FROM agent_run_step step
                 WHERE step.run_id=current.id
               ) AS total_steps,
               (
                 SELECT COUNT(*) FROM agent_run_step step
                 WHERE step.run_id=current.id AND step.status='completed'
               ) AS completed_steps
        FROM agent_run current
        WHERE current.user_id=:user_id
          AND NOT EXISTS (
            SELECT 1 FROM agent_run newer
            WHERE newer.user_id=current.user_id
              AND newer.session_id=current.session_id
              AND (
                newer.created_at > current.created_at
                OR (
                  newer.created_at = current.created_at
                  AND newer.id > current.id
                )
              )
          )
        """,
        {"user_id": user_id},
    )
    return {
        str(row["session_id"]): {
            "id": row["id"],
            "goalSummary": row.get("goal_summary") or "Agent task",
            "status": row.get("status") or "planning",
            "startedAt": row.get("started_at"),
            "finishedAt": row.get("finished_at"),
            "updatedAt": row.get("updated_at"),
            "durationMs": _session_run_duration_ms(row),
            "progress": {
                "completed": int(row.get("completed_steps") or 0),
                "total": int(row.get("total_steps") or 0),
            },
        }
        for row in rows
    }


def should_route_to_agent(payload: ChatRequest) -> bool:
    tool_mode = (payload.toolMode or "auto").lower()
    first_token = (payload.question or "").strip().split(maxsplit=1)
    plan_command = bool(
        first_token
        and first_token[0].lower() == "/plan"
    )
    manual_tools = (
        tool_mode == "manual"
        and bool(payload.enabledTools)
    )
    auto_tools = (
        tool_mode == "auto"
        and payload.enableTools
    )
    return (
        plan_command
        or has_workspace_references(payload.question)
        or payload.skillId is not None
        or manual_tools
        or auto_tools
        or (
            payload.autoAgent
            and should_use_agent(payload.question)
        )
    )


@router.post("/api/chat/attachments", tags=CHAT_TAGS, summary="Upload a chat attachment")
async def upload_chat_attachment(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = sanitize_upload_filename(file.filename or f"upload-{uuid.uuid4().hex}.txt")
    data = await read_upload_file_with_limit(file)
    validate_upload_file(filename, data)
    suffix = Path(filename).suffix.lower()
    try:
        content = extract_text_from_upload(filename, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"File parsing failed: {exc}") from exc
    content = content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="No usable text was extracted from this file.")
    clipped = content[:12000]
    mime_type = file.content_type or IMAGE_MIME_TYPES.get(suffix)
    preview_url = None
    if suffix in IMAGE_SUFFIXES:
        preview_url = f"data:{mime_type or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}"
    return api_success(
        {
            "attachmentId": uuid.uuid4().hex,
            "filename": filename,
            "fileType": suffix.lstrip("."),
            "mimeType": mime_type,
            "fileSize": len(data),
            "content": clipped,
            "preview": clipped[:500],
            "previewUrl": preview_url,
            "tokenCount": len(tokenize(clipped)),
        }
    )


class _ChatStreamCancelled(BaseException):
    pass


def run_chat(
    payload: ChatRequest,
    request: Request,
    *,
    model_event_callback=None,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    use_rag = bool(payload.knowledgeBaseId) or payload.useRag
    if use_rag and not payload.knowledgeBaseId:
        raise HTTPException(status_code=400, detail="knowledgeBaseId is required when RAG is enabled")
    if should_route_to_agent(payload):
        payload.useRag = use_rag
        return agent_chat(payload, request)
    if payload.knowledgeBaseId:
        get_kb(payload.knowledgeBaseId, user_id)
    session_id = ensure_session(payload.sessionId, payload.knowledgeBaseId, payload.chatModelConfigId, user_id)
    save_message(session_id, "user", payload.question)
    history = get_recent_history(session_id)
    retrieval_run: dict[str, Any] | None = None
    rag_quality: dict[str, Any] = {"enabled": False}
    chunks: list[dict[str, Any]] = []
    if use_rag and payload.knowledgeBaseId:
        started_at = time.perf_counter()
        chunks = retrieve_chunks(payload.knowledgeBaseId, payload.question, DEFAULT_TOP_K, user_id)
        chunks = enrich_retrieval_chunks(payload.question, chunks)
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        rag_quality = assess_retrieval_quality(payload.question, chunks)
        retrieval_run = record_retrieval_run(
            user_id=user_id,
            knowledge_base_id=payload.knowledgeBaseId,
            query=payload.question,
            top_k=DEFAULT_TOP_K,
            chunks=chunks,
            quality=rag_quality,
            duration_ms=duration_ms,
        )
        rag_quality = {**rag_quality, "retrievalRunId": retrieval_run.get("id")}
    memory_active = memory_manager.active(user_id)
    memories = (
        memory_manager.recall(user_id, payload.question)
        if memory_active
        else []
    )
    chat_config = get_model_config(payload.chatModelConfigId, "chat", user_id)
    if chat_config is not None:
        chat_config = {
            **chat_config,
            "reasoning_effort": payload.reasoningEffort,
        }
    answer_options = {
        "use_rag": use_rag,
        "attachments": payload.attachments,
        "memories": memories if memory_active else None,
    }
    if model_event_callback is not None:
        answer_options["event_callback"] = model_event_callback
    answer = generate_answer(
        payload.question,
        chunks,
        history,
        chat_config,
        **answer_options,
    )
    message_id = save_message(session_id, "assistant", answer)
    memory_activity = None
    if memory_active:
        memory_operation_store.create_for_message(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            agent_run_id=None,
            recalled=memories,
        )
        memory_operation_runner.wake()
        memory_activity = memory_operation_store.activity_for_message(
            user_id=user_id,
            message_id=message_id,
        )
    update_retrieval_run_message(retrieval_run.get("id") if retrieval_run else None, message_id)
    refs = save_references(message_id, chunks)
    return api_success(
        {
            "sessionId": session_id,
            "messageId": message_id,
            "answer": answer,
            "references": refs,
            "ragQuality": rag_quality,
            "retrievalRun": retrieval_run,
            "memoryActivity": memory_activity,
        }
    )


@router.post("/api/chat", tags=CHAT_TAGS, summary="Create a chat answer")
def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
    return run_chat(payload, request)


@router.post("/api/chat/stream", tags=CHAT_TAGS, summary="Stream a chat answer")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    if should_route_to_agent(payload):
        payload.useRag = (
            bool(payload.knowledgeBaseId)
            or payload.useRag
        )
        return agent_chat_stream(payload, request)
    queue: Queue[tuple[str, Any]] = Queue()
    cancelled = Event()

    def forward_model_event(event: dict[str, Any]) -> None:
        if cancelled.is_set():
            raise _ChatStreamCancelled()
        if event.get("type") == "text_delta" and event.get("text"):
            queue.put(
                (
                    "message",
                    {
                        "type": "answer",
                        "content": str(event["text"]),
                    },
                )
            )

    def worker() -> None:
        try:
            queue.put(
                (
                    "result",
                    run_chat(
                        payload,
                        request,
                        model_event_callback=forward_model_event,
                    )["data"],
                )
            )
        except _ChatStreamCancelled:
            queue.put(("cancelled", None))
        except Exception as exc:
            queue.put(("error", gateway._safe_error(exc)))

    Thread(target=worker, daemon=True).start()

    def generate() -> Iterable[str]:
        streamed_answer = False
        try:
            while True:
                try:
                    event_name, value = queue.get(timeout=0.25)
                except Empty:
                    yield ": keepalive\n\n"
                    continue
                if event_name == "message":
                    streamed_answer = True
                    yield sse_event("message", value)
                    continue
                if event_name == "cancelled":
                    return
                if event_name == "error":
                    yield sse_event(
                        "error",
                        {
                            "type": "error",
                            "code": "chat_stream_failed",
                            "message": str(value),
                        },
                    )
                    return
                result = value
                for call in result.get("toolCalls", []):
                    yield sse_event(
                        "tool",
                        {"type": "tool", **call},
                    )
                if not streamed_answer:
                    for i in range(0, len(result["answer"]), 12):
                        yield sse_event(
                            "message",
                            {
                                "type": "answer",
                                "content": result["answer"][i : i + 12],
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
                            "retrievalRun": result.get("retrievalRun"),
                        },
                    )
                yield sse_event(
                    "done",
                    {
                        "type": "done",
                        "sessionId": result["sessionId"],
                        "messageId": result["messageId"],
                        "memoryActivity": result.get("memoryActivity"),
                    },
                )
                return
        finally:
            cancelled.set()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/api/messages/{message_id}/references", tags=CHAT_TAGS, summary="Read answer references")
def read_message_references(message_id: int, request: Request) -> dict[str, Any]:
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
    rows = fetch_all(
        """
        SELECT mr.*, d.filename, dc.chunk_text
        FROM message_reference mr
        JOIN document d ON d.id = mr.document_id
        JOIN document_chunk dc ON dc.id = mr.chunk_id
        WHERE mr.message_id=:message_id
        ORDER BY mr.score DESC
        """,
        {"message_id": message_id},
    )
    return api_success(rows)


@router.get(
    "/api/messages/{message_id}/memory-activity",
    tags=CHAT_TAGS,
    summary="Read memory activity for an answer",
)
def read_message_memory_activity(
    message_id: int,
    request: Request,
) -> dict[str, Any]:
    activity = memory_operation_store.activity_for_message(
        user_id=current_user_id(request),
        message_id=message_id,
    )
    if activity is None:
        raise HTTPException(
            status_code=404,
            detail="Memory activity not found.",
        )
    return api_success(activity)


@router.get("/api/sessions", tags=SESSION_TAGS, summary="List chat sessions")
def list_sessions(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rows = fetch_all(
        """
        SELECT id, title, knowledge_base_id, chat_model_config_id, created_at, updated_at
        FROM chat_session
        WHERE user_id=:user_id
        ORDER BY updated_at DESC
        """,
        {"user_id": user_id},
    )
    latest_runs = _latest_session_runs(user_id)
    for row in rows:
        row["latest_run"] = latest_runs.get(str(row["id"]))
    return api_success(rows)


@router.get("/api/sessions/{session_id}/messages", tags=SESSION_TAGS, summary="Read session messages")
def read_session_messages(session_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_session_for_user(session_id, user_id)
    rows = fetch_all(
        """
        SELECT *
        FROM chat_message
        WHERE session_id=:session_id
        ORDER BY id ASC
        """,
        {"session_id": session_id},
    )
    assistant_ids = [
        int(row["id"])
        for row in rows
        if row["role"] == "assistant"
    ]
    memory_activities = memory_operation_store.activity_map_for_messages(
        user_id=user_id,
        message_ids=assistant_ids,
    )
    messages = []
    for row in rows:
        message = normalize_chat_message(row)
        run_row = (
            fetch_one(
                """
                SELECT id
                FROM agent_run
                WHERE assistant_message_id=:message_id
                  AND user_id=:user_id
                ORDER BY created_at DESC
                LIMIT 1
                """,
                {
                    "message_id": row["id"],
                    "user_id": user_id,
                },
            )
            if row["role"] == "assistant"
            else None
        )
        message["run"] = (
            agent_runs.get_snapshot(user_id, run_row["id"])
            if run_row
            else None
        )
        if message["run"] is not None:
            message["run"].update(
                agent_run_events.metadata_for_run(
                    user_id, str(run_row["id"])
                )
            )
            message["approvals"] = agent_tool_operations.get_for_run(
                user_id,
                str(run_row["id"]),
                statuses={"waiting"},
            )
            pending_question = message["run"].get("pendingQuestion")
            message["questions"] = (
                [pending_question]
                if isinstance(pending_question, dict)
                else []
            )
            message["toolCalls"] = list(
                message["run"].get("toolCalls") or []
            )
        else:
            message["approvals"] = []
            message["questions"] = []
            message["toolCalls"] = []
        message["memoryActivity"] = memory_activities.get(
            int(row["id"])
        )
        messages.append(message)
    return api_success(messages)


def _session_context_status(
    session_id: str,
    user_id: int,
) -> dict[str, Any]:
    session, _, messages = get_session_context_messages(session_id, user_id)
    count_row = fetch_one(
        "SELECT COUNT(*) AS total FROM chat_message WHERE session_id=:session_id",
        {"session_id": session_id},
    ) or {}
    metadata = session_context_metadata(session)
    status = context_status(
        messages,
        max_tokens=AGENT_CONTEXT_MAX_TOKENS,
    )
    status.update(
        {
            "compacted": bool(session.get("context_summary")),
            "compaction": metadata,
            "transcriptMessageCount": int(count_row.get("total") or 0),
        }
    )
    return status


@router.get(
    "/api/sessions/{session_id}/context",
    tags=SESSION_TAGS,
    summary="Read session context status",
)
def read_session_context(session_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    return api_success(_session_context_status(session_id, user_id))


@router.post(
    "/api/sessions/{session_id}/context/compact",
    tags=SESSION_TAGS,
    summary="Compact early session context",
)
def compact_session_context(
    session_id: str,
    payload: SessionContextCompactIn,
    request: Request,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    session, rows, messages = get_session_context_messages(session_id, user_id)
    active_run = agent_runs.get_open_run_for_session(user_id, session_id)
    if active_run is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_context_active",
                "message": "Wait for the current Agent run to finish before compacting context.",
                "data": None,
            },
        )
    chat_config = get_model_config(
        session.get("chat_model_config_id"),
        "chat",
        user_id,
    )
    if chat_config is None or not cipher.decrypt(chat_config.get("api_key_cipher")):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_context_model_required",
                "message": "Select an available chat model for this session before compacting context.",
                "data": None,
            },
        )
    try:
        result = compact_context(
            messages,
            gateway=gateway,
            config=chat_config,
            max_tokens=AGENT_CONTEXT_MAX_TOKENS,
            custom_instructions=payload.instructions,
            reason="manual",
        )
    except ContextCompactionError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "session_context_compaction_failed",
                "message": "Context compaction failed; the original conversation is unchanged.",
                "data": None,
            },
        ) from exc
    if not result.compacted:
        return api_success(
            {
                "compacted": False,
                "reason": result.reason,
                "metadata": {},
                "status": _session_context_status(session_id, user_id),
            }
        )
    summary_message = next(
        (
            item for item in result.messages
            if item.get("role") == "system"
            and SUMMARY_MARKER in str(item.get("content") or "")
        ),
        None,
    )
    if summary_message is None:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "session_context_summary_missing",
                "message": "The compaction result did not contain a restorable summary; the original conversation is unchanged.",
                "data": None,
            },
        )
    recent_ids = {
        int(item["id"])
        for item in result.messages
        if item.get("id") is not None
    }
    compacted_row_ids = [
        int(row["id"]) for row in rows if int(row["id"]) not in recent_ids
    ]
    if not compacted_row_ids:
        raise HTTPException(
            status_code=500,
            detail={
                "code": "session_context_boundary_missing",
                "message": "A safe compaction boundary could not be determined; the original conversation is unchanged.",
                "data": None,
            },
        )
    boundary = max(compacted_row_ids)
    metadata = {
        **result.metadata,
        "boundaryMessageId": boundary,
    }
    execute(
        """
        UPDATE chat_session
        SET context_summary=:summary,
            context_summary_metadata_json=:metadata,
            context_summary_up_to_message_id=:boundary,
            updated_at=:updated_at
        WHERE id=:session_id AND user_id=:user_id
        """,
        {
            "summary": str(summary_message.get("content") or ""),
            "metadata": json.dumps(metadata, ensure_ascii=False),
            "boundary": boundary,
            "updated_at": now_str(),
            "session_id": session_id,
            "user_id": user_id,
        },
    )
    return api_success(
        {
            "compacted": True,
            "reason": result.reason,
            "metadata": metadata,
            "status": _session_context_status(session_id, user_id),
        }
    )


@router.post(
    "/api/sessions/{session_id}/branch",
    tags=SESSION_TAGS,
    summary="Branch a chat session",
)
def branch_session(
    session_id: str,
    payload: SessionBranchIn,
    request: Request,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    source = get_session_for_user(session_id, user_id)
    active_run = fetch_one(
        """
        SELECT id
        FROM agent_run
        WHERE session_id=:session_id AND user_id=:user_id
          AND status IN (
            'planning', 'waiting_start', 'running',
            'waiting_approval', 'waiting_input'
          )
        LIMIT 1
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    if active_run:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_branch_active",
                "message": "Wait for the active Agent run to finish before branching.",
                "data": None,
            },
        )
    existing_titles = fetch_all(
        "SELECT title FROM chat_session WHERE user_id=:user_id",
        {"user_id": user_id},
    )
    title = unique_branch_title(
        str(source.get("title") or "New session"),
        [str(row.get("title") or "") for row in existing_titles],
        str(payload.title or ""),
    )
    new_session_id = f"session-{uuid.uuid4().hex[:16]}"
    created_at = now_str()
    source_messages = fetch_all(
        """
        SELECT * FROM chat_message
        WHERE session_id=:session_id
        ORDER BY id ASC
        """,
        {"session_id": session_id},
    )
    restored_question = ""
    if payload.beforeMessageId is not None:
        branch_point = next(
            (
                message
                for message in source_messages
                if int(message["id"]) == payload.beforeMessageId
            ),
            None,
        )
        if branch_point is None or branch_point.get("role") != "user":
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "session_branch_point_not_found",
                    "message": "The selected user message is not in this session.",
                    "data": None,
                },
            )
        restored_question = str(branch_point.get("content") or "")
        source_messages = [
            message
            for message in source_messages
            if int(message["id"]) < payload.beforeMessageId
        ]
    source_context_boundary = int(
        source.get("context_summary_up_to_message_id") or 0
    )
    inherit_context = bool(
        source.get("context_summary")
        and source_context_boundary
        and (
            payload.beforeMessageId is None
            or payload.beforeMessageId > source_context_boundary
        )
        and any(
            int(message["id"]) == source_context_boundary
            for message in source_messages
        )
    )
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO chat_session (
                  id, user_id, title, knowledge_base_id,
                  chat_model_config_id, context_summary,
                  context_summary_metadata_json,
                  context_summary_up_to_message_id,
                  created_at, updated_at
                ) VALUES (
                  :id, :user_id, :title, :knowledge_base_id,
                  :chat_model_config_id, :context_summary,
                  :context_summary_metadata_json, NULL,
                  :created_at, :updated_at
                )
                """
            ),
            {
                "id": new_session_id,
                "user_id": user_id,
                "title": title,
                "knowledge_base_id": source.get("knowledge_base_id"),
                "chat_model_config_id": source.get("chat_model_config_id"),
                "context_summary": (
                    source.get("context_summary") if inherit_context else None
                ),
                "context_summary_metadata_json": (
                    source.get("context_summary_metadata_json")
                    if inherit_context
                    else None
                ),
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        message_id_map: dict[int, int] = {}
        for message in source_messages:
            inserted = conn.execute(
                text(
                    """
                    INSERT INTO chat_message (
                      session_id, role, content, trace_json, skill_id,
                      skill_slug, skill_version, skill_content_hash, created_at
                    ) VALUES (
                      :session_id, :role, :content, :trace_json, :skill_id,
                      :skill_slug, :skill_version, :skill_content_hash, :created_at
                    )
                    """
                ),
                {
                    "session_id": new_session_id,
                    "role": message.get("role"),
                    "content": message.get("content"),
                    "trace_json": message.get("trace_json"),
                    "skill_id": message.get("skill_id"),
                    "skill_slug": message.get("skill_slug"),
                    "skill_version": message.get("skill_version"),
                    "skill_content_hash": message.get("skill_content_hash"),
                    "created_at": message.get("created_at") or created_at,
                },
            )
            message_id_map[int(message["id"])] = int(inserted.lastrowid)
        if inherit_context:
            conn.execute(
                text(
                    """
                    UPDATE chat_session
                    SET context_summary_up_to_message_id=:boundary
                    WHERE id=:session_id
                    """
                ),
                {
                    "boundary": message_id_map[source_context_boundary],
                    "session_id": new_session_id,
                },
            )
        for old_id, new_id in message_id_map.items():
            references = conn.execute(
                text(
                    """
                    SELECT document_id, chunk_id, score, created_at
                    FROM message_reference WHERE message_id=:message_id
                    """
                ),
                {"message_id": old_id},
            ).mappings().all()
            for reference in references:
                conn.execute(
                    text(
                        """
                        INSERT INTO message_reference (
                          message_id, document_id, chunk_id, score, created_at
                        ) VALUES (
                          :message_id, :document_id, :chunk_id, :score, :created_at
                        )
                        """
                    ),
                    {
                        "message_id": new_id,
                        "document_id": reference["document_id"],
                        "chunk_id": reference["chunk_id"],
                        "score": reference["score"],
                        "created_at": reference["created_at"] or created_at,
                    },
                )
    return api_success(
        {
            "id": new_session_id,
            "title": title,
            "knowledge_base_id": source.get("knowledge_base_id"),
            "chat_model_config_id": source.get("chat_model_config_id"),
            "created_at": created_at,
            "updated_at": created_at,
            "sourceSessionId": session_id,
            "messageCount": len(source_messages),
            "restoredQuestion": restored_question,
            "rewindMessageId": payload.beforeMessageId,
        }
    )


@router.get(
    "/api/sessions/{session_id}/export",
    tags=SESSION_TAGS,
    summary="Export a chat session",
)
def export_session(session_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    session = get_session_for_user(session_id, user_id)
    messages = fetch_all(
        """
        SELECT role, content FROM chat_message
        WHERE session_id=:session_id
        ORDER BY id ASC
        """,
        {"session_id": session_id},
    )
    title = str(session.get("title") or "AgentLens session")
    return api_success(
        {
            "filename": safe_export_filename(title),
            "content": render_session_markdown(title, messages),
            "messageCount": sum(
                1 for message in messages
                if message.get("role") in {"user", "assistant"}
                and str(message.get("content") or "").strip()
            ),
        }
    )


@router.put("/api/sessions/{session_id}", tags=SESSION_TAGS, summary="Rename a session")
def rename_session(session_id: str, payload: SessionUpdate, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_session_for_user(session_id, user_id)
    execute("UPDATE chat_session SET title=:title, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"title": payload.title, "updated_at": now_str(), "id": session_id, "user_id": user_id})
    return api_success(True)


@router.delete("/api/sessions/{session_id}", tags=SESSION_TAGS, summary="Delete a session")
def delete_session(session_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_session_for_user(session_id, user_id)
    run_rows = fetch_all(
        """
        SELECT id, status
        FROM agent_run
        WHERE session_id=:session_id AND user_id=:user_id
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    busy_run_ids: list[str] = []
    active_statuses = {
        "planning",
        "waiting_start",
        "running",
        "waiting_approval",
        "waiting_input",
    }
    for run_row in run_rows:
        managed_run = agent_run_coordinator.is_active(run_row["id"])
        if run_row.get("status") in active_statuses and not managed_run:
            busy_run_ids.append(str(run_row["id"]))
            continue
        if not agent_run_coordinator.cancel_and_wait(
            run_row["id"],
            timeout_seconds=5.0,
        ):
            busy_run_ids.append(str(run_row["id"]))
    if busy_run_ids:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "agent_run_still_active",
                "message": (
                    "An Agent run is still active. Retry session deletion shortly."
                ),
                "data": None,
            },
        )
    try:
        langgraph_checkpoints.delete_threads(
            user_id,
            [str(run_row["id"]) for run_row in run_rows]
        )
    except LangGraphCheckpointError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": exc.code,
                "message": exc.message,
                "data": None,
            },
        ) from exc
    execute(
        """
        DELETE FROM agent_tool_operation
        WHERE run_id IN (
          SELECT id FROM agent_run
          WHERE session_id=:session_id AND user_id=:user_id
        )
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    execute(
        """
        DELETE FROM agent_run_event
        WHERE run_id IN (
          SELECT id FROM agent_run
          WHERE session_id=:session_id AND user_id=:user_id
        )
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    execute(
        """
        DELETE FROM agent_run_step
        WHERE run_id IN (
          SELECT id FROM agent_run
          WHERE session_id=:session_id AND user_id=:user_id
        )
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    execute(
        """
        DELETE FROM agent_run
        WHERE session_id=:session_id AND user_id=:user_id
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    execute("DELETE FROM agent_tool_call WHERE session_id=:session_id", {"session_id": session_id})
    execute(
        """
        DELETE FROM memory_operation
        WHERE session_id=:session_id AND user_id=:user_id
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    execute("DELETE FROM message_reference WHERE message_id IN (SELECT id FROM chat_message WHERE session_id=:session_id)", {"session_id": session_id})
    execute("DELETE FROM chat_message WHERE session_id=:session_id", {"session_id": session_id})
    execute("DELETE FROM chat_session WHERE id=:session_id", {"session_id": session_id})
    return api_success(True)
