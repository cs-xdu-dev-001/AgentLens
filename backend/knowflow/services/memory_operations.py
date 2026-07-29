from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
import uuid

from sqlalchemy import text


class MemoryOperationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _time(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current.replace(microsecond=0).isoformat(sep=" ")


def _json_value(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return fallback


def _content(item: dict[str, Any]) -> str:
    return str(
        item.get("memory")
        or item.get("content")
        or item.get("text")
        or ""
    ).strip()


def _memory_id(item: dict[str, Any]) -> str:
    return str(
        item.get("id")
        or item.get("memory_id")
        or item.get("memoryId")
        or ""
    ).strip()


def _normalize_items(
    items: list[dict[str, Any]] | None,
    *,
    default_action: str,
) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        event = str(
            raw.get("event")
            or raw.get("action")
            or default_action
        ).strip().lower()
        action = {
            "add": "add",
            "added": "add",
            "update": "update",
            "updated": "update",
            "delete": "delete",
            "deleted": "delete",
            "recall": "recall",
        }.get(event, default_action)
        normalized.append(
            {
                "memoryId": _memory_id(raw),
                "action": action,
                "content": _content(raw)[:700],
            }
        )
    return normalized


class MemoryOperationStore:
    def __init__(self, *, database):
        self.database = database

    @staticmethod
    def _operation(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "messageId": int(row["message_id"]),
            "agentRunId": row.get("agent_run_id"),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "attemptCount": int(row.get("attempt_count") or 0),
            "nextAttemptAt": (
                str(row["next_attempt_at"])
                if row.get("next_attempt_at") is not None
                else None
            ),
            "items": _json_value(row.get("result_json"), []),
            "errorCode": row.get("error_code"),
            "errorMessage": row.get("error_message"),
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
    def _summary(operations: list[dict[str, Any]]) -> dict[str, int]:
        counts = {
            "recalled": 0,
            "added": 0,
            "updated": 0,
            "deleted": 0,
        }
        for operation in operations:
            for item in operation.get("items") or []:
                action = str(item.get("action") or "")
                key = {
                    "recall": "recalled",
                    "add": "added",
                    "update": "updated",
                    "delete": "deleted",
                }.get(action)
                if key:
                    counts[key] += 1
        return counts

    def create_for_message(
        self,
        *,
        user_id: int,
        session_id: str,
        message_id: int,
        agent_run_id: str | None,
        recalled: list[dict[str, Any]],
    ) -> tuple[str, str]:
        now = _time()
        with self.database.engine.begin() as conn:
            existing = conn.execute(
                text(
                    """
                    SELECT id, kind
                    FROM memory_operation
                    WHERE user_id=:user_id AND message_id=:message_id
                      AND kind IN ('recall', 'write')
                    """
                ),
                {"user_id": int(user_id), "message_id": int(message_id)},
            ).mappings().all()
            identifiers = {
                str(row["kind"]): str(row["id"])
                for row in existing
            }
            if "recall" not in identifiers:
                identifiers["recall"] = f"memop_{uuid.uuid4().hex[:16]}"
                conn.execute(
                    text(
                        """
                        INSERT INTO memory_operation(
                          id, user_id, session_id, message_id, agent_run_id,
                          kind, status, attempt_count, result_json,
                          started_at, finished_at, created_at, updated_at
                        )
                        VALUES (
                          :id, :user_id, :session_id, :message_id,
                          :agent_run_id, 'recall', 'succeeded', 1,
                          :result_json, :started_at, :finished_at,
                          :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": identifiers["recall"],
                        "user_id": int(user_id),
                        "session_id": str(session_id),
                        "message_id": int(message_id),
                        "agent_run_id": agent_run_id,
                        "result_json": json.dumps(
                            _normalize_items(
                                recalled,
                                default_action="recall",
                            ),
                            ensure_ascii=False,
                        ),
                        "started_at": now,
                        "finished_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            if "write" not in identifiers:
                identifiers["write"] = f"memop_{uuid.uuid4().hex[:16]}"
                conn.execute(
                    text(
                        """
                        INSERT INTO memory_operation(
                          id, user_id, session_id, message_id, agent_run_id,
                          kind, status, attempt_count, result_json,
                          next_attempt_at, created_at, updated_at
                        )
                        VALUES (
                          :id, :user_id, :session_id, :message_id,
                          :agent_run_id, 'write', 'queued', 0, '[]',
                          :next_attempt_at, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "id": identifiers["write"],
                        "user_id": int(user_id),
                        "session_id": str(session_id),
                        "message_id": int(message_id),
                        "agent_run_id": agent_run_id,
                        "next_attempt_at": now,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
        return identifiers["recall"], identifiers["write"]

    def _rows_for_message(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> list[dict[str, Any]]:
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT *
                    FROM memory_operation
                    WHERE user_id=:user_id AND message_id=:message_id
                    ORDER BY CASE kind WHEN 'recall' THEN 0 ELSE 1 END
                    """
                ),
                {"user_id": int(user_id), "message_id": int(message_id)},
            ).mappings().all()
        return [dict(row) for row in rows]

    def activity_for_message(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        rows = self._rows_for_message(
            user_id=user_id,
            message_id=message_id,
        )
        if not rows:
            return None
        operations = [self._operation(row) for row in rows]
        return {
            "messageId": int(message_id),
            "summary": self._summary(operations),
            "operations": operations,
        }

    def activity_map_for_messages(
        self,
        *,
        user_id: int,
        message_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        return {
            int(message_id): activity
            for message_id in message_ids
            if (
                activity := self.activity_for_message(
                    user_id=user_id,
                    message_id=int(message_id),
                )
            )
            is not None
        }

    def claim_due(self, *, now: datetime) -> dict[str, Any] | None:
        current = _time(now)
        with self.database.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT *
                    FROM memory_operation
                    WHERE kind='write' AND status='queued'
                      AND (
                        next_attempt_at IS NULL
                        OR next_attempt_at<=:current
                      )
                    ORDER BY created_at, id
                    LIMIT 1
                    """
                ),
                {"current": current},
            ).mappings().first()
            if row is None:
                return None
            result = conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='running',
                        attempt_count=attempt_count + 1,
                        started_at=:started_at,
                        next_attempt_at=NULL,
                        error_code=NULL,
                        error_message=NULL,
                        updated_at=:updated_at
                    WHERE id=:id AND status='queued'
                    """
                ),
                {
                    "started_at": current,
                    "updated_at": current,
                    "id": row["id"],
                },
            )
            if result.rowcount != 1:
                return None
            claimed = conn.execute(
                text("SELECT * FROM memory_operation WHERE id=:id"),
                {"id": row["id"]},
            ).mappings().first()
        return self._operation(dict(claimed)) if claimed else None

    def reschedule(
        self,
        operation_id: str,
        *,
        error_code: str,
        error_message: str,
        next_attempt_at: datetime,
    ) -> None:
        now = _time()
        with self.database.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='queued', next_attempt_at=:next_attempt_at,
                        error_code=:error_code, error_message=:error_message,
                        finished_at=NULL, updated_at=:updated_at
                    WHERE id=:id AND kind='write'
                    """
                ),
                {
                    "next_attempt_at": _time(next_attempt_at),
                    "error_code": str(error_code)[:100],
                    "error_message": str(error_message)[:255],
                    "updated_at": now,
                    "id": str(operation_id),
                },
            )

    def mark_succeeded(
        self,
        operation_id: str,
        result: list[dict[str, Any]],
    ) -> None:
        now = _time()
        items = _normalize_items(result, default_action="add")
        with self.database.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='succeeded', result_json=:result_json,
                        next_attempt_at=NULL, error_code=NULL,
                        error_message=NULL, finished_at=:finished_at,
                        updated_at=:updated_at
                    WHERE id=:id AND kind='write'
                    """
                ),
                {
                    "result_json": json.dumps(
                        items,
                        ensure_ascii=False,
                    ),
                    "finished_at": now,
                    "updated_at": now,
                    "id": str(operation_id),
                },
            )

    def mark_failed(
        self,
        operation_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        now = _time()
        with self.database.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='failed', next_attempt_at=NULL,
                        error_code=:error_code, error_message=:error_message,
                        finished_at=:finished_at, updated_at=:updated_at
                    WHERE id=:id AND kind='write'
                    """
                ),
                {
                    "error_code": str(error_code)[:100],
                    "error_message": str(error_message)[:255],
                    "finished_at": now,
                    "updated_at": now,
                    "id": str(operation_id),
                },
            )

    def retry_failed(
        self,
        *,
        user_id: int,
        operation_id: str,
    ) -> dict[str, Any]:
        now = _time()
        with self.database.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT *
                    FROM memory_operation
                    WHERE id=:id AND user_id=:user_id AND kind='write'
                    """
                ),
                {"id": str(operation_id), "user_id": int(user_id)},
            ).mappings().first()
            if row is None:
                raise MemoryOperationError(
                    "memory_operation_not_found",
                    "Memory operation was not found.",
                )
            if row["status"] != "failed":
                raise MemoryOperationError(
                    "memory_operation_conflict",
                    "Only failed memory operations can be retried.",
                )
            conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='queued', attempt_count=0,
                        next_attempt_at=:next_attempt_at,
                        error_code=NULL, error_message=NULL,
                        started_at=NULL, finished_at=NULL,
                        updated_at=:updated_at
                    WHERE id=:id AND user_id=:user_id
                    """
                ),
                {
                    "next_attempt_at": now,
                    "updated_at": now,
                    "id": str(operation_id),
                    "user_id": int(user_id),
                },
            )
            updated = conn.execute(
                text(
                    """
                    SELECT *
                    FROM memory_operation
                    WHERE id=:id AND user_id=:user_id
                    """
                ),
                {"id": str(operation_id), "user_id": int(user_id)},
            ).mappings().first()
        return self._operation(dict(updated))

    def recover_interrupted(self, *, stale_before: datetime) -> int:
        now = _time()
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    UPDATE memory_operation
                    SET status='queued', next_attempt_at=:next_attempt_at,
                        error_code='memory_worker_interrupted',
                        error_message='记忆任务已在服务恢复后重新排队。',
                        finished_at=NULL, updated_at=:updated_at
                    WHERE kind='write' AND status='running'
                      AND started_at<=:stale_before
                    """
                ),
                {
                    "next_attempt_at": now,
                    "updated_at": now,
                    "stale_before": _time(stale_before),
                },
            )
            return max(0, int(result.rowcount or 0))

    def _redact(
        self,
        *,
        user_id: int,
        memory_id: str | None,
    ) -> None:
        now = _time()
        with self.database.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id, result_json
                    FROM memory_operation
                    WHERE user_id=:user_id
                    """
                ),
                {"user_id": int(user_id)},
            ).mappings().all()
            for row in rows:
                items = _json_value(row.get("result_json"), [])
                changed = False
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if (
                        memory_id is None
                        or str(item.get("memoryId") or "") == memory_id
                    ):
                        item["content"] = ""
                        changed = True
                if changed:
                    conn.execute(
                        text(
                            """
                            UPDATE memory_operation
                            SET result_json=:result_json,
                                updated_at=:updated_at
                            WHERE id=:id AND user_id=:user_id
                            """
                        ),
                        {
                            "result_json": json.dumps(
                                items,
                                ensure_ascii=False,
                            ),
                            "updated_at": now,
                            "id": row["id"],
                            "user_id": int(user_id),
                        },
                    )

    def redact_memory(self, *, user_id: int, memory_id: str) -> None:
        self._redact(user_id=user_id, memory_id=str(memory_id))

    def redact_user(self, *, user_id: int) -> None:
        self._redact(user_id=user_id, memory_id=None)

    def purge_expired(self, *, before: datetime) -> int:
        with self.database.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    DELETE FROM memory_operation
                    WHERE created_at<:before
                      AND status IN ('succeeded', 'failed')
                    """
                ),
                {"before": _time(before)},
            )
            return max(0, int(result.rowcount or 0))
