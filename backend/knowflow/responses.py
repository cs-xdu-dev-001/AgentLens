from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_success(data: Any = None, message: str = "success") -> dict[str, Any]:
    return {"code": 0, "message": message, "data": data}


def api_error_payload(code: int | str, message: str, data: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "data": data}


def normalize_api_error_detail(detail: Any, status_code: int) -> dict[str, Any]:
    if isinstance(detail, dict):
        code = detail.get("code") or status_code * 100
        if not isinstance(code, (int, str)):
            code = status_code * 100
        message = str(detail.get("message") or detail.get("detail") or "Unknown error")
        return api_error_payload(code, message, detail.get("data"))
    message = str(detail or "Unknown error")
    return api_error_payload(status_code * 100, message, None)


def raise_api_error(status_code: int, code: int | str, message: str, data: Any = None) -> None:
    raise HTTPException(status_code=status_code, detail=api_error_payload(code, message, data))
