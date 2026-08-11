from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


AGENT_EVENT_SCHEMA_VERSION = 1


def _status(value: Any) -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "success": "completed",
        "succeeded": "completed",
        "done": "completed",
        "error": "failed",
        "waiting_approval": "waiting",
    }
    return aliases.get(status, status)


def _normalized_status(event_name: str, value: Any) -> str:
    explicit = _status(value)
    if explicit:
        return explicit
    if event_name.endswith((".failed",)) or event_name == "error.raised":
        return "failed"
    if event_name.endswith(".cancelled"):
        return "cancelled"
    if event_name.endswith(".skipped"):
        return "skipped"
    if event_name.endswith((".waiting", ".required")):
        return "waiting"
    if event_name.endswith((".completed", ".created", ".resolved", ".closed")):
        return "completed"
    return "running"


def _event_name(event: dict[str, Any]) -> str:
    explicit = str(event.get("eventName") or "").strip()
    if explicit:
        return explicit
    legacy = str(event.get("type") or "runtime_event").strip()
    status = _status(event.get("status"))
    if legacy == "agent_step":
        return {
            "completed": "step.completed",
            "failed": "step.failed",
            "cancelled": "step.cancelled",
            "waiting": "step.waiting",
        }.get(status, "step.started")
    if legacy == "step_updated":
        return "step.updated"
    if legacy == "tool_started":
        return "tool.started"
    if legacy == "tool_progress":
        return "tool.progress"
    if legacy in {"tool_result", "tool"}:
        return {
            "failed": "tool.failed",
            "cancelled": "tool.cancelled",
        }.get(status, "tool.completed")
    if legacy == "approval_required":
        return "approval.required"
    if legacy in {"approval_resolved", "approval_submitted"}:
        return "approval.resolved"
    if legacy == "memory_started":
        return "memory.started"
    if legacy == "memory_result":
        return {
            "failed": "memory.failed",
            "cancelled": "memory.cancelled",
            "skipped": "memory.skipped",
        }.get(status, "memory.completed")
    if legacy == "run_started":
        return "run.started"
    if legacy in {"run_snapshot", "run_updated"}:
        return "run.updated"
    if legacy == "plan_created":
        return "run.plan_created"
    if legacy == "done":
        return "run.cancelled" if status == "cancelled" else "run.completed"
    if legacy == "cancelled":
        return "run.cancelled"
    if legacy == "error":
        return "error.raised"
    if legacy in {"answer", "message", "text_delta"}:
        return "message.completed" if event.get("final") else "message.delta"
    if legacy == "reference":
        return "artifact.created"
    if legacy == "quality":
        return "run.quality_updated"
    if legacy.startswith("context_compaction"):
        return legacy.replace("_", ".")
    if legacy == "model_retry":
        return "model.retrying"
    if legacy == "stream_closed":
        return "stream.closed"
    return legacy.replace("_", ".")


def _run_id(event: dict[str, Any], fallback: str | None) -> str | None:
    value = event.get("runId") or fallback
    snapshot = event.get("run")
    if not value and isinstance(snapshot, dict):
        value = snapshot.get("id")
    text = str(value or "").strip()
    return text or None


def _error_payload(event: dict[str, Any], event_name: str) -> dict[str, Any] | None:
    structured = event.get("error")
    structured_error = structured if isinstance(structured, dict) else {}
    code = (
        structured_error.get("code")
        or event.get("errorCode")
        or event.get("code")
    )
    message = structured_error.get("message") or event.get("errorMessage")
    is_error = event_name == "error.raised" or event_name.endswith(".failed")
    if not is_error and not structured_error and not code and not message:
        return None
    if message is None and is_error:
        message = event.get("message")
    code_text = str(code or "agent_error")
    non_retryable = {
        "approval_expired",
        "permission_denied",
        "tool_cancelled",
        "agent_run_cancelled",
    }
    payload = {
        "code": code_text,
        "message": str(message or "Agent运行失败。"),
        "retryable": bool(
            structured_error.get(
                "retryable",
                code_text not in non_retryable,
            )
        ),
    }
    return payload


def _recovery_actions(
    event_name: str,
    error: dict[str, Any] | None,
) -> list[str]:
    if event_name == "approval.required":
        return ["allow_once", "deny"]
    if event_name == "tool.failed":
        return ["retry", "fix"] if error and error.get("retryable") else ["fix"]
    if event_name in {"step.failed", "error.raised"}:
        return ["continue", "retry"] if error and error.get("retryable") else ["continue"]
    return []


def normalize_agent_event(
    value: dict[str, Any],
    *,
    run_id: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Add the stable Agent event envelope while preserving legacy fields."""
    event = dict(value)
    event_name = _event_name(event)
    resolved_run_id = _run_id(event, run_id)
    status = _normalized_status(event_name, event.get("status"))
    error = _error_payload(event, event_name)
    event.setdefault("schemaVersion", AGENT_EVENT_SCHEMA_VERSION)
    event.setdefault("eventName", event_name)
    event.setdefault("eventId", f"evt_{uuid4().hex}")
    event.setdefault("occurredAt", datetime.now(timezone.utc).isoformat())
    if resolved_run_id:
        event.setdefault("runId", resolved_run_id)
    if sequence is not None:
        event.setdefault("sequence", max(1, int(sequence)))
    event.setdefault("normalizedStatus", status)
    event.setdefault("category", event_name.split(".", 1)[0])
    event.setdefault("phase", event["category"])
    if str(event.get("type") or "") == "reference":
        event.setdefault("artifactType", "reference")
    if error is not None:
        existing_error = event.get("error")
        event["error"] = {
            **(existing_error if isinstance(existing_error, dict) else {}),
            **error,
        }
    actions = _recovery_actions(event_name, error)
    if actions:
        event.setdefault("recoveryActions", actions)
    if "durationMs" not in event and event.get("latencyMs") is not None:
        event["durationMs"] = event.get("latencyMs")
    return event


class AgentEventNormalizer:
    """Assign monotonically increasing sequence numbers within one stream."""

    def __init__(
        self,
        run_id: str | None = None,
        *,
        initial_sequence: int = 0,
    ) -> None:
        self.run_id = run_id
        self.sequence = max(0, int(initial_sequence))

    def __call__(self, value: dict[str, Any]) -> dict[str, Any]:
        self.sequence += 1
        source = dict(value)
        source.pop("sequence", None)
        if self.run_id:
            source["runId"] = self.run_id
        event = normalize_agent_event(
            source,
            run_id=self.run_id,
            sequence=self.sequence,
        )
        if not self.run_id and event.get("runId"):
            self.run_id = str(event["runId"])
        return event
