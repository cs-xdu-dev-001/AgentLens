from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from ..runtime import (
    SkillGitHubInspect,
    SkillInstallRequest,
    SkillPatchRequest,
    SkillUpdateRequest,
    api_success,
    current_user_id,
    skills,
)
from ..services.skill_store import SkillStoreError


router = APIRouter(prefix="/api/skills", tags=["Skills"])

_STATUS_BY_CODE = {
    "skill_not_found": 404,
    "skill_import_expired": 410,
    "skill_archive_too_large": 413,
    "skill_content_too_large": 413,
    "skill_dependency_unavailable": 409,
    "skill_builtin_delete_forbidden": 409,
    "skill_slug_conflict": 409,
    "skill_update_unsupported": 409,
    "skill_install_failed": 409,
}


def _raise_store_error(exc: SkillStoreError) -> None:
    status = _STATUS_BY_CODE.get(exc.code, 400)
    messages = {
        "skill_not_found": "Skill not found.",
        "skill_import_expired": "Skill import has expired.",
        "skill_archive_too_large": "Skill archive is too large.",
        "skill_content_too_large": "Skill content is too large.",
        "skill_dependency_unavailable": "Skill dependencies are unavailable.",
        "skill_builtin_delete_forbidden": "Builtin Skills cannot be deleted.",
        "skill_slug_conflict": "Skill slug conflicts with a builtin.",
        "skill_update_unsupported": "This Skill does not support updates.",
        "skill_install_failed": "Skill installation failed.",
        "skill_invalid_source": "Invalid GitHub Skill source.",
        "skill_download_failed": "GitHub archive download failed.",
        "skill_invalid_manifest": "Skill manifest is invalid.",
        "skill_import_rejected": "Skill archive was rejected.",
    }
    raise HTTPException(
        status_code=status,
        detail={
            "code": exc.code,
            "message": messages.get(exc.code, "Skill operation failed."),
            "data": None,
        },
    ) from exc


async def _read_bounded_upload(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > skills.archive_limits.max_archive_bytes:
            raise SkillStoreError(
                "skill_archive_too_large", "Skill archive is too large."
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/")
def list_skills(request: Request) -> dict:
    try:
        data = skills.list_for_user(current_user_id(request))
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.post("/import/github/inspect")
def inspect_github(payload: SkillGitHubInspect, request: Request) -> dict:
    try:
        data = skills.inspect_github(
            current_user_id(request),
            payload.url,
            ref=payload.ref,
            subpath=payload.subpath,
        )
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.post("/import/upload/inspect")
async def inspect_upload(
    request: Request,
    file: UploadFile = File(...),
) -> dict:
    try:
        archive = await _read_bounded_upload(file)
        data = skills.inspect_upload(current_user_id(request), archive)
    except SkillStoreError as exc:
        _raise_store_error(exc)
    finally:
        await file.close()
    return api_success(data)


@router.post("/import/{import_id}/install")
def install_skill(
    import_id: str,
    payload: SkillInstallRequest,
    request: Request,
) -> dict:
    try:
        data = skills.install(
            current_user_id(request),
            import_id,
            enabled=payload.enabled,
        )
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.get("/{skill_id}")
def get_skill(skill_id: int, request: Request) -> dict:
    try:
        data = skills.get_for_user(current_user_id(request), skill_id)
    except SkillStoreError as exc:
        _raise_store_error(exc)
    if data is None:
        _raise_store_error(SkillStoreError("skill_not_found"))
    return api_success(data)


@router.get("/{skill_id}/content")
def get_skill_content(skill_id: int, request: Request) -> dict:
    try:
        data = skills.content_for_user(current_user_id(request), skill_id)
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.patch("/{skill_id}")
def patch_skill(
    skill_id: int,
    payload: SkillPatchRequest,
    request: Request,
) -> dict:
    try:
        data = skills.set_enabled(
            current_user_id(request), skill_id, payload.enabled
        )
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.post("/{skill_id}/check-update")
def check_skill_update(skill_id: int, request: Request) -> dict:
    try:
        data = skills.check_update(current_user_id(request), skill_id)
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.post("/{skill_id}/update")
def update_skill(
    skill_id: int,
    payload: SkillUpdateRequest,
    request: Request,
) -> dict:
    try:
        data = skills.update(
            current_user_id(request),
            skill_id,
            enabled=payload.enabled,
        )
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, request: Request) -> dict:
    try:
        data = skills.delete(current_user_id(request), skill_id)
    except SkillStoreError as exc:
        _raise_store_error(exc)
    return api_success(data)
