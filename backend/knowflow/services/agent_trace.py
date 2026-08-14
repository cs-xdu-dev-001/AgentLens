from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timezone
import json
import re
import time
from typing import Any
import uuid


TRACE_KINDS = {
    "model",
    "tool",
    "mcp",
    "skill",
    "agent",
    "system",
    "approval",
    "question",
    "memory",
    "sandbox",
    "workspace",
}
TRACE_STATUSES = {
    "waiting",
    "running",
    "success",
    "failed",
    "cancelled",
}
SENSITIVE_KEYS = {
    "accesstoken",
    "apikey",
    "authorization",
    "clientsecret",
    "codeverifier",
    "cookie",
    "headers",
    "refreshtoken",
    "secret",
    "token",
    "password",
}
SECRET_PATTERN = re.compile(
    r"(?i)(tvly-[a-z0-9_-]+|ntn_[a-z0-9_-]+|sk-[a-z0-9_-]{8,}|"
    r"bearer\s+[a-z0-9._~+/-]+|"
    r"(?:api[_-]?key|token|secret|password|authorization|cookie)"
    r"\s*[:=]\s*[^\s,;}&]+|"
    r"--(?:api[-_]?key|token|secret|password|authorization|cookie)"
    r"(?:=|\s+)[^\s,;]+|"
    r"eyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+)"
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
    return normalized in SENSITIVE_KEYS


def _scrub_trace_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _is_sensitive_key(key)
                else _scrub_trace_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_trace_value(item) for item in value]
    if isinstance(value, str):
        return SECRET_PATTERN.sub("[REDACTED]", value)
    return value


def sanitize_trace_payload(value: Any) -> Any:
    """Return a JSON-safe shape with recursive secret redaction."""
    return _scrub_trace_value(value)


def sanitize_trace_value(
    value: Any,
    *,
    max_chars: int = 700,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    safe = sanitize_trace_payload(value)
    if isinstance(safe, (dict, list, tuple)):
        text_value = json.dumps(
            safe,
            ensure_ascii=False,
            default=str,
        )
    else:
        text_value = str(safe)
    return SECRET_PATTERN.sub("[REDACTED]", text_value)[:max_chars]


class AgentTraceRecorder:
    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None] | None = None,
        run_id: str | None = None,
        clock: Callable[[], float] = time.perf_counter,
        initial_steps: list[dict[str, Any]] | None = None,
    ):
        self.emit = emit
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:12]}"
        self.clock = clock
        self.steps: dict[str, dict[str, Any]] = {}
        self.started: dict[str, float] = {}
        for raw_step in initial_steps or []:
            if not isinstance(raw_step, dict):
                continue
            step = _scrub_trace_value(deepcopy(raw_step))
            step_id = str(step.get("stepId") or "")
            if (
                not step_id
                or step_id in self.steps
                or step.get("kind") not in TRACE_KINDS
                or step.get("status") not in TRACE_STATUSES
            ):
                continue
            step["runId"] = self.run_id
            self.steps[step_id] = step
            if step["status"] in {"running", "waiting"}:
                self.started[step_id] = self.clock()

    def _publish(self, event: dict[str, Any]) -> None:
        self.steps[event["stepId"]] = event
        if self.emit:
            self.emit(deepcopy(event))

    def start_step(
        self,
        *,
        kind: str,
        name: str,
        title: str,
        parent_id: str | None = None,
        input_summary: Any = None,
        status: str = "running",
        details: dict[str, Any] | None = None,
    ) -> str:
        if kind not in TRACE_KINDS:
            raise ValueError(f"Unsupported trace kind: {kind}")
        if status not in {"running", "waiting"}:
            raise ValueError(
                f"Unsupported initial trace status: {status}"
            )
        sequence = len(self.steps) + 1
        step_id = f"step_{sequence}"
        while step_id in self.steps:
            sequence += 1
            step_id = f"step_{sequence}"
        self.started[step_id] = self.clock()
        self._publish(
            {
                "runId": self.run_id,
                "stepId": step_id,
                "parentId": parent_id,
                "kind": kind,
                "name": name,
                "status": status,
                "title": title,
                "inputSummary": sanitize_trace_value(input_summary),
                "outputSummary": None,
                "errorCode": None,
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "durationMs": None,
                "details": _scrub_trace_value(details or {}),
            }
        )
        return step_id

    def finish_step(
        self,
        step_id: str,
        *,
        status: str,
        title: str,
        output_summary: Any = None,
        error_code: str | None = None,
    ) -> None:
        terminal_statuses = TRACE_STATUSES - {"waiting", "running"}
        if status not in terminal_statuses:
            raise ValueError(
                f"Unsupported terminal trace status: {status}"
            )
        current = self.steps[step_id]
        started_at = self.started.pop(step_id, None)
        previous_duration = current.get("durationMs")
        duration_ms = (
            int((self.clock() - started_at) * 1000)
            if started_at is not None
            else 0
        )
        if isinstance(previous_duration, (int, float)):
            duration_ms += int(previous_duration)
        self._publish(
            {
                **current,
                "status": status,
                "title": title,
                "outputSummary": sanitize_trace_value(output_summary),
                "errorCode": error_code,
                "durationMs": max(0, duration_ms),
            }
        )

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            deepcopy(step)
            for step in self.steps.values()
        ]
