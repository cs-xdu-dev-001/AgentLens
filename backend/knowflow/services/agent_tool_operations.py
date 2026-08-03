from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import text


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
            "expiresAt": str(row["expires_at"]),
            "resolvedAt": (
                str(row["resolved_at"])
                if row.get("resolved_at") is not None
                else None
            ),
            "startedAt": (
                str(row["started_at"])
                if row.get("started_at") is not None
                else None
            ),
            "finishedAt": (
                str(row["finished_at"])
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
        if decision not in {"allow_once", "deny"}:
            return None
        now = self.clock()
        with self.database.engine.begin() as conn:
            row = self._row(conn, user_id, approval_id)
            if row is None or row["status"] != "waiting":
                return None
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
            if now >= expires_at:
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
                return None
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
