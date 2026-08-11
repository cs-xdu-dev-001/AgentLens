from __future__ import annotations

from threading import Event
from typing import Any, Callable

from .agent_event_protocol import AgentEventNormalizer
from .agent_execution import AgentEventSink, AgentExecution


class AgentApplicationService:
    """Transport-neutral facade over the existing Agent runtime."""

    def __init__(
        self,
        *,
        execute_agent: Callable[..., dict[str, Any]],
        execute_persisted: Callable[..., None],
        approval_store: Any,
        run_store: Any,
    ):
        self._execute_agent = execute_agent
        self._execute_persisted = execute_persisted
        self._approval_store = approval_store
        self._run_store = run_store

    @staticmethod
    def _named_event(name: str, value: dict[str, Any]) -> dict[str, Any]:
        payload = dict(value)
        detail_type = str(payload.pop("type", "") or "")
        event = {"type": name, **payload}
        if detail_type and detail_type != name:
            event["eventType"] = detail_type
        return event

    @staticmethod
    def _publish_result(
        result: dict[str, Any],
        emit: AgentEventSink,
    ) -> None:
        if result.get("paused"):
            return
        for call in result.get("toolCalls", []):
            emit({"type": "tool", **dict(call)})
        for reference in result.get("references", []):
            emit({"type": "reference", **dict(reference)})
        emit(
            {
                "type": "answer",
                "content": str(result.get("answer") or ""),
                "final": True,
            }
        )
        emit(
            {
                "type": "done",
                "runId": result.get("runId"),
                "sessionId": result.get("sessionId"),
                "messageId": result.get("messageId"),
                "run": result.get("run"),
                "trace": result.get("trace") or [],
                "memoryActivity": result.get("memoryActivity"),
            }
        )

    def run(
        self,
        payload: Any,
        user_id: int,
        *,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        events: list[dict[str, Any]] = []
        normalize = AgentEventNormalizer()

        def emit(event: dict[str, Any]) -> None:
            public = normalize(event)
            events.append(public)
            if event_sink is not None:
                event_sink(public)

        result = self._execute_agent(
            payload,
            user_id,
            event_emit=lambda name, value: emit(
                self._named_event(name, value)
            ),
        )
        self._publish_result(result, emit)
        return AgentExecution(result=result, events=events)

    def resolve_approval(
        self,
        *,
        user_id: int,
        run_id: str,
        approval_id: str,
        decision: str,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        operation = self._approval_store.resolve(
            user_id,
            approval_id,
            decision,
        )
        if operation is None or str(operation.get("runId")) != run_id:
            raise ValueError("Approval is unavailable for this Agent run.")
        events: list[dict[str, Any]] = []
        normalize = AgentEventNormalizer(run_id)

        def emit(event: dict[str, Any]) -> None:
            public = normalize(event)
            events.append(public)
            if event_sink is not None:
                event_sink(public)

        self._execute_persisted(
            user_id,
            run_id,
            f"approval:{approval_id}",
            Event(),
            emit,
        )
        return self._execution_from_events(
            user_id=user_id,
            run_id=run_id,
            events=events,
        )

    def resume(
        self,
        *,
        user_id: int,
        run_id: str,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        events: list[dict[str, Any]] = []
        normalize = AgentEventNormalizer(run_id)

        def emit(event: dict[str, Any]) -> None:
            public = normalize(event)
            events.append(public)
            if event_sink is not None:
                event_sink(public)

        self._execute_persisted(
            user_id,
            run_id,
            "resume",
            Event(),
            emit,
        )
        return self._execution_from_events(
            user_id=user_id,
            run_id=run_id,
            events=events,
        )

    def _execution_from_events(
        self,
        *,
        user_id: int,
        run_id: str,
        events: list[dict[str, Any]],
    ) -> AgentExecution:
        snapshot = self._run_store.get_snapshot(user_id, run_id) or {}
        answer = "".join(
            str(event.get("content") or "")
            for event in events
            if event.get("type") == "answer"
        )
        result = {
            "paused": snapshot.get("status") == "waiting_approval",
            "runId": run_id,
            "sessionId": snapshot.get("sessionId"),
            "messageId": snapshot.get("assistantMessageId"),
            "answer": answer,
            "run": snapshot,
            "trace": snapshot.get("trace") or [],
            "toolCalls": [],
            "references": [],
            "memoryActivity": None,
        }
        return AgentExecution(result=result, events=events)
