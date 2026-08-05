from __future__ import annotations

import json
import logging
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import text


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _timestamp(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat(sep=" ")


def _json_value(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return fallback


def _public_timestamp(raw: Any) -> str:
    value = str(raw or "").strip().replace(" ", "T")
    if value and not value.endswith("Z") and "+" not in value[10:]:
        value = f"{value}Z"
    return value


class AgentToolOperationStore:
    def __init__(
        self,
        *,
        database,
        approval_timeout_seconds: float,
        clock: Callable[[], datetime] = _now,
    ):
        self.database = database
        self.approval_timeout_seconds = max(
            0.001,
            float(approval_timeout_seconds),
        )
        self.clock = clock

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "approvalId": str(row["id"]),
            "userId": int(row["user_id"]),
            "runId": str(row["run_id"]),
            "toolCallId": str(row["tool_call_id"]),
            "toolName": str(row["tool_name"]),
            "serverName": str(row.get("server_name") or "MCP"),
            "risk": str(row.get("risk") or "unknown"),
            "inputSummary": _json_value(
                row.get("input_summary"),
                None,
            ),
            "status": str(row["status"]),
            "decision": (
                str(row["decision"])
                if row.get("decision") is not None
                else None
            ),
            "execution": _json_value(
                row.get("execution_json"),
                None,
            ),
            "expiresAt": _public_timestamp(row["expires_at"]),
            "resolvedAt": (
                _public_timestamp(row["resolved_at"])
                if row.get("resolved_at") is not None
                else None
            ),
            "startedAt": (
                _public_timestamp(row["started_at"])
                if row.get("started_at") is not None
                else None
            ),
            "finishedAt": (
                _public_timestamp(row["finished_at"])
                if row.get("finished_at") is not None
                else None
            ),
        }

    @staticmethod
    def _row(conn, user_id: int, approval_id: str):
        row = conn.execute(
            text(
                """
                SELECT * FROM agent_tool_operation
                WHERE id=:approval_id AND user_id=:user_id
                """
            ),
            {"approval_id": approval_id, "user_id": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def ensure_waiting(
        self,
        *,
        user_id: int,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        server_name: str,
        risk: str,
        input_summary: Any,
    ) -> dict[str, Any]:
        if int(user_id) <= 0 or not run_id or not tool_call_id:
            raise ValueError("A user, run, and tool call are required.")
        approval_id = f"apr_{secrets.token_urlsafe(18)}"
        now = self.clock()
        expires_at = now + timedelta(
            seconds=self.approval_timeout_seconds
        )
        with self.database.engine.begin() as conn:
            owner = conn.execute(
                text(
                    """
                    SELECT id FROM agent_run
                    WHERE id=:run_id AND user_id=:user_id
                    """
                ),
                {"run_id": run_id, "user_id": user_id},
            ).first()
            if owner is None:
                raise ValueError("Agent run was not found.")
            statement = (
                """
                INSERT IGNORE INTO agent_tool_operation(
                  id, user_id, run_id, tool_call_id, tool_name,
                  server_name, risk, input_summary, status,
                  expires_at, created_at, updated_at
                ) VALUES (
                  :id, :user_id, :run_id, :tool_call_id, :tool_name,
                  :server_name, :risk, :input_summary, 'waiting',
                  :expires_at, :created_at, :updated_at
                )
                """
                if self.database.is_mysql
                else """
                INSERT INTO agent_tool_operation(
                  id, user_id, run_id, tool_call_id, tool_name,
                  server_name, risk, input_summary, status,
                  expires_at, created_at, updated_at
                ) VALUES (
                  :id, :user_id, :run_id, :tool_call_id, :tool_name,
                  :server_name, :risk, :input_summary, 'waiting',
                  :expires_at, :created_at, :updated_at
                )
                ON CONFLICT(run_id, tool_call_id) DO NOTHING
                """
            )
            conn.execute(
                text(statement),
                {
                    "id": approval_id,
                    "user_id": user_id,
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "tool_name": str(tool_name)[:160],
                    "server_name": str(server_name or "MCP")[:255],
                    "risk": str(risk or "unknown")[:30],
                    "input_summary": json.dumps(
                        input_summary,
                        ensure_ascii=False,
                        default=str,
                    ),
                    "expires_at": _timestamp(expires_at),
                    "created_at": _timestamp(now),
                    "updated_at": _timestamp(now),
                },
            )
            row = conn.execute(
                text(
                    """
                    SELECT * FROM agent_tool_operation
                    WHERE run_id=:run_id AND tool_call_id=:tool_call_id
                      AND user_id=:user_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                    "user_id": user_id,
                },
            ).mappings().first()
        if row is None:
            raise RuntimeError("Agent tool operation was not created.")
        return self._normalize(dict(row))

    def resolve(
        self,
        user_id: int,
        approval_id: str,
        decision: str,
    ) -> dict[str, Any] | None:
        if decision not in {"allow_once", "deny", "timeout"}:
            return None
        now = self.clock()
        with self.database.engine.begin() as conn:
            row = self._row(conn, user_id, approval_id)
            if row is None:
                return None
            if row["status"] != "waiting":
                if decision == "timeout" and row["status"] == "expired":
                    return self._normalize(row)
                return None
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
            if decision == "timeout" or now >= expires_at:
                conn.execute(
                    text(
                        """
                        UPDATE agent_tool_operation
                        SET status='expired', decision='timeout',
                            resolved_at=:now, updated_at=:now
                        WHERE id=:approval_id AND user_id=:user_id
                          AND status='waiting'
                        """
                    ),
                    {
                        "now": _timestamp(now),
                        "approval_id": approval_id,
                        "user_id": user_id,
                    },
                )
                updated = self._row(conn, user_id, approval_id)
                return self._normalize(updated) if updated else None
            status = "approved" if decision == "allow_once" else "denied"
            result = conn.execute(
                text(
                    """
                    UPDATE agent_tool_operation
                    SET status=:status, decision=:decision,
                        resolved_at=:now, updated_at=:now
                    WHERE id=:approval_id AND user_id=:user_id
                      AND status='waiting'
                    """
                ),
                {
                    "status": status,
                    "decision": decision,
                    "now": _timestamp(now),
                    "approval_id": approval_id,
                    "user_id": user_id,
                },
            )
            if result.rowcount != 1:
                return None
            updated = self._row(conn, user_id, approval_id)
        return self._normalize(updated) if updated else None

    def expire_due(self, *, limit: int = 100) -> int:
        now = self.clock()
        current = _timestamp(now)
        expired = 0
        with self.database.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, user_id
                    FROM agent_tool_operation
                    WHERE status='waiting' AND expires_at<=:current
                    ORDER BY expires_at, id
                    LIMIT :limit
                    """
                ),
                {
                    "current": current,
                    "limit": max(1, int(limit)),
                },
            ).mappings().all()
            for row in rows:
                result = conn.execute(
                    text(
                        """
                        UPDATE agent_tool_operation
                        SET status='expired', decision='timeout',
                            resolved_at=:now, updated_at=:now
                        WHERE id=:approval_id AND user_id=:user_id
                          AND status='waiting'
                        """
                    ),
                    {
                        "now": current,
                        "approval_id": row["id"],
                        "user_id": row["user_id"],
                    },
                )
                expired += max(0, int(result.rowcount or 0))
        return expired

    def resumable_resolutions(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT operation.*
                    FROM agent_tool_operation AS operation
                    JOIN agent_run AS run
                      ON run.id=operation.run_id
                     AND run.user_id=operation.user_id
                    WHERE operation.status IN (
                      'approved', 'denied', 'expired'
                    )
                      AND operation.decision IS NOT NULL
                      AND run.status='waiting_approval'
                      AND NOT EXISTS (
                        SELECT 1
                        FROM agent_tool_operation AS waiting
                        WHERE waiting.run_id=operation.run_id
                          AND waiting.user_id=operation.user_id
                          AND waiting.status='waiting'
                      )
                      AND operation.id=(
                        SELECT latest.id
                        FROM agent_tool_operation AS latest
                        WHERE latest.run_id=operation.run_id
                          AND latest.user_id=operation.user_id
                          AND latest.status IN (
                            'approved', 'denied', 'expired'
                          )
                        ORDER BY latest.resolved_at DESC,
                          latest.created_at DESC, latest.id DESC
                        LIMIT 1
                      )
                    ORDER BY operation.resolved_at, operation.id
                    LIMIT :limit
                    """
                ),
                {"limit": max(1, int(limit))},
            ).mappings().all()
        return [self._normalize(dict(row)) for row in rows]

    def get_for_run(
        self,
        user_id: int,
        run_id: str,
        *,
        statuses: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT * FROM agent_tool_operation
                    WHERE user_id=:user_id AND run_id=:run_id
                    ORDER BY created_at, id
                    """
                ),
                {"user_id": user_id, "run_id": run_id},
            ).mappings().all()
        normalized = [self._normalize(dict(row)) for row in rows]
        if statuses is None:
            return normalized
        return [item for item in normalized if item["status"] in statuses]

    def get(self, user_id: int, approval_id: str) -> dict[str, Any] | None:
        with self.database.engine.connect() as conn:
            row = self._row(conn, user_id, approval_id)
        return self._normalize(row) if row else None

    def get_for_call(
        self,
        user_id: int,
        run_id: str,
        tool_call_id: str,
    ) -> dict[str, Any] | None:
        with self.database.engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT * FROM agent_tool_operation
                    WHERE user_id=:user_id AND run_id=:run_id
                      AND tool_call_id=:tool_call_id
                    """
                ),
                {
                    "user_id": user_id,
                    "run_id": run_id,
                    "tool_call_id": tool_call_id,
                },
            ).mappings().first()
        return self._normalize(dict(row)) if row else None

    def cancel_for_run(self, user_id: int, run_id: str) -> int:
        now = _timestamp(self.clock())
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_tool_operation
                    SET status='cancelled', decision='cancelled',
                        resolved_at=:now, updated_at=:now
                    WHERE user_id=:user_id AND run_id=:run_id
                      AND status='waiting'
                    """
                ),
                {
                    "now": now,
                    "user_id": user_id,
                    "run_id": run_id,
                },
            )
        return int(result.rowcount or 0)

    def claim_execution(
        self,
        user_id: int,
        approval_id: str,
    ) -> dict[str, Any] | None:
        now = _timestamp(self.clock())
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_tool_operation
                    SET status='executing', started_at=:now,
                        updated_at=:now
                    WHERE id=:approval_id AND user_id=:user_id
                      AND status='approved' AND decision='allow_once'
                    """
                ),
                {
                    "now": now,
                    "approval_id": approval_id,
                    "user_id": user_id,
                },
            )
            if result.rowcount != 1:
                return None
            row = self._row(conn, user_id, approval_id)
        return self._normalize(row) if row else None

    def finish_execution(
        self,
        user_id: int,
        approval_id: str,
        execution: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = str(execution.get("status") or "failed")
        final_status = "succeeded" if status == "success" else "failed"
        now = _timestamp(self.clock())
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_tool_operation
                    SET status=:status, execution_json=:execution_json,
                        finished_at=:now, updated_at=:now
                    WHERE id=:approval_id AND user_id=:user_id
                      AND status='executing'
                    """
                ),
                {
                    "status": final_status,
                    "execution_json": json.dumps(
                        execution,
                        ensure_ascii=False,
                        default=str,
                    ),
                    "now": now,
                    "approval_id": approval_id,
                    "user_id": user_id,
                },
            )
            if result.rowcount != 1:
                return None
            row = self._row(conn, user_id, approval_id)
        return self._normalize(row) if row else None


class AgentApprovalRunner:
    def __init__(
        self,
        *,
        store: AgentToolOperationStore,
        resume: Callable[[dict[str, Any]], bool],
        poll_interval: float = 1.0,
    ):
        self.store = store
        self.resume = resume
        self.poll_interval = max(0.05, float(poll_interval))
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def run_once(self) -> bool:
        expired = self.store.expire_due()
        resumed = False
        for operation in self.store.resumable_resolutions():
            try:
                resumed = bool(self.resume(operation)) or resumed
            except Exception as exc:
                logger.warning(
                    "Agent approval resume failed for %s: %s",
                    operation.get("approvalId"),
                    type(exc).__name__,
                )
        return bool(expired or resumed)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            processed = self.run_once()
            if processed:
                continue
            self._wake_event.wait(self.poll_interval)
            self._wake_event.clear()

    def start(self) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="knowflow-agent-approvals",
            daemon=True,
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join()
        self._thread = None
