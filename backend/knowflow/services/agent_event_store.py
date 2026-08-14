from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import threading
import time
from typing import Any

from sqlalchemy import text

from .agent_event_protocol import (
    normalize_agent_event,
    public_artifact_projection,
    public_run_summary_projection,
)
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
        if str(event.get("eventName") or "") in {
            "artifact.created",
            "artifact.updated",
        }:
            artifact = public_artifact_projection(event)
            if artifact is None:
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
            } | artifact
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
        safe_limit = max(1, min(int(limit), 5000))
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

    def artifacts_for_run(
        self,
        user_id: int,
        run_id: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return the latest public projection for each persisted artifact."""
        safe_limit = max(1, min(int(limit), 500))
        with self.database.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT event.payload_json
                    FROM agent_run_event AS event
                    JOIN agent_run AS run ON run.id=event.run_id
                    WHERE event.run_id=:run_id
                      AND run.user_id=:user_id
                      AND event.event_name IN (
                        'artifact.created', 'artifact.updated'
                      )
                    ORDER BY event.event_sequence
                    LIMIT :limit
                    """
                ),
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "limit": safe_limit,
                },
            ).mappings().all()
        artifacts: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                event = json.loads(str(row["payload_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            artifact = public_artifact_projection(event)
            if artifact is not None:
                identifier = str(artifact["artifactId"])
                artifacts[identifier] = {
                    **artifacts.get(identifier, {}),
                    **artifact,
                }
        return list(artifacts.values())

    def metadata_for_run(
        self,
        user_id: int,
        run_id: str,
        *,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Rebuild durable UI metadata without replaying the full run."""
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
                      AND event.event_name IN (
                        'artifact.created', 'artifact.updated',
                        'usage.updated', 'error.raised',
                        'context.usage_updated', 'context.compacted',
                        'run.failed', 'step.failed', 'tool.failed',
                        'tool.started', 'tool.waiting',
                        'tool.completed', 'tool.cancelled',
                        'run.completed', 'run.cancelled',
                        'run.started', 'run.updated', 'run.plan_created'
                      )
                    ORDER BY event.event_sequence
                    LIMIT :limit
                    """
                ),
                {
                    "run_id": run_id,
                    "user_id": user_id,
                    "limit": safe_limit,
                },
            ).mappings().all()
        artifacts: dict[str, dict[str, Any]] = {}
        usage: dict[str, Any] = {}
        context: dict[str, Any] = {}
        recovery_actions: list[str] = []
        run_summary: dict[str, Any] = {}
        tool_calls: dict[str, dict[str, Any]] = {}
        for row in rows:
            try:
                event = json.loads(str(row["payload_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            event_name = str(event.get("eventName") or "")
            if event_name in {"artifact.created", "artifact.updated"}:
                artifact = public_artifact_projection(event)
                if artifact is not None:
                    identifier = str(artifact["artifactId"])
                    artifacts[identifier] = {
                        **artifacts.get(identifier, {}),
                        **artifact,
                    }
            if event_name == "usage.updated":
                event_usage = event.get("usage")
                if isinstance(event_usage, dict):
                    usage.update(event_usage)
            if event_name.startswith("tool."):
                identifier = str(
                    event.get("toolCallId")
                    or event.get("eventId")
                    or ""
                )
                if identifier:
                    tool_calls[identifier] = {
                        **tool_calls.get(identifier, {}),
                        **event,
                        "toolCallId": identifier,
                        "status": (
                            event.get("normalizedStatus")
                            or event.get("status")
                            or event_name.removeprefix("tool.")
                        ),
                    }
            if event_name in {
                "context.usage_updated",
                "context.compacted",
            }:
                context.update({
                    key: event.get(key)
                    for key in (
                        "usedTokens",
                        "originalTokens",
                        "maxTokens",
                        "remainingTokens",
                        "usageRatio",
                        "usagePercent",
                        "warningAtPercent",
                        "autoCompactAtPercent",
                        "shouldWarn",
                        "shouldAutoCompact",
                        "contextTrimmed",
                        "messageCount",
                        "reason",
                    )
                    if event.get(key) is not None
                })
                if event_name == "context.compacted":
                    context["compacted"] = True
            actions = event.get("recoveryActions")
            if isinstance(actions, list):
                recovery_actions = list(dict.fromkeys(
                    str(action)
                    for action in actions
                    if str(action)
                ))
            if event_name in {"run.completed", "run.cancelled"}:
                recovery_actions = []
            summary = public_run_summary_projection(event)
            if summary is not None:
                run_summary.update(summary)
        return {
            "artifacts": list(artifacts.values()),
            "usage": usage,
            "context": context,
            "toolCalls": list(tool_calls.values()),
            "recoveryActions": recovery_actions,
            "runSummary": run_summary or None,
        }
