from __future__ import annotations

from pathlib import Path
import shutil
import sys

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..responses import api_success
from ..runtime import (
    SANDBOX_COMMAND,
    SANDBOX_ENABLED,
    SANDBOX_LIMIT_COMMAND,
    SANDBOX_SHELL,
    WORKSPACE_DIR,
    WORKSPACE_ENABLED,
    WORKSPACE_MAX_FILE_BYTES,
    current_user_id,
)
from ..services.workspace_runtime import WorkspaceRuntime, WorkspaceRuntimeError


router = APIRouter()
WORKSPACE_TAGS = ["Workspace"]


def _runtime(request: Request) -> WorkspaceRuntime:
    if not WORKSPACE_ENABLED:
        raise HTTPException(status_code=409, detail="Workspace功能尚未启用。")
    return WorkspaceRuntime(
        WORKSPACE_DIR,
        user_id=current_user_id(request),
        max_file_bytes=WORKSPACE_MAX_FILE_BYTES,
    )


def _raise_workspace_error(exc: WorkspaceRuntimeError) -> None:
    status = 404 if exc.code.endswith("missing") else 400
    raise HTTPException(
        status_code=status,
        detail={"code": exc.code, "message": str(exc)},
    ) from exc


@router.get("/api/workspace", tags=WORKSPACE_TAGS)
def workspace_status(request: Request) -> dict:
    current_user_id(request)
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
    return api_success(
        {
            "enabled": WORKSPACE_ENABLED,
            "sandboxEnabled": SANDBOX_ENABLED,
            "sandboxReady": sandbox_ready,
            "platform": "linux" if sys.platform.startswith("linux") else "unsupported",
            "maxFileBytes": WORKSPACE_MAX_FILE_BYTES,
        }
    )


@router.get("/api/workspace/files", tags=WORKSPACE_TAGS)
def list_workspace_files(request: Request, path: str = "") -> dict:
    try:
        return api_success(_runtime(request).list_entries(path))
    except WorkspaceRuntimeError as exc:
        _raise_workspace_error(exc)


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
