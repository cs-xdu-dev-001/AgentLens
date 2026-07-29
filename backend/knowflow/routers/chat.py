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


@router.post("/api/chat", tags=CHAT_TAGS, summary="Create a chat answer")
def chat(payload: ChatRequest, request: Request) -> dict[str, Any]:
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
    memories = memory_manager.recall(user_id, payload.question)
    chat_config = get_model_config(payload.chatModelConfigId, "chat", user_id)
    answer = generate_answer(
        payload.question,
        chunks,
        history,
        chat_config,
        use_rag=use_rag,
        attachments=payload.attachments,
        memories=memories,
    )
    message_id = save_message(session_id, "assistant", answer)
    memory_manager.remember_async(
        user_id=user_id,
        session_id=session_id,
        message_id=message_id,
        question=payload.question,
        answer=answer,
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
        }
    )


@router.post("/api/chat/stream", tags=CHAT_TAGS, summary="Stream a chat answer")
def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    if should_route_to_agent(payload):
        payload.useRag = (
            bool(payload.knowledgeBaseId)
            or payload.useRag
        )
        return agent_chat_stream(payload, request)
    result = chat(payload, request)["data"]

    def generate() -> Iterable[str]:
        for call in result.get("toolCalls", []):
            yield sse_event("tool", {"type": "tool", **call})
        for i in range(0, len(result["answer"]), 12):
            yield sse_event("message", {"type": "answer", "content": result["answer"][i : i + 12]})
            time.sleep(0.02)
        for ref in result["references"]:
            yield sse_event("reference", {"type": "reference", **ref})
        if result.get("ragQuality", {}).get("enabled"):
            yield sse_event("quality", {"type": "quality", "ragQuality": result["ragQuality"], "retrievalRun": result.get("retrievalRun")})
        yield sse_event("done", {"type": "done", "sessionId": result["sessionId"], "messageId": result["messageId"]})

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
        SELECT id
        FROM agent_run
        WHERE session_id=:session_id AND user_id=:user_id
        """,
        {"session_id": session_id, "user_id": user_id},
    )
    for run_row in run_rows:
        approval_broker.cancel_run(run_row["id"])
        agent_run_coordinator.cancel(run_row["id"])
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
    execute("DELETE FROM message_reference WHERE message_id IN (SELECT id FROM chat_message WHERE session_id=:session_id)", {"session_id": session_id})
    execute("DELETE FROM chat_message WHERE session_id=:session_id", {"session_id": session_id})
    execute("DELETE FROM chat_session WHERE id=:session_id", {"session_id": session_id})
    return api_success(True)
