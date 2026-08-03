from __future__ import annotations

import re
from typing import Any


FAILURE_POLICIES: dict[str, dict[str, Any]] = {
    "agent_run_cancelled": {
        "summary": "The Agent run was cancelled.",
        "retryable": True,
        "target": None,
    },
    "agent_run_failed": {
        "summary": "The Agent run failed.",
        "retryable": True,
        "target": None,
    },
    "langgraph_checkpoint_not_found": {
        "summary": "The LangGraph checkpoint is unavailable for this run.",
        "retryable": False,
        "target": None,
    },
    "langgraph_checkpoint_unavailable": {
        "summary": "The LangGraph checkpoint store is unavailable.",
        "retryable": True,
        "target": None,
    },
    "mcp_authentication_required": {
        "summary": "The MCP connection requires authorization.",
        "retryable": False,
        "target": "tools",
    },
    "mcp_tool_configuration_invalid": {
        "summary": "The MCP tool configuration is invalid.",
        "retryable": False,
        "target": "tools",
    },
    "model_authentication_failed": {
        "summary": "The model credentials were rejected.",
        "retryable": False,
        "target": "settings",
    },
    "rate_limited": {
        "summary": "The upstream service is rate limited.",
        "retryable": True,
        "target": None,
    },
    "service_restart_interrupted": {
        "summary": "The Agent run was interrupted by a service restart.",
        "retryable": True,
        "target": None,
    },
    "upstream_timeout": {
        "summary": "The upstream service timed out.",
        "retryable": True,
        "target": None,
    },
    "web_search_timeout": {
        "summary": "The web search request timed out.",
        "retryable": True,
        "target": None,
    },
}


def _safe_code(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    return re.sub(r"[^a-z0-9_]", "", text)[:100]


def _status_code(error: Exception | None) -> int | None:
    if error is None:
        return None
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def normalize_failure_code(
    error: Exception | None = None,
    code: Any = None,
    source: str = "agent",
) -> str:
    raw_code = _safe_code(code or getattr(error, "code", None))
    status = _status_code(error)
    type_name = type(error).__name__.lower() if error is not None else ""
    combined = "_".join(
        item for item in (_safe_code(source), raw_code, type_name) if item
    )

    if raw_code == "service_restart_interrupted":
        return raw_code
    if raw_code == "agent_run_cancelled":
        return raw_code
    if raw_code == "web_search_timeout":
        return raw_code
    if status in {401, 403} or any(
        marker in combined
        for marker in (
            "api_key",
            "authentication",
            "invalid_key",
            "oauth",
            "resource_unauthorized",
            "unauthorized",
        )
    ):
        if any(marker in combined for marker in ("mcp", "oauth", "resource_")):
            return "mcp_authentication_required"
        return "model_authentication_failed"
    if status == 429 or "rate_limit" in combined:
        return "rate_limited"
    if status in {408, 504} or "timeout" in combined:
        return "upstream_timeout"
    if raw_code == "mcp_tool_configuration_invalid":
        return raw_code
    return raw_code or "agent_run_failed"


def classify_agent_failure(
    error: Exception | None = None,
    *,
    code: Any = None,
    source: str = "agent",
) -> dict[str, Any]:
    normalized = normalize_failure_code(error, code, source)
    policy = FAILURE_POLICIES.get(
        normalized,
        FAILURE_POLICIES["agent_run_failed"],
    )
    return {"code": normalized, **policy}


def recovery_from_snapshot(
    status: str,
    steps: list[dict[str, Any]],
    trace: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if status not in {"failed", "interrupted", "cancelled"}:
        return None

    failed_step = next(
        (item for item in reversed(steps) if item.get("status") == "failed"),
        None,
    )
    failed_trace = next(
        (item for item in reversed(trace) if item.get("status") == "failed"),
        None,
    )
    if failed_step:
        return classify_agent_failure(
            code=failed_step.get("errorCode"),
            source=str(failed_step.get("kind") or "agent"),
        )
    if failed_trace:
        return classify_agent_failure(
            code=failed_trace.get("errorCode"),
            source=str(failed_trace.get("kind") or "agent"),
        )
    if status == "interrupted":
        return classify_agent_failure(code="service_restart_interrupted")
    if status == "cancelled":
        return classify_agent_failure(code="agent_run_cancelled")
    return classify_agent_failure(code="agent_run_failed")
