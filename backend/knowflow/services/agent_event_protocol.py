from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from .agent_trace import sanitize_trace_payload
from .agent_failure import classify_agent_failure, normalize_failure_code


AGENT_EVENT_SCHEMA_VERSION = 1

_ARTIFACT_TOOLS = {
    "edit_workspace_file": "edit",
    "write_workspace_file": "write",
}

_PUBLIC_ARTIFACT_TYPES = {"file", "link", "reference"}
_PUBLIC_ARTIFACT_OPERATIONS = {"edit", "write"}
_PUBLIC_RUN_STATUSES = {
    "cancelled",
    "completed",
    "failed",
    "planning",
    "running",
    "waiting",
    "waiting_approval",
    "waiting_input",
    "waiting_start",
}
_TERMINAL_STEP_STATUSES = {
    "cancelled",
    "completed",
    "failed",
    "skipped",
    "success",
    "succeeded",
}

_VERIFICATION_RULES = (
    ("test", "pytest", re.compile(r"\b(?:pytest|python(?:\d+(?:\.\d+)?)?\s+-m\s+pytest)\b", re.I)),
    ("test", "python_check", re.compile(r"\btests[\\/]check_[^\s\"']+\.py\b", re.I)),
    ("test", "npm_test", re.compile(r"\bnpm\s+(?:run\s+)?test\b", re.I)),
    ("test", "pnpm_test", re.compile(r"\bpnpm\s+(?:run\s+)?test\b", re.I)),
    ("test", "yarn_test", re.compile(r"\byarn\s+test\b", re.I)),
    ("test", "project_test", re.compile(r"\b(?:vitest|jest|unittest|cargo\s+test|go\s+test|dotnet\s+test)\b", re.I)),
    ("build", "npm_build", re.compile(r"\bnpm\s+run\s+build\b", re.I)),
    ("build", "pnpm_build", re.compile(r"\bpnpm\s+(?:run\s+)?build\b", re.I)),
    ("build", "yarn_build", re.compile(r"\byarn\s+build\b", re.I)),
    ("build", "python_build", re.compile(r"\bpython(?:\d+(?:\.\d+)?)?\s+-m\s+build\b", re.I)),
    ("build", "project_build", re.compile(r"\b(?:vite\s+build|cargo\s+build|go\s+build|mvn\b[^\r\n]*\bpackage|gradle\b[^\r\n]*\bbuild)\b", re.I)),
    ("check", "git_diff_check", re.compile(r"\bgit\s+diff\s+--check\b", re.I)),
    ("check", "lint", re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b", re.I)),
    ("check", "typecheck", re.compile(r"\b(?:(?:npm|pnpm|yarn)\s+(?:run\s+)?typecheck|tsc\s+--noEmit)\b", re.I)),
    ("check", "static_check", re.compile(r"\b(?:ruff|mypy|flake8|eslint|prettier\s+--check)\b", re.I)),
)


def _summary_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _public_text(value: Any, *, max_chars: int = 1_000) -> str:
    sanitized = sanitize_trace_payload(
        str(value or "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    )
    return "".join(
        char for char in str(sanitized).strip() if ord(char) >= 32
    )[:max_chars]


def _public_url(value: Any) -> str:
    source = _public_text(value, max_chars=4_000)
    try:
        parsed = urlsplit(source)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", "", ""))[:4_000]


def _reference_label(*, title: str, filename: str, url: str, chunk_id: str) -> str:
    for candidate in (title, filename):
        if not candidate:
            continue
        safe_url = _public_url(candidate)
        if not safe_url:
            return candidate
        parsed = urlsplit(safe_url)
        path = "" if parsed.path == "/" else parsed.path.rstrip("/")
        return f"{parsed.hostname or parsed.netloc}{path}"[:300]
    if url:
        parsed = urlsplit(url)
        path = "" if parsed.path == "/" else parsed.path.rstrip("/")
        return f"{parsed.hostname or parsed.netloc}{path}"[:300]
    return f"片段 #{chunk_id[:40]}" if chunk_id else "引用来源"


def _workspace_relative_path(value: Any) -> str:
    path = _public_text(value)
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return ""
    parts = tuple(path.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return ""
    return "/".join(parts)


def _public_non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def public_run_summary_projection(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return the strict run-summary facts shared by Web and TUI clients."""
    explicit = event.get("runSummary")
    snapshot = event.get("run")
    source = explicit if isinstance(explicit, dict) else snapshot
    if not isinstance(source, dict):
        return None
    run_id = _public_text(
        source.get("runId") or source.get("id") or event.get("runId"),
        max_chars=200,
    )
    if not run_id:
        return None
    status = _public_text(
        source.get("status") or event.get("normalizedStatus"),
        max_chars=40,
    ).lower()
    if status not in _PUBLIC_RUN_STATUSES:
        status = "running"
    summary: dict[str, Any] = {
        "runId": run_id,
        "status": status,
    }
    headline = _public_text(
        source.get("headline")
        or source.get("goalSummary")
        or source.get("goal_summary"),
        max_chars=300,
    )
    if headline:
        summary["headline"] = headline
    for source_key, target_key in (
        ("startedAt", "startedAt"),
        ("finishedAt", "finishedAt"),
        ("lastActivityAt", "lastActivityAt"),
    ):
        value = _public_text(
            source.get(source_key)
            or (event.get("occurredAt") if source_key == "lastActivityAt" else None),
            max_chars=80,
        )
        if value:
            summary[target_key] = value
    steps = source.get("steps")
    if isinstance(steps, list):
        safe_steps = [step for step in steps if isinstance(step, dict)]
        summary["totalSteps"] = len(safe_steps)
        summary["completedSteps"] = sum(
            1
            for step in safe_steps
            if str(step.get("status") or "").lower()
            in _TERMINAL_STEP_STATUSES
        )
    for field in (
        "completedSteps",
        "totalSteps",
        "toolCalls",
        "artifactCount",
        "referenceCount",
        "inputTokens",
        "outputTokens",
        "totalTokens",
    ):
        if source.get(field) is not None:
            summary[field] = _public_non_negative_int(source.get(field))
    total_steps = summary.get("totalSteps", 0)
    completed_steps = min(summary.get("completedSteps", 0), total_steps)
    summary["completedSteps"] = completed_steps
    summary["totalSteps"] = total_steps
    summary["progressPercent"] = (
        min(100, round((completed_steps / total_steps) * 100))
        if total_steps
        else 0
    )
    return summary


def public_artifact_projection(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return the strict, credential-free artifact shape shared by clients."""
    artifact_type = _public_text(event.get("artifactType") or "", max_chars=40).lower()
    if artifact_type not in _PUBLIC_ARTIFACT_TYPES:
        return None
    identifier = _public_text(
        event.get("artifactId") or event.get("id"),
        max_chars=300,
    )
    path = _workspace_relative_path(event.get("path"))
    url = _public_url(event.get("url") or event.get("href"))
    filename = _public_text(event.get("filename"), max_chars=300)
    chunk_id = _public_text(
        event.get("chunkId") or event.get("chunk_id"),
        max_chars=200,
    )
    if artifact_type == "file" and not path:
        return None
    if artifact_type == "link" and not url:
        return None
    if artifact_type == "reference" and not (url or filename or chunk_id):
        return None
    if not identifier:
        identity = path or url or f"{filename}:{chunk_id}"
        identifier = f"{artifact_type}:{identity}"[:300]
    title = _public_text(event.get("title"), max_chars=300)
    display_label = _public_text(event.get("displayLabel"), max_chars=300)
    artifact: dict[str, Any] = {
        "artifactId": identifier,
        "artifactType": artifact_type,
        "title": title or filename or path or url,
    }
    if path:
        artifact["path"] = path
    if url:
        artifact["url"] = url
    if filename:
        artifact["filename"] = filename
    if chunk_id:
        artifact["chunkId"] = chunk_id
    if artifact_type == "reference":
        artifact["displayLabel"] = display_label or _reference_label(
            title=title,
            filename=filename,
            url=url,
            chunk_id=chunk_id,
        )
        artifact["sourceType"] = "web" if url else "knowledge"
        document_id = _public_text(
            event.get("documentId") or event.get("document_id"),
            max_chars=100,
        )
        if document_id:
            artifact["documentId"] = document_id
        excerpt = _public_text(
            event.get("excerpt") or event.get("content") or event.get("chunk_text"),
            max_chars=600,
        )
        if excerpt:
            artifact["excerpt"] = excerpt
    operation = _public_text(event.get("operation"), max_chars=40).lower()
    if operation in _PUBLIC_ARTIFACT_OPERATIONS:
        artifact["operation"] = operation
    for field in ("addedLines", "removedLines", "writtenBytes"):
        if event.get(field) is not None:
            artifact[field] = _public_non_negative_int(event.get(field))
    for field in ("operationId", "sourceTool", "toolCallId", "changeStatus"):
        value = _public_text(event.get(field), max_chars=200)
        if value:
            artifact[field] = value
    for field in ("diffAvailable", "reverted"):
        if event.get(field) is not None:
            artifact[field] = bool(event.get(field))
    if event.get("score") is not None:
        try:
            artifact["score"] = max(0.0, min(1.0, float(event.get("score"))))
        except (TypeError, ValueError, OverflowError):
            pass
    return artifact


def verification_from_agent_event(
    event: dict[str, Any],
    *,
    normalized_status: str | None = None,
) -> dict[str, Any] | None:
    """Create a credential-free verification fact from a terminal shell tool event."""
    tool_name = str(event.get("toolName") or event.get("name") or "").strip()
    if tool_name != "run_sandbox_command":
        return None
    status = _status(normalized_status or event.get("normalizedStatus") or event.get("status"))
    if status not in {"cancelled", "completed", "failed"}:
        return None
    arguments = _summary_object(event.get("arguments") or event.get("inputSummary"))
    command = str(arguments.get("command") or arguments.get("cmd") or "")
    matched = next(
        ((kind, tool) for kind, tool, pattern in _VERIFICATION_RULES if pattern.search(command)),
        None,
    )
    if matched is None:
        return None
    output = _summary_object(event.get("output") or event.get("outputSummary"))
    raw_exit_code = output.get("exit_code", output.get("exitCode", event.get("exitCode")))
    if raw_exit_code is None or raw_exit_code == "":
        exit_code = None
    else:
        try:
            exit_code = int(raw_exit_code)
        except (TypeError, ValueError):
            exit_code = None
    failed = status in {"cancelled", "failed"} or (exit_code is not None and exit_code != 0)
    kind, tool = matched
    identifier = str(event.get("toolCallId") or event.get("stepId") or event.get("eventId") or "")
    verification: dict[str, Any] = {
        "id": f"verification:{identifier}" if identifier else "verification",
        "kind": kind,
        "tool": tool,
        "status": "failed" if failed else "passed",
    }
    if exit_code is not None:
        verification["exitCode"] = exit_code
    duration_ms = event.get("durationMs", event.get("latencyMs"))
    if isinstance(duration_ms, (int, float)) and duration_ms >= 0:
        verification["durationMs"] = int(duration_ms)
    return verification


def artifact_event_from_tool_execution(
    *,
    tool_name: Any,
    status: Any,
    output: Any,
    tool_call_id: Any = None,
) -> dict[str, Any] | None:
    """Project successful workspace writes into the public artifact protocol."""
    name = str(tool_name or "").strip()
    if _status(status) != "completed" or name not in _ARTIFACT_TOOLS:
        return None
    if not isinstance(output, dict):
        return None
    path = _workspace_relative_path(output.get("path"))
    if not path:
        return None
    artifact: dict[str, Any] = {
        "type": "artifact_created",
        "artifactId": f"file:{path}",
        "artifactType": "file",
        "title": path,
        "path": path,
        "operation": _ARTIFACT_TOOLS[name],
        "sourceTool": name,
    }
    call_id = str(tool_call_id or "").strip()
    if call_id:
        artifact["toolCallId"] = call_id
    for source, target in (
        ("writtenBytes", "writtenBytes"),
        ("addedLines", "addedLines"),
        ("removedLines", "removedLines"),
    ):
        value = output.get(source)
        if value is not None:
            artifact[target] = _public_non_negative_int(value)
    operation_id = str(output.get("operationId") or "").strip()
    if operation_id:
        artifact["operationId"] = operation_id[:200]
        artifact["diffAvailable"] = True
    artifact["reverted"] = False
    return artifact


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
    if legacy == "user_question_required":
        return "question.required"
    if legacy == "user_question_resolved":
        return "question.resolved"
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
    if legacy == "context_usage_updated":
        return "context.usage_updated"
    if legacy.startswith("context_compaction"):
        return legacy.replace("_", ".")
    if legacy == "model_retry":
        return "model.retrying"
    if legacy == "stream_closed":
        return "stream.closed"
    return legacy.replace("_", ".")


def agent_event_name(event: dict[str, Any]) -> str:
    """Resolve canonical Agent event names while preserving legacy input."""
    return _event_name(event)


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
    message_text = _public_text(message or "Agent运行失败。")
    event_source = event_name.split(".", 1)[0] or "agent"
    inferred_failure = classify_agent_failure(
        error=RuntimeError(message_text),
        code=code,
        source=event_source,
    )
    inferred_code = normalize_failure_code(
        error=RuntimeError(message_text),
        code=code,
        source=event_source,
    )
    code_text = _public_text(code or "agent_error", max_chars=100)
    model_failure_codes = {
        "model_authentication_failed",
        "access_denied",
        "not_found",
        "protocol_unsupported",
        "incompatible_parameters",
        "upstream_unavailable",
        "network_error",
        "invalid_request",
    }
    if (
        inferred_code != "agent_run_failed"
        and (
            code_text in {"agent_error", "agent_run_failed"}
            or inferred_code in model_failure_codes
            and code_text not in model_failure_codes
        )
    ):
        code_text = inferred_code
    if code_text == "rate_limited" or inferred_code == "rate_limited":
        code_text = "rate_limited"
        message_text = "上游模型请求过于频繁，自动重试后仍未恢复。"
    non_retryable = {
        "approval_expired",
        "permission_denied",
        "tool_cancelled",
        "agent_run_cancelled",
    }
    payload = {
        "code": code_text,
        "message": message_text,
        "retryable": bool(
            structured_error.get(
                "retryable",
                bool(inferred_failure["retryable"])
                and code_text not in non_retryable,
            )
        ),
    }
    target = structured_error.get("target")
    if not target and code_text == inferred_failure["code"]:
        target = inferred_failure.get("target")
    if target in {"memory", "settings", "tools"}:
        payload["target"] = target
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
        return (
            ["continue", "retry", "fix"]
            if error and error.get("retryable")
            else ["fix"]
        )
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
    run_summary = public_run_summary_projection(event)
    if run_summary is not None:
        event["runSummary"] = run_summary
    if str(event.get("type") or "") == "reference":
        event.setdefault("artifactType", "reference")
    if event_name in {"artifact.created", "artifact.updated"}:
        artifact = public_artifact_projection(event)
        if artifact is not None:
            envelope = {
                key: event.get(key)
                for key in (
                    "type",
                    "schemaVersion",
                    "eventName",
                    "eventId",
                    "occurredAt",
                    "runId",
                    "sequence",
                    "normalizedStatus",
                    "category",
                    "phase",
                )
                if event.get(key) is not None
            }
            event = {**envelope, **artifact}
    if error is not None:
        event["error"] = error
        for field in ("message", "errorMessage"):
            if field in event:
                event[field] = error["message"]
        for field in ("code", "errorCode"):
            if field in event:
                event[field] = error["code"]
    actions = _recovery_actions(event_name, error)
    if error is not None or event_name == "approval.required":
        event["recoveryActions"] = actions
    elif actions:
        event.setdefault("recoveryActions", actions)
    if "durationMs" not in event and event.get("latencyMs") is not None:
        event["durationMs"] = event.get("latencyMs")
    verification = verification_from_agent_event(
        event,
        normalized_status=status,
    )
    if verification is not None:
        event["verification"] = verification
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
        self.run_summary: dict[str, Any] = {}
        self._steps: dict[str, str] = {}
        self._tool_calls: set[str] = set()
        self._artifacts: set[str] = set()
        self._references: set[str] = set()

    def _update_run_summary(self, event: dict[str, Any]) -> dict[str, Any] | None:
        event_name = str(event.get("eventName") or "")
        incoming = public_run_summary_projection(event)
        if incoming is not None:
            self.run_summary.update(incoming)
            snapshot = event.get("run")
            steps = snapshot.get("steps") if isinstance(snapshot, dict) else None
            if isinstance(steps, list):
                self._steps = {
                    str(step.get("id") or step.get("stepId") or index): str(
                        step.get("status") or "waiting"
                    ).lower()
                    for index, step in enumerate(steps)
                    if isinstance(step, dict)
                }
        run_id = _public_text(
            event.get("runId") or self.run_id,
            max_chars=200,
        )
        if not run_id:
            return None
        self.run_summary.setdefault("runId", run_id)
        self.run_summary["lastActivityAt"] = str(event.get("occurredAt") or "")
        headline = _public_text(
            event.get("headline")
            or event.get("goalSummary")
            or event.get("goal_summary"),
            max_chars=300,
        )
        if headline:
            self.run_summary["headline"] = headline
        if event_name == "run.started":
            self.run_summary.update({
                "status": "running",
                "startedAt": str(event.get("occurredAt") or ""),
            })
        elif event_name == "run.completed":
            self.run_summary.update({
                "status": "completed",
                "finishedAt": str(event.get("occurredAt") or ""),
            })
        elif event_name == "run.cancelled":
            self.run_summary.update({
                "status": "cancelled",
                "finishedAt": str(event.get("occurredAt") or ""),
            })
        elif event_name in {"run.failed", "error.raised"}:
            self.run_summary.update({
                "status": "failed",
                "finishedAt": str(event.get("occurredAt") or ""),
            })
        elif event_name.startswith("run.") and incoming is None:
            status = _public_text(event.get("normalizedStatus"), max_chars=40)
            if status in _PUBLIC_RUN_STATUSES:
                self.run_summary["status"] = status

        if event_name.startswith("step."):
            identifier = _public_text(
                event.get("stepId") or event.get("id") or event.get("eventId"),
                max_chars=200,
            )
            if identifier:
                self._steps[identifier] = str(
                    event.get("status") or event.get("normalizedStatus") or "running"
                ).lower()
        if event_name.startswith("tool."):
            identifier = _public_text(
                event.get("toolCallId") or event.get("eventId"),
                max_chars=200,
            )
            if identifier:
                self._tool_calls.add(identifier)
        if event_name in {"artifact.created", "artifact.updated"}:
            artifact = public_artifact_projection(event)
            if artifact is not None:
                target = self._references if artifact["artifactType"] == "reference" else self._artifacts
                target.add(str(artifact["artifactId"]))
        if event_name == "usage.updated":
            usage = event.get("usage") if isinstance(event.get("usage"), dict) else event
            for source_key, target_key in (
                ("inputTokens", "inputTokens"),
                ("input_tokens", "inputTokens"),
                ("promptTokens", "inputTokens"),
                ("prompt_tokens", "inputTokens"),
                ("outputTokens", "outputTokens"),
                ("output_tokens", "outputTokens"),
                ("completionTokens", "outputTokens"),
                ("completion_tokens", "outputTokens"),
                ("totalTokens", "totalTokens"),
                ("total_tokens", "totalTokens"),
            ):
                if usage.get(source_key) is not None:
                    self.run_summary[target_key] = _public_non_negative_int(
                        usage.get(source_key)
                    )
            if "totalTokens" not in self.run_summary and (
                "inputTokens" in self.run_summary
                or "outputTokens" in self.run_summary
            ):
                self.run_summary["totalTokens"] = (
                    self.run_summary.get("inputTokens", 0)
                    + self.run_summary.get("outputTokens", 0)
                )

        if self._steps:
            self.run_summary["totalSteps"] = len(self._steps)
            self.run_summary["completedSteps"] = sum(
                1
                for status in self._steps.values()
                if status in _TERMINAL_STEP_STATUSES
            )
        if self._tool_calls or "toolCalls" not in self.run_summary:
            self.run_summary["toolCalls"] = len(self._tool_calls)
        if self._artifacts or "artifactCount" not in self.run_summary:
            self.run_summary["artifactCount"] = len(self._artifacts)
        if self._references or "referenceCount" not in self.run_summary:
            self.run_summary["referenceCount"] = len(self._references)
        total = _public_non_negative_int(self.run_summary.get("totalSteps"))
        completed = min(
            _public_non_negative_int(self.run_summary.get("completedSteps")),
            total,
        )
        self.run_summary["totalSteps"] = total
        self.run_summary["completedSteps"] = completed
        self.run_summary["progressPercent"] = (
            min(100, round((completed / total) * 100)) if total else 0
        )
        return public_run_summary_projection({"runSummary": self.run_summary})

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
        summary = self._update_run_summary(event)
        if summary is not None:
            event["runSummary"] = summary
        if not self.run_id and event.get("runId"):
            self.run_id = str(event["runId"])
        return event
