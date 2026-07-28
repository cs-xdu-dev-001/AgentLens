from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import secrets
from threading import Event, Lock
import time
from typing import Any, Callable, TYPE_CHECKING

from .agent_trace import sanitize_trace_value

if TYPE_CHECKING:
    from .agent_loop import ToolDefinition
    from .agent_trace import AgentTraceRecorder


ApprovalEmitter = Callable[[dict[str, Any]], None]


@dataclass
class _PendingApproval:
    event: Event
    user_id: int
    run_id: str
    deadline: float
    decision: str | None = None


class ApprovalBroker:
    def __init__(
        self,
        *,
        timeout_seconds: float = 300,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.timeout_seconds = max(0.001, float(timeout_seconds))
        self.clock = clock
        self.wall_clock = wall_clock
        self._lock = Lock()
        self._pending: dict[str, _PendingApproval] = {}
        self._closed = False

    def request(
        self,
        *,
        user_id: int,
        run_id: str,
        server_name: str,
        tool_name: str,
        risk: str,
        input_summary: Any,
        emit: ApprovalEmitter | None = None,
    ) -> str:
        approval_id = f"apr_{secrets.token_urlsafe(18)}"
        deadline = self.clock() + self.timeout_seconds
        pending = _PendingApproval(
            event=Event(),
            user_id=user_id,
            run_id=run_id,
            deadline=deadline,
        )
        with self._lock:
            if self._closed:
                return "deny"
            self._pending[approval_id] = pending

        try:
            step_id = f"step_{approval_id}"
            if emit:
                expires_at = datetime.fromtimestamp(
                    self.wall_clock() + self.timeout_seconds,
                    tz=timezone.utc,
                ).isoformat().replace("+00:00", "Z")
                emit(
                    {
                        "type": "approval_required",
                        "approvalId": approval_id,
                        "runId": run_id,
                        "stepId": step_id,
                        "serverName": (
                            sanitize_trace_value(server_name) or "MCP"
                        ),
                        "toolName": (
                            sanitize_trace_value(tool_name) or "tool"
                        ),
                        "risk": sanitize_trace_value(risk) or "unknown",
                        "inputSummary": sanitize_trace_value(
                            input_summary
                        ),
                        "expiresAt": expires_at,
                    }
                )
            pending.event.wait(self.timeout_seconds)
            with self._lock:
                if pending.decision is None:
                    pending.decision = "timeout"
                decision = pending.decision
            if emit:
                emit(
                    {
                        "type": "approval_resolved",
                        "approvalId": approval_id,
                        "stepId": step_id,
                        "decision": decision,
                        "status": (
                            "success"
                            if decision == "allow_once"
                            else "failed"
                        ),
                    }
                )
            return decision
        finally:
            with self._lock:
                if self._pending.get(approval_id) is pending:
                    self._pending.pop(approval_id, None)

    def resolve(
        self,
        user_id: int,
        approval_id: str,
        decision: str,
    ) -> bool:
        if decision not in {"allow_once", "deny"}:
            return False
        with self._lock:
            pending = self._pending.get(approval_id)
            if (
                pending is None
                or pending.user_id != user_id
                or pending.decision is not None
            ):
                return False
            if self.clock() >= pending.deadline:
                pending.decision = "timeout"
                pending.event.set()
                return False
            pending.decision = decision
            pending.event.set()
            return True

    def cancel_run(self, run_id: str) -> int:
        resolved = 0
        with self._lock:
            for pending in self._pending.values():
                if pending.run_id == run_id and pending.decision is None:
                    pending.decision = "deny"
                    pending.event.set()
                    resolved += 1
        return resolved

    def shutdown(self) -> int:
        resolved = 0
        with self._lock:
            self._closed = True
            for pending in self._pending.values():
                if pending.decision is None:
                    pending.decision = "deny"
                    pending.event.set()
                    resolved += 1
        return resolved


class AgentApprovalGate:
    def __init__(
        self,
        *,
        broker: ApprovalBroker,
        user_id: int,
        run_id: str,
        emit: ApprovalEmitter | None = None,
        trace: AgentTraceRecorder | None = None,
        parent_step_id: str | None = None,
    ):
        self.broker = broker
        self.user_id = user_id
        self.run_id = run_id
        self.emit = emit
        self.trace = trace
        self.parent_step_id = parent_step_id
        self._approval_steps: dict[str, str] = {}

    def set_parent_step_id(self, parent_step_id: str | None) -> None:
        self.parent_step_id = parent_step_id

    def _emit(self, event: dict[str, Any]) -> None:
        public_event = dict(event)
        approval_id = str(public_event["approvalId"])
        if public_event["type"] == "approval_required":
            if self.trace:
                step_id = self.trace.start_step(
                    kind="approval",
                    name="approval_required",
                    title="Waiting for approval",
                    parent_id=self.parent_step_id,
                    input_summary=public_event.get("inputSummary"),
                    status="waiting",
                    details={
                        key: public_event[key]
                        for key in (
                            "approvalId",
                            "risk",
                            "serverName",
                            "toolName",
                            "expiresAt",
                        )
                    },
                )
                self._approval_steps[approval_id] = step_id
                public_event["stepId"] = step_id
        elif public_event["type"] == "approval_resolved":
            step_id = self._approval_steps.pop(
                approval_id,
                public_event.get("stepId"),
            )
            public_event["stepId"] = step_id
            if self.trace and step_id in self.trace.steps:
                decision = public_event.get("decision")
                allowed = decision == "allow_once"
                error_code = (
                    None
                    if allowed
                    else (
                        "approval_timeout"
                        if decision == "timeout"
                        else "permission_denied"
                    )
                )
                self.trace.finish_step(
                    step_id,
                    status="success" if allowed else "failed",
                    title=(
                        "Approval granted"
                        if allowed
                        else (
                            "Approval timed out"
                            if decision == "timeout"
                            else "Approval denied"
                        )
                    ),
                    output_summary={"decision": decision},
                    error_code=error_code,
                )
        if self.emit:
            self.emit(public_event)

    def request(
        self,
        definition: ToolDefinition,
        arguments: dict[str, Any],
        call_id: str,
    ) -> str:
        return self.broker.request(
            user_id=self.user_id,
            run_id=self.run_id,
            server_name=definition.server_name or "MCP",
            tool_name=definition.name,
            risk=definition.risk,
            input_summary=sanitize_trace_value(arguments),
            emit=self._emit,
        )
