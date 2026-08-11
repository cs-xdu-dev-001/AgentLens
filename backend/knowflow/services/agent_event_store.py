from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any

from sqlalchemy import text

from .agent_event_protocol import normalize_agent_event
from .agent_trace import sanitize_trace_value


TRANSIENT_EVENT_NAMES = frozenset({"message.delta", "tool.progress"})
MAX_EVENT_CHARS = 1_000_000
DEFAULT_RETENTION_DAYS = 30


class AgentEventStore:
    """Append-only store for public, replayable Agent events."""

    _cleanup_lock = threading.Lock()
    _last_cleanup: dict[int, float] = {}

    def __init__(
        self,
        *,
        database,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        cleanup_interval_seconds: int = 300,
    ) -> None:
        self.database = database
        self.retention_days = max(1, int(retention_days))
        self.cleanup_interval_seconds = max(
            60,
            int(cleanup_interval_seconds),
        )

    @staticmethod
    def should_persist(event: dict[str, Any]) -> bool:
        return str(event.get("eventName") or "") not in TRANSIENT_EVENT_NAMES

    @staticmethod
    def _safe_payload(event: dict[str, Any]) -> dict[str, Any]:
        serialized = sanitize_trace_value(event, max_chars=MAX_EVENT_CHARS)
        if serialized:
            try:
                value = json.loads(serialized)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
        return {
            key: event.get(key)
            for key in (
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
        } | {"payloadTruncated": True}

    def latest_sequence(self, run_id: str) -> int:
        with self.database.engine.connect() as conn:
            value = conn.execute(
                text(
                    """
                    SELECT MAX(event_sequence)
                    FROM agent_run_event
                    WHERE run_id=:run_id
                    """
                ),
                {"run_id": run_id},
            ).scalar()
        return max(0, int(value or 0))

    def append(self, run_id: str, event: dict[str, Any]) -> bool:
        self._cleanup_if_due()
        public = normalize_agent_event(event, run_id=run_id)
        if not self.should_persist(public):
            return False
        sequence = int(public.get("sequence") or 0)
        if sequence < 1:
            raise ValueError("Persisted Agent events require a sequence.")
        public["runId"] = run_id
        public["sequence"] = sequence
        payload = self._safe_payload(public)
        params = {
            "id": str(public["eventId"]),
            "run_id": run_id,
            "sequence": sequence,
            "event_name": str(public["eventName"]),
            "payload_json": json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
            ),
            "occurred_at": str(public["occurredAt"]),
        }
        if self.database.is_mysql:
            statement = """
                INSERT IGNORE INTO agent_run_event(
                  id, run_id, event_sequence, event_name,
                  payload_json, occurred_at
                ) VALUES (
                  :id, :run_id, :sequence, :event_name,
                  :payload_json, :occurred_at
                )
            """
        else:
            statement = """
                INSERT OR IGNORE INTO agent_run_event(
                  id, run_id, event_sequence, event_name,
                  payload_json, occurred_at
                ) VALUES (
                  :id, :run_id, :sequence, :event_name,
                  :payload_json, :occurred_at
                )
            """
        with self.database.engine.begin() as conn:
            result = conn.execute(text(statement), params)
        return result.rowcount == 1

    def _cleanup_if_due(self) -> None:
        current = time.monotonic()
        key = id(self.database.engine)
        with self._cleanup_lock:
            previous = self._last_cleanup.get(key, 0.0)
            if current - previous < self.cleanup_interval_seconds:
                return
            self._last_cleanup[key] = current
        self.cleanup_expired()

    def cleanup_expired(
        self,
        *,
        now: datetime | None = None,
        max_runs: int = 100,
    ) -> int:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is not None:
            current = current.astimezone(timezone.utc).replace(tzinfo=None)
        cutoff = current - timedelta(days=self.retention_days)
        with self.database.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT id
                    FROM agent_run
                    WHERE status IN (
                      'completed', 'failed', 'cancelled'
                    )
                      AND updated_at < :cutoff
                    ORDER BY updated_at
                    LIMIT :limit
                    """
                ),
                {
                    "cutoff": cutoff,
                    "limit": max(1, min(int(max_runs), 1000)),
                },
            ).mappings().all()
            removed = 0
            for row in rows:
                result = conn.execute(
                    text(
                        """
                        DELETE FROM agent_run_event
                        WHERE run_id=:run_id
                        """
                    ),
                    {"run_id": str(row["id"])},
                )
                removed += max(0, int(result.rowcount or 0))
        return removed

    def list_after(
        self,
        user_id: int,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT event.payload_json
                    FROM agent_run_event AS event
                    JOIN agent_run AS run ON run.id=event.run_id
                    WHERE event.run_id=:run_id
                      AND run.user_id=:user_id
                      AND event.event_sequence>:after_sequence
                    ORDER BY event.event_sequence
                    LIMIT :limit
                    """
                ),
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "after_sequence": max(0, int(after_sequence)),
                    "limit": safe_limit,
                },
            ).mappings().all()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(str(row["payload_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                events.append(value)
        return events
