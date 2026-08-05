from fastapi import APIRouter
from sqlalchemy import text

from ..runtime import *

router = APIRouter()

KNOWLEDGE_TAGS = ["Knowledge Bases"]
DOCUMENT_TAGS = ["Documents"]
RAG_TAGS = ["RAG Debug"]


def normalize_knowledge_base(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description"),
        "embedding_model_config_id": row["embedding_model_config_id"],
        "document_count": row.get("document_count") or 0,
        "chunk_count": row.get("chunk_count") or 0,
        "status": row.get("status") or "active",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


@router.post("/api/knowledge-bases", tags=KNOWLEDGE_TAGS, summary="Create a knowledge base")
def create_knowledge_base(payload: KnowledgeBaseIn, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_model_config(payload.embeddingModelConfigId, "embedding", user_id)
    kb_id = execute(
        """
        INSERT INTO knowledge_base(user_id, name, description, embedding_model_config_id, created_at, updated_at)
        VALUES (:user_id, :name, :description, :embedding_model_config_id, :created_at, :updated_at)
        """,
        {
            "user_id": user_id,
            "name": payload.name,
            "description": payload.description,
            "embedding_model_config_id": payload.embeddingModelConfigId,
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    return api_success(normalize_knowledge_base(get_kb(int(kb_id or 0), user_id)))


@router.get("/api/knowledge-bases", tags=KNOWLEDGE_TAGS, summary="List knowledge bases")
def list_knowledge_bases(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    rows = fetch_all("SELECT * FROM knowledge_base WHERE user_id=:user_id ORDER BY id DESC", {"user_id": user_id})
    return api_success([normalize_knowledge_base(row) for row in rows])


@router.get("/api/knowledge-bases/{kb_id}", tags=KNOWLEDGE_TAGS, summary="Read a knowledge base")
def read_knowledge_base(kb_id: int, request: Request) -> dict[str, Any]:
    return api_success(normalize_knowledge_base(get_kb(kb_id, current_user_id(request))))


@router.put("/api/knowledge-bases/{kb_id}", tags=KNOWLEDGE_TAGS, summary="Update a knowledge base")
def update_knowledge_base(kb_id: int, payload: KnowledgeBaseUpdate, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_kb(kb_id, user_id)
    if payload.name is not None:
        execute("UPDATE knowledge_base SET name=:name, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"name": payload.name, "updated_at": now_str(), "id": kb_id, "user_id": user_id})
    if payload.description is not None:
        execute("UPDATE knowledge_base SET description=:description, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"description": payload.description, "updated_at": now_str(), "id": kb_id, "user_id": user_id})
    return api_success(normalize_knowledge_base(get_kb(kb_id, user_id)))


@router.delete("/api/knowledge-bases/{kb_id}", tags=KNOWLEDGE_TAGS, summary="Delete a knowledge base")
def delete_knowledge_base(kb_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_kb(kb_id, user_id)
    documents = fetch_all(
        "SELECT storage_path FROM document WHERE knowledge_base_id=:id AND user_id=:user_id",
        {"id": kb_id, "user_id": user_id},
    )
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM message_reference WHERE document_id IN (SELECT id FROM document WHERE knowledge_base_id=:id AND user_id=:user_id)"), {"id": kb_id, "user_id": user_id})
        conn.execute(text("DELETE FROM retrieval_run WHERE knowledge_base_id=:id AND user_id=:user_id"), {"id": kb_id, "user_id": user_id})
        conn.execute(text("DELETE FROM document_task WHERE knowledge_base_id=:id AND user_id=:user_id"), {"id": kb_id, "user_id": user_id})
        conn.execute(text("DELETE FROM document_chunk WHERE knowledge_base_id=:id"), {"id": kb_id})
        conn.execute(text("DELETE FROM document WHERE knowledge_base_id=:id AND user_id=:user_id"), {"id": kb_id, "user_id": user_id})
        conn.execute(text("DELETE FROM knowledge_base WHERE id=:id AND user_id=:user_id"), {"id": kb_id, "user_id": user_id})
    cleanup_document_source_files(documents)
    return api_success(True)


def normalize_document_task(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "documentId": row["document_id"],
        "knowledgeBaseId": row["knowledge_base_id"],
        "taskType": row["task_type"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "retryCount": row["retry_count"],
        "errorMessage": row.get("error_message"),
        "startedAt": row.get("started_at"),
        "finishedAt": row.get("finished_at"),
        "createdAt": row.get("created_at"),
        "updatedAt": row.get("updated_at"),
    }


def create_document_task(user_id: int, document_id: int, knowledge_base_id: int, task_type: str) -> int:
    previous = scalar(
        "SELECT COUNT(*) FROM document_task WHERE document_id=:document_id AND task_type=:task_type",
        {"document_id": document_id, "task_type": task_type},
    )
    task_id = execute(
        """
        INSERT INTO document_task(
          user_id, document_id, knowledge_base_id, task_type, status, stage,
          progress, retry_count, created_at, updated_at
        )
        VALUES (
          :user_id, :document_id, :knowledge_base_id, :task_type, 'pending', 'uploading',
          5, :retry_count, :created_at, :updated_at
        )
        """,
        {
            "user_id": user_id,
            "document_id": document_id,
            "knowledge_base_id": knowledge_base_id,
            "task_type": task_type,
            "retry_count": int(previous or 0),
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    return int(task_id or 0)


def update_document_task(
    task_id: int,
    *,
    status: str | None = None,
    stage: str | None = None,
    progress: int | None = None,
    error_message: str | None = None,
    started: bool = False,
    finished: bool = False,
) -> None:
    assignments = ["updated_at=:updated_at"]
    params: dict[str, Any] = {"id": task_id, "updated_at": now_str()}
    if status is not None:
        assignments.append("status=:status")
        params["status"] = status
    if stage is not None:
        assignments.append("stage=:stage")
        params["stage"] = stage
    if progress is not None:
        assignments.append("progress=:progress")
        params["progress"] = max(0, min(100, int(progress)))
    if error_message is not None:
        assignments.append("error_message=:error_message")
        params["error_message"] = error_message
    if started:
        assignments.append("started_at=:started_at")
        params["started_at"] = now_str()
    if finished:
        assignments.append("finished_at=:finished_at")
        params["finished_at"] = now_str()
    execute(f"UPDATE document_task SET {', '.join(assignments)} WHERE id=:id", params)


def get_latest_document_task(document_id: int, user_id: int | None = None) -> dict[str, Any] | None:
    if user_id is None:
        row = fetch_one("SELECT * FROM document_task WHERE document_id=:document_id ORDER BY id DESC LIMIT 1", {"document_id": document_id})
    else:
        row = fetch_one(
            "SELECT * FROM document_task WHERE document_id=:document_id AND user_id=:user_id ORDER BY id DESC LIMIT 1",
            {"document_id": document_id, "user_id": user_id},
        )
    return normalize_document_task(row)


def normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document["id"],
        "knowledge_base_id": document["knowledge_base_id"],
        "filename": document["filename"],
        "file_type": document.get("file_type"),
        "file_size": document.get("file_size") or 0,
        "parse_status": document.get("parse_status") or "pending",
        "chunk_count": document.get("chunk_count") or 0,
        "error_message": document.get("error_message"),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
    }


def attach_latest_task(document: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
    item = normalize_document(document)
    item["latestTask"] = get_latest_document_task(int(item["id"]), user_id)
    return item


def refresh_kb_counts(kb_id: int) -> None:
    execute(
        """
        UPDATE knowledge_base
        SET document_count=(SELECT COUNT(*) FROM document WHERE knowledge_base_id=:id),
            chunk_count=(SELECT COUNT(*) FROM document_chunk WHERE knowledge_base_id=:id),
            updated_at=:updated_at
        WHERE id=:id
        """,
        {"id": kb_id, "updated_at": now_str()},
    )


def remove_document_source_file(document: dict[str, Any]) -> None:
    raw_path = str(document.get("storage_path") or "").strip()
    if not raw_path:
        return
    upload_root = UPLOAD_DIR.resolve()
    storage_path = Path(raw_path).resolve()
    if storage_path != upload_root and upload_root not in storage_path.parents:
        raise RuntimeError("Refusing to delete a document source outside the upload directory.")
    storage_path.unlink(missing_ok=True)


def cleanup_document_source_files(documents: list[dict[str, Any]]) -> None:
    for document in documents:
        try:
            remove_document_source_file(document)
        except Exception:
            pass


def process_document_ingestion(document_id: int, task_id: int | None = None) -> None:
    document = fetch_one("SELECT * FROM document WHERE id=:id", {"id": document_id})
    if not document:
        return

    kb_id = int(document["knowledge_base_id"])
    user_id = int(document.get("user_id") or 0)
    try:
        if task_id:
            update_document_task(task_id, status="running", stage="parsing", progress=20, started=True)
        execute(
            """
            UPDATE document
            SET parse_status='parsing', chunk_count=0, error_message=NULL, updated_at=:updated_at
            WHERE id=:id
            """,
            {"updated_at": now_str(), "id": document_id},
        )

        path = Path(document["storage_path"])
        if not path.exists():
            raise FileNotFoundError("Original file is missing, so the document cannot be reingested.")

        data = path.read_bytes()
        text_value = extract_text_from_upload(document["filename"], data)
        chunks = split_text(text_value)
        if not chunks:
            raise ValueError("No valid text was extracted from this document.")

        if task_id:
            update_document_task(task_id, stage="chunking", progress=55)
        execute(
            "UPDATE document SET parse_status='chunking', updated_at=:updated_at WHERE id=:id",
            {"updated_at": now_str(), "id": document_id},
        )
        vector_store.delete_document(document_id)
        execute("DELETE FROM document_chunk WHERE document_id=:document_id", {"document_id": document_id})

        created_chunks: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            vector_id = f"kb-{kb_id}-doc-{document_id}-chunk-{index}"
            chunk_id = execute(
                """
                INSERT INTO document_chunk(
                  knowledge_base_id, document_id, chunk_index, chunk_text,
                  vector_id, token_count, created_at
                )
                VALUES (
                  :knowledge_base_id, :document_id, :chunk_index, :chunk_text,
                  :vector_id, :token_count, :created_at
                )
                """,
                {
                    "knowledge_base_id": kb_id,
                    "document_id": document_id,
                    "chunk_index": index,
                    "chunk_text": chunk,
                    "vector_id": vector_id,
                    "token_count": len(tokenize(chunk)),
                    "created_at": now_str(),
                },
            )
            created_chunks.append(
                {
                    "id": int(chunk_id or 0),
                    "knowledge_base_id": kb_id,
                    "document_id": document_id,
                    "chunk_text": chunk,
                    "vector_id": vector_id,
                    "filename": document["filename"],
                }
            )

        execute(
            "UPDATE document SET parse_status='embedding', chunk_count=:chunk_count, updated_at=:updated_at WHERE id=:id",
            {"chunk_count": len(chunks), "updated_at": now_str(), "id": document_id},
        )
        if task_id:
            update_document_task(task_id, stage="embedding", progress=85)
        vector_store.upsert_chunks(created_chunks, get_embedding_config_for_kb(kb_id, user_id or None))
        execute(
            "UPDATE document SET parse_status='success', updated_at=:updated_at WHERE id=:id",
            {"updated_at": now_str(), "id": document_id},
        )
        if task_id:
            update_document_task(task_id, status="success", stage="done", progress=100, finished=True)
    except Exception as exc:
        execute(
            "UPDATE document SET parse_status='failed', error_message=:error, updated_at=:updated_at WHERE id=:id",
            {"error": str(exc), "updated_at": now_str(), "id": document_id},
        )
        if task_id:
            update_document_task(task_id, status="failed", stage="failed", progress=100, error_message=str(exc), finished=True)
    finally:
        refresh_kb_counts(kb_id)


@router.post("/api/knowledge-bases/{knowledge_base_id}/documents", tags=DOCUMENT_TAGS, summary="Upload a document")
async def upload_document(knowledge_base_id: int, background_tasks: BackgroundTasks, request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_kb(knowledge_base_id, user_id)
    filename = sanitize_upload_filename(file.filename or "document.txt")
    data = await read_upload_file_with_limit(file)
    validate_upload_file(filename, data)
    file_md5 = hashlib.md5(data).hexdigest()
    existing = fetch_one(
        "SELECT * FROM document WHERE knowledge_base_id=:knowledge_base_id AND file_md5=:file_md5 AND user_id=:user_id",
        {"knowledge_base_id": knowledge_base_id, "file_md5": file_md5, "user_id": user_id},
    )
    if existing:
        existing = attach_latest_task(existing, user_id)
        return api_success(
            {
                "documentId": existing["id"],
                "filename": existing["filename"],
                "parseStatus": existing["parse_status"],
                "taskId": existing["latestTask"]["id"] if existing.get("latestTask") else None,
                "duplicated": True,
            },
            "Document already exists.",
        )
    storage_path = UPLOAD_DIR / f"{knowledge_base_id}_{file_md5}_{filename}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(data)
    document_id = execute(
        """
        INSERT INTO document(
          user_id, knowledge_base_id, filename, file_type, file_size, file_md5,
          storage_path, parse_status, created_at, updated_at
        )
        VALUES (
          :user_id, :knowledge_base_id, :filename, :file_type, :file_size, :file_md5,
          :storage_path, 'parsing', :created_at, :updated_at
        )
        """,
        {
            "user_id": user_id,
            "knowledge_base_id": knowledge_base_id,
            "filename": filename,
            "file_type": Path(filename).suffix.lower().lstrip("."),
            "file_size": len(data),
            "file_md5": file_md5,
            "storage_path": str(storage_path),
            "created_at": now_str(),
            "updated_at": now_str(),
        },
    )
    task_id = create_document_task(user_id, int(document_id or 0), knowledge_base_id, "ingest")
    background_tasks.add_task(process_document_ingestion, int(document_id or 0), task_id)
    refresh_kb_counts(knowledge_base_id)
    return api_success({"documentId": document_id, "taskId": task_id, "filename": filename, "parseStatus": "parsing", "chunkCount": 0})


@router.get("/api/knowledge-bases/{knowledge_base_id}/documents", tags=DOCUMENT_TAGS, summary="List documents in a knowledge base")
def list_documents(knowledge_base_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_kb(knowledge_base_id, user_id)
    rows = fetch_all("SELECT * FROM document WHERE knowledge_base_id=:knowledge_base_id AND user_id=:user_id ORDER BY id DESC", {"knowledge_base_id": knowledge_base_id, "user_id": user_id})
    return api_success([attach_latest_task(row, user_id) for row in rows])


@router.get("/api/documents/{document_id}", tags=DOCUMENT_TAGS, summary="Read document processing status")
def read_document(document_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    row = get_document_for_user(document_id, user_id)
    return api_success(attach_latest_task(row, user_id))


@router.get("/api/documents/{document_id}/tasks", tags=DOCUMENT_TAGS, summary="Read document background tasks")
def read_document_tasks(document_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_document_for_user(document_id, user_id)
    rows = fetch_all(
        "SELECT * FROM document_task WHERE document_id=:document_id AND user_id=:user_id ORDER BY id DESC",
        {"document_id": document_id, "user_id": user_id},
    )
    return api_success([normalize_document_task(row) for row in rows])


@router.get("/api/documents/{document_id}/chunks", tags=DOCUMENT_TAGS, summary="Read document chunks")
def read_document_chunks(document_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_document_for_user(document_id, user_id)
    rows = fetch_all("SELECT * FROM document_chunk WHERE document_id=:document_id ORDER BY chunk_index ASC", {"document_id": document_id})
    return api_success(rows)


@router.post("/api/documents/{document_id}/reindex", tags=DOCUMENT_TAGS, summary="Reindex a document")
def reindex_document(document_id: int, background_tasks: BackgroundTasks, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    document = get_document_for_user(document_id, user_id)
    path = Path(document["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original file not found.")
    execute(
        """
        UPDATE document
        SET parse_status='parsing', error_message=NULL, updated_at=:updated_at
        WHERE id=:id
        """,
        {"updated_at": now_str(), "id": document_id},
    )
    task_id = create_document_task(user_id, document_id, int(document["knowledge_base_id"]), "reindex")
    background_tasks.add_task(process_document_ingestion, document_id, task_id)
    return api_success({"documentId": document_id, "taskId": task_id, "parseStatus": "parsing", "chunkCount": int(document.get("chunk_count") or 0)})


@router.delete("/api/documents/{document_id}", tags=DOCUMENT_TAGS, summary="Delete a document")
def delete_document(document_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    document = get_document_for_user(document_id, user_id)
    kb_id = int(document["knowledge_base_id"])
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM message_reference WHERE document_id=:document_id"), {"document_id": document_id})
        conn.execute(text("DELETE FROM document_task WHERE document_id=:document_id AND user_id=:user_id"), {"document_id": document_id, "user_id": user_id})
        conn.execute(text("DELETE FROM document_chunk WHERE document_id=:document_id"), {"document_id": document_id})
        conn.execute(text("DELETE FROM document WHERE id=:document_id AND user_id=:user_id"), {"document_id": document_id, "user_id": user_id})
        conn.execute(
            text(
                """
                UPDATE knowledge_base
                SET document_count=(SELECT COUNT(*) FROM document WHERE knowledge_base_id=:id),
                    chunk_count=(SELECT COUNT(*) FROM document_chunk WHERE knowledge_base_id=:id),
                    updated_at=:updated_at
                WHERE id=:id
                """
            ),
            {"id": kb_id, "updated_at": now_str()},
        )
    vector_store.delete_document(document_id)
    cleanup_document_source_files([document])
    return api_success(True)


@router.post("/api/retrieval/debug", tags=RAG_TAGS, summary="Debug RAG retrieval")
def retrieval_debug(payload: RetrievalDebugRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    get_kb(payload.knowledgeBaseId, user_id)
    started_at = time.perf_counter()
    chunks = retrieve_chunks(payload.knowledgeBaseId, payload.query, payload.topK, user_id)
    chunks = enrich_retrieval_chunks(payload.query, chunks)
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    quality = assess_retrieval_quality(payload.query, chunks)
    retrieval_run = record_retrieval_run(
        user_id=user_id,
        knowledge_base_id=payload.knowledgeBaseId,
        query=payload.query,
        top_k=payload.topK,
        chunks=chunks,
        quality=quality,
        duration_ms=duration_ms,
    )
    return api_success(
        {
            "query": payload.query,
            "topK": payload.topK,
            "vectorBackend": vector_store.backend,
            "quality": quality,
            "retrievalRun": retrieval_run,
            "chunks": [
                {
                    "rank": item["rank"],
                    "chunkId": item["chunk_id"],
                    "documentId": item["document_id"],
                    "filename": item["filename"],
                    "score": item["score"],
                    "matchedTerms": item["matchedTerms"],
                    "content": item["chunk_text"],
                }
                for item in chunks
            ],
        }
    )


@router.get("/api/retrieval/runs/{run_id}", tags=RAG_TAGS, summary="Read a RAG retrieval run")
def read_retrieval_run(run_id: int, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    row = fetch_one("SELECT * FROM retrieval_run WHERE id=:id AND user_id=:user_id", {"id": run_id, "user_id": user_id})
    if not row:
        raise HTTPException(status_code=404, detail="Retrieval run not found.")
    return api_success(normalize_retrieval_run(row))
