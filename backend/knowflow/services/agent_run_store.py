from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from sqlalchemy import text


RUN_TRANSITIONS: dict[str, set[str]] = {
    "planning": {"waiting_start", "running", "failed", "cancelled"},
    "waiting_start": {"planning", "running", "cancelled"},
    "running": {
        "waiting_approval",
        "interrupted",
        "completed",
        "failed",
        "cancelled",
    },
    "waiting_approval": {
        "running",
        "interrupted",
        "failed",
        "cancelled",
    },
    "interrupted": {"running", "cancelled"},
    "completed": set(),
    "failed": {"running"},
    "cancelled": set(),
}

STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "skipped", "cancelled"},
    "running": {
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    },
    "waiting_approval": {
        "running",
        "failed",
        "cancelled",
    },
    "completed": set(),
    "failed": {"running", "skipped", "cancelled"},
    "skipped": set(),
    "cancelled": set(),
}

ACTIVE_RUN_STATUSES = {
    "planning",
    "running",
    "waiting_approval",
}


class AgentRunStoreError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).replace(
        tzinfo=None,
        microsecond=0,
    ).isoformat(sep=" ")


def _json_value(raw: Any, fallback: Any) -> Any:
    if raw in {None, ""}:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return fallback


class AgentRunStore:
    def __init__(self, *, database):
        self.database = database

    @staticmethod
    def _normalize_step(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "position": int(row["position"]),
            "title": row["title"],
            "status": row["status"],
            "kind": row["kind"],
            "toolName": row.get("tool_name"),
            "inputSummary": row.get("input_summary"),
            "outputSummary": row.get("output_summary"),
            "errorCode": row.get("error_code"),
            "attemptCount": int(row.get("attempt_count") or 0),
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
    def _normalize_run(
        row: dict[str, Any],
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "id": row["id"],
            "sessionId": row["session_id"],
            "userMessageId": row.get("user_message_id"),
            "assistantMessageId": row.get("assistant_message_id"),
            "goalSummary": row["goal_summary"],
            "triggerMode": row["trigger_mode"],
            "status": row["status"],
            "currentStepId": row.get("current_step_id"),
            "trace": _json_value(row.get("trace_json"), []),
            "version": int(row.get("version") or 1),
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
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "steps": steps,
        }

    @staticmethod
    def _mappings(result) -> list[dict[str, Any]]:
        return [dict(row) for row in result.mappings().all()]

    def _run_row(
        self,
        conn,
        user_id: int,
        run_id: str,
    ) -> dict[str, Any] | None:
        row = conn.execute(
            text(
                """
                SELECT *
                FROM agent_run
                WHERE id=:run_id AND user_id=:user_id
                """
            ),
            {"run_id": run_id, "user_id": user_id},
        ).mappings().first()
        return dict(row) if row else None

    def _step_rows(self, conn, run_id: str) -> list[dict[str, Any]]:
        return self._mappings(
            conn.execute(
                text(
                    """
                    SELECT *
                    FROM agent_run_step
                    WHERE run_id=:run_id
                    ORDER BY position
                    """
                ),
                {"run_id": run_id},
            )
        )

    def create_run(
        self,
        *,
        user_id: int,
        session_id: str,
        user_message_id: int | None,
        goal_summary: str,
        trigger_mode: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        identifier = run_id or f"run_{uuid.uuid4().hex[:12]}"
        now = _now()
        with self.database.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO agent_run(
                      id, user_id, session_id, user_message_id,
                      goal_summary, trigger_mode, status, trace_json,
                      version, created_at, updated_at
                    )
                    VALUES (
                      :id, :user_id, :session_id, :user_message_id,
                      :goal_summary, :trigger_mode, 'planning', '[]',
                      1, :created_at, :updated_at
                    )
                    """
                ),
                {
                    "id": identifier,
                    "user_id": user_id,
                    "session_id": session_id,
                    "user_message_id": user_message_id,
                    "goal_summary": str(goal_summary)[:700],
                    "trigger_mode": trigger_mode,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            row = self._run_row(conn, user_id, identifier)
        if row is None:
            raise AgentRunStoreError(
                "agent_run_not_found",
                "Agent run could not be created.",
            )
        return self._normalize_run(row, [])

    def get_snapshot(
        self,
        user_id: int,
        run_id: str,
    ) -> dict[str, Any] | None:
        with self.database.engine.connect() as conn:
            row = self._run_row(conn, user_id, run_id)
            if row is None:
                return None
            steps = [
                self._normalize_step(item)
                for item in self._step_rows(conn, run_id)
            ]
        return self._normalize_run(row, steps)

    def replace_plan(
        self,
        user_id: int,
        run_id: str,
        steps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not 2 <= len(steps) <= 8:
            raise AgentRunStoreError(
                "invalid_agent_plan",
                "Agent plans must contain between 2 and 8 steps.",
            )
        now = _now()
        with self.database.engine.begin() as conn:
            run = self._run_row(conn, user_id, run_id)
            if run is None:
                raise AgentRunStoreError(
                    "agent_run_not_found",
                    "Agent run was not found.",
                )
            if run["status"] not in {"planning", "waiting_start"}:
                raise AgentRunStoreError(
                    "illegal_run_transition",
                    "The plan cannot be replaced in its current state.",
                )
            conn.execute(
                text(
                    "DELETE FROM agent_run_step WHERE run_id=:run_id"
                ),
                {"run_id": run_id},
            )
            for position, item in enumerate(steps, start=1):
                title = " ".join(str(item.get("title") or "").split())
                kind = str(item.get("kind") or "")
                if not title or len(title) > 80:
                    raise AgentRunStoreError(
                        "invalid_agent_plan",
                        "Agent plan titles must be between 1 and 80 characters.",
                    )
                if kind not in {
                    "reasoning",
                    "tool",
                    "mcp",
                    "skill",
                    "answer",
                }:
                    raise AgentRunStoreError(
                        "invalid_agent_plan",
                        "Agent plan step kind is invalid.",
                    )
                conn.execute(
                    text(
                        """
                        INSERT INTO agent_run_step(
                          id, run_id, position, title, status, kind,
                          tool_name, input_summary, attempt_count,
                          created_at, updated_at
                        )
                        VALUES (
                          :id, :run_id, :position, :title, 'pending',
                          :kind, :tool_name, :input_summary, 0,
                          :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": f"plan_{uuid.uuid4().hex[:12]}",
                        "run_id": run_id,
                        "position": position,
                        "title": title,
                        "kind": kind,
                        "tool_name": (
                            str(item["tool_name"])[:160]
                            if item.get("tool_name")
                            else None
                        ),
                        "input_summary": (
                            str(item["input_summary"])[:700]
                            if item.get("input_summary") is not None
                            else None
                        ),
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            rows = self._step_rows(conn, run_id)
        return [self._normalize_step(row) for row in rows]

    def transition_run(
        self,
        user_id: int,
        run_id: str,
        status: str,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.engine.begin() as conn:
            run = self._run_row(conn, user_id, run_id)
            if run is None:
                raise AgentRunStoreError(
                    "agent_run_not_found",
                    "Agent run was not found.",
                )
            current = str(run["status"])
            if status not in RUN_TRANSITIONS.get(current, set()):
                raise AgentRunStoreError(
                    "illegal_run_transition",
                    f"Cannot transition Agent run from {current} to {status}.",
                )
            terminal = status in {"completed", "failed", "cancelled"}
            started_at = (
                now
                if status == "running" and run.get("started_at") is None
                else run.get("started_at")
            )
            result = conn.execute(
                text(
                    """
                    UPDATE agent_run
                    SET status=:status, started_at=:started_at,
                        finished_at=:finished_at,
                        version=version + 1, updated_at=:updated_at
                    WHERE id=:run_id AND user_id=:user_id
                      AND version=:version
                    """
                ),
                {
                    "status": status,
                    "started_at": started_at,
                    "finished_at": now if terminal else None,
                    "updated_at": now,
                    "run_id": run_id,
                    "user_id": user_id,
                    "version": run["version"],
                },
            )
            if result.rowcount != 1:
                raise AgentRunStoreError(
                    "agent_run_conflict",
                    "Agent run was updated concurrently.",
                )
            updated = self._run_row(conn, user_id, run_id)
            steps = self._step_rows(conn, run_id)
        if updated is None:
            raise AgentRunStoreError(
                "agent_run_not_found",
                "Agent run was not found.",
            )
        return self._normalize_run(
            updated,
            [self._normalize_step(item) for item in steps],
        )

    def transition_step(
        self,
        user_id: int,
        run_id: str,
        step_id: str,
        status: str,
        *,
        output_summary: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        now = _now()
        with self.database.engine.begin() as conn:
            run = self._run_row(conn, user_id, run_id)
            if run is None:
                raise AgentRunStoreError(
                    "agent_run_not_found",
                    "Agent run was not found.",
                )
            row = conn.execute(
                text(
                    """
                    SELECT *
                    FROM agent_run_step
                    WHERE id=:step_id AND run_id=:run_id
                    """
                ),
                {"step_id": step_id, "run_id": run_id},
            ).mappings().first()
            if row is None:
                raise AgentRunStoreError(
                    "agent_run_step_not_found",
                    "Agent run step was not found.",
                )
            current = str(row["status"])
            if status not in STEP_TRANSITIONS.get(current, set()):
                raise AgentRunStoreError(
                    "illegal_step_transition",
                    f"Cannot transition Agent step from {current} to {status}.",
                )
            terminal = status in {
                "completed",
                "failed",
                "skipped",
                "cancelled",
            }
            started_at = (
                now
                if status == "running" and row.get("started_at") is None
                else row.get("started_at")
            )
            conn.execute(
                text(
                    """
                    UPDATE agent_run_step
                    SET status=:status, output_summary=:output_summary,
                        error_code=:error_code, started_at=:started_at,
                        finished_at=:finished_at,
                        attempt_count=attempt_count + :attempt_increment,
                        updated_at=:updated_at
                    WHERE id=:step_id AND run_id=:run_id
                    """
                ),
                {
                    "status": status,
                    "output_summary": (
                        str(output_summary)[:700]
                        if output_summary is not None
                        else row.get("output_summary")
                    ),
                    "error_code": error_code,
                    "started_at": started_at,
                    "finished_at": now if terminal else None,
                    "attempt_increment": 1 if status == "running" else 0,
                    "updated_at": now,
                    "step_id": step_id,
                    "run_id": run_id,
                },
            )
            if status in {"running", "waiting_approval"}:
                conn.execute(
                    text(
                        """
                        UPDATE agent_run
                        SET current_step_id=:step_id,
                            version=version + 1, updated_at=:updated_at
                        WHERE id=:run_id AND user_id=:user_id
                        """
                    ),
                    {
                        "step_id": step_id,
                        "updated_at": now,
                        "run_id": run_id,
                        "user_id": user_id,
                    },
                )
            updated = conn.execute(
                text(
                    """
                    SELECT *
                    FROM agent_run_step
                    WHERE id=:step_id AND run_id=:run_id
                    """
                ),
                {"step_id": step_id, "run_id": run_id},
            ).mappings().first()
        if updated is None:
            raise AgentRunStoreError(
                "agent_run_step_not_found",
                "Agent run step was not found.",
            )
        return self._normalize_step(dict(updated))

    def update_trace(
        self,
        user_id: int,
        run_id: str,
        trace: list[dict[str, Any]],
    ) -> None:
        now = _now()
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE agent_run
                    SET trace_json=:trace_json, version=version + 1,
                        updated_at=:updated_at
                    WHERE id=:run_id AND user_id=:user_id
                    """
                ),
                {
                    "trace_json": json.dumps(
                        trace,
                        ensure_ascii=False,
                        default=str,
                    ),
                    "updated_at": now,
                    "run_id": run_id,
                    "user_id": user_id,
                },
            )
            if result.rowcount != 1:
                raise AgentRunStoreError(
                    "agent_run_not_found",
                    "Agent run was not found.",
                )

    def interrupt_stale_runs(self) -> int:
        now = _now()
        with self.database.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE agent_run_step
                    SET status='failed',
                        error_code='service_restart_interrupted',
                        finished_at=:finished_at,
                        updated_at=:updated_at
                    WHERE status IN ('running', 'waiting_approval')
                      AND run_id IN (
                        SELECT id FROM agent_run
                        WHERE status IN (
                          'planning', 'running', 'waiting_approval'
                        )
                      )
                    """
                ),
                {"finished_at": now, "updated_at": now},
            )
            result = conn.execute(
                text(
                    """
                    UPDATE agent_run
                    SET status='interrupted', finished_at=NULL,
                        version=version + 1, updated_at=:updated_at
                    WHERE status IN (
                      'planning', 'running', 'waiting_approval'
                    )
                    """
                ),
                {"updated_at": now},
            )
            return max(0, int(result.rowcount or 0))
