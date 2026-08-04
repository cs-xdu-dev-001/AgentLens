from queue import Empty, Queue
from threading import Event, Thread

from fastapi import APIRouter

from ..runtime import *
from .extensions import agent_chat, agent_chat_stream

router = APIRouter()

CHAT_TAGS = ["Chat"]
SESSION_TAGS = ["Sessions"]


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
        message["memoryActivity"] = memory_activities.get(
            int(row["id"])
        )
        messages.append(message)
    return api_success(messages)


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
