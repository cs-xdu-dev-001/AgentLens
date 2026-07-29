from fastapi import APIRouter, HTTPException, Query, Request

from ..responses import api_success
from ..runtime import current_user_id, memory_manager
from ..schemas import MemoryContentUpdate, MemorySettingsUpdate
from ..services.memory import (
    MemoryNotFoundError,
    MemoryUnavailableError,
)


router = APIRouter()
MEMORY_TAGS = ["Memory"]


def _memory_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MemoryNotFoundError):
        return HTTPException(status_code=404, detail="记忆不存在。")
    if isinstance(exc, MemoryUnavailableError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="记忆操作失败。")


@router.get(
    "/api/memory/settings",
    tags=MEMORY_TAGS,
    summary="Read memory settings",
)
def read_memory_settings(request: Request):
    return api_success(memory_manager.settings(current_user_id(request)))


@router.put(
    "/api/memory/settings",
    tags=MEMORY_TAGS,
    summary="Update memory settings",
)
def update_memory_settings(
    payload: MemorySettingsUpdate,
    request: Request,
):
    try:
        data = memory_manager.set_enabled(
            current_user_id(request),
            payload.enabled,
        )
    except Exception as exc:
        raise _memory_error(exc) from exc
    return api_success(data)


@router.get(
    "/api/memories",
    tags=MEMORY_TAGS,
    summary="List long-term memories",
)
def list_memories(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        data = memory_manager.list(current_user_id(request), limit)
    except Exception as exc:
        raise _memory_error(exc) from exc
    return api_success(data)


@router.put(
    "/api/memories/{memory_id}",
    tags=MEMORY_TAGS,
    summary="Update a long-term memory",
)
def update_memory(
    memory_id: str,
    payload: MemoryContentUpdate,
    request: Request,
):
    try:
        data = memory_manager.update(
            current_user_id(request),
            memory_id,
            payload.content,
        )
    except Exception as exc:
        raise _memory_error(exc) from exc
    return api_success(data)


@router.delete(
    "/api/memories/{memory_id}",
    tags=MEMORY_TAGS,
    summary="Delete a long-term memory",
)
def delete_memory(memory_id: str, request: Request):
    try:
        memory_manager.delete(current_user_id(request), memory_id)
    except Exception as exc:
        raise _memory_error(exc) from exc
    return api_success(True)


@router.delete(
    "/api/memories",
    tags=MEMORY_TAGS,
    summary="Delete all long-term memories",
)
def delete_all_memories(request: Request):
    try:
        memory_manager.delete_all(current_user_id(request))
    except Exception as exc:
        raise _memory_error(exc) from exc
    return api_success(True)
