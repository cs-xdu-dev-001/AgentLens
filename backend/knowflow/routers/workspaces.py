from __future__ import annotations

from pathlib import Path
import shutil
import sys

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from ..responses import api_success
from ..runtime import (
    SANDBOX_COMMAND,
    SANDBOX_ENABLED,
    SANDBOX_LIMIT_COMMAND,
    SANDBOX_SHELL,
    WORKSPACE_DIR,
    WORKSPACE_ENABLED,
    WORKSPACE_MAX_FILE_BYTES,
    agent_run_events,
    agent_runs,
    current_user_id,
)
from ..services.agent_event_protocol import normalize_agent_event
from ..services.agent_trace import sanitize_trace_value
from ..services.workspace_runtime import (
    WorkspaceContext,
    WorkspaceRuntime,
    WorkspaceRuntimeError,
    tracked_workspace_runtime,
)


router = APIRouter()
WORKSPACE_TAGS = ["Workspace"]


class WorkspaceUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runId: str = Field(min_length=1, max_length=200)
    operationId: str = Field(min_length=1, max_length=200)


def _runtime(request: Request) -> WorkspaceRuntime:
    if not WORKSPACE_ENABLED:
        raise HTTPException(status_code=409, detail="Workspace功能尚未启用。")
    return WorkspaceRuntime(
        WORKSPACE_DIR,
        user_id=current_user_id(request),
        max_file_bytes=WORKSPACE_MAX_FILE_BYTES,
    )


def _tracked_runtime(user_id: int, run_id: str | None = None) -> WorkspaceRuntime:
    if not WORKSPACE_ENABLED:
        raise HTTPException(status_code=409, detail="Workspace功能尚未启用。")
    return tracked_workspace_runtime(
        WORKSPACE_DIR,
        user_id=user_id,
        max_file_bytes=WORKSPACE_MAX_FILE_BYTES,
        run_id=run_id,
    )


def _owned_run(user_id: int, run_id: str) -> dict:
    snapshot = agent_runs.get_snapshot(user_id, run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent运行不存在。")
    return snapshot


def _raise_workspace_error(exc: WorkspaceRuntimeError) -> None:
    status = (
        404
        if exc.code.endswith("missing")
        else 409
        if exc.code in {"workspace_undo_conflict", "workspace_undo_empty"}
        else 400
    )
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/api/workspace", tags=WORKSPACE_TAGS)
def workspace_status(request: Request) -> dict:
    user_id = current_user_id(request)
    sandbox_ready = bool(
        SANDBOX_ENABLED
        and sys.platform.startswith("linux")
        and (shutil.which(SANDBOX_COMMAND) or Path(SANDBOX_COMMAND).is_file())
        and (shutil.which(SANDBOX_SHELL) or Path(SANDBOX_SHELL).is_file())
        and (
            shutil.which(SANDBOX_LIMIT_COMMAND)
            or Path(SANDBOX_LIMIT_COMMAND).is_file()
        )
    )
    item_count = 0
    project_instructions = {"count": 0, "sources": [], "truncated": False}
    git_status: dict = {"repository": False, "clean": True}
    if WORKSPACE_ENABLED:
        runtime = WorkspaceRuntime(
            WORKSPACE_DIR,
            user_id=user_id,
            max_file_bytes=WORKSPACE_MAX_FILE_BYTES,
        )
        item_count = len(runtime.list_entries("").get("entries", []))
        context_status = WorkspaceContext(runtime.root).status()
        project_instructions = context_status["projectInstructions"]
        git_status = context_status["git"]
    return api_success(
        {
            "enabled": WORKSPACE_ENABLED,
            "sandboxEnabled": SANDBOX_ENABLED,
            "sandboxReady": sandbox_ready,
            "platform": "linux" if sys.platform.startswith("linux") else "unsupported",
            "maxFileBytes": WORKSPACE_MAX_FILE_BYTES,
            "itemCount": item_count,
            "isolation": "user",
            "protectedPatterns": [".git", ".env*", ".ssh", ".tmp"],
            "symlinkWriteProtected": True,
            "projectInstructions": project_instructions,
            "git": git_status,
        }
    )


@router.get("/api/workspace/changes", tags=WORKSPACE_TAGS)
def read_workspace_changes(
    request: Request,
    run_id: str,
    path: str | None = None,
) -> dict:
    user_id = current_user_id(request)
    _owned_run(user_id, run_id)
    try:
        result = _tracked_runtime(user_id, run_id).context.diff(
            path or None,
            run_id=run_id,
        )
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)
    result["patch"] = sanitize_trace_value(
        result.get("patch") or "",
        max_chars=100_000,
    ) or ""
    return api_success(result)


@router.post("/api/workspace/changes/undo", tags=WORKSPACE_TAGS)
def undo_workspace_change(
    payload: WorkspaceUndoRequest,
    request: Request,
) -> dict:
    user_id = current_user_id(request)
    snapshot = _owned_run(user_id, payload.runId)
    if snapshot.get("status") not in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Agent仍在运行，结束后才能撤销变更。")
    try:
        result = _tracked_runtime(user_id, payload.runId).context.undo_file(
            operation_id=payload.operationId,
            run_id=payload.runId,
        )
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)
    artifact_id = f"file:{result.get('path') or ''}"
    existing = next(
        (
            item
            for item in agent_run_events.artifacts_for_run(user_id, payload.runId)
            if item.get("artifactId") == artifact_id
        ),
        {},
    )
    existing_artifact = {
        key: existing[key]
        for key in (
            "operation",
            "sourceTool",
            "toolCallId",
            "writtenBytes",
            "addedLines",
            "removedLines",
            "diffAvailable",
        )
        if existing.get(key) is not None
    }
    event = normalize_agent_event(
        {
            **existing_artifact,
            "type": "artifact_updated",
            "artifactId": artifact_id,
            "artifactType": "file",
            "title": result.get("path"),
            "path": result.get("path"),
            "operationId": result.get("operationId"),
            "reverted": True,
            "changeStatus": "reverted",
        },
        run_id=payload.runId,
        sequence=agent_run_events.latest_sequence(payload.runId) + 1,
    )
    agent_run_events.append(payload.runId, event)
    return api_success({**result, "artifact": event})


@router.get("/api/workspace/files", tags=WORKSPACE_TAGS)
def list_workspace_files(request: Request, path: str = "") -> dict:
    try:
        return api_success(_runtime(request).list_entries(path))
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)


@router.get("/api/workspace/mentions", tags=WORKSPACE_TAGS)
def list_workspace_mentions(request: Request) -> dict:
    return api_success(_runtime(request).mention_paths())


@router.post("/api/workspace/files", tags=WORKSPACE_TAGS)
async def upload_workspace_file(
    request: Request,
    path: str = Form(...),
    overwrite: bool = Form(False),
    file: UploadFile = File(...),
) -> dict:
    content = await file.read(WORKSPACE_MAX_FILE_BYTES + 1)
    try:
        return api_success(
            _runtime(request).write_bytes(
                path,
                content,
                overwrite=overwrite,
            )
        )
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)


@router.get("/api/workspace/files/{path:path}", tags=WORKSPACE_TAGS)
def download_workspace_file(path: str, request: Request) -> FileResponse:
    try:
        target = _runtime(request).file_path(path)
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)
    return FileResponse(target, filename=target.name)


@router.delete("/api/workspace/files/{path:path}", tags=WORKSPACE_TAGS)
def delete_workspace_file(path: str, request: Request) -> dict:
    try:
        _runtime(request).delete_file(path)
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)
    return api_success(True)
