from __future__ import annotations

from collections.abc import Callable, Iterable
from queue import Empty
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.agent_event_protocol import normalize_agent_event
from ..services.agent_run_store import (
    ACTIVE_RUN_STATUSES,
    AgentRunStoreError,
    OPEN_RUN_STATUSES,
)
from ..runtime import (
    agent_run_coordinator,
    agent_run_events,
    agent_runs,
    agent_tool_operations,
    api_success,
    current_user_id,
    sse_event,
)


router = APIRouter()
_run_executor: Callable[..., None] | None = None


class AgentQuestionAnswer(BaseModel):
    questionId: str = Field(min_length=1, max_length=160)
    answer: str = Field(min_length=1, max_length=4000)
    selectedOptions: list[str] = Field(default_factory=list, max_length=4)


@router.get("/api/agent/runs")
def list_agent_runs(
    request: Request,
    limit: int = 20,
) -> dict[str, Any]:
    return api_success(
        agent_runs.list_recent(
            current_user_id(request),
            limit=limit,
        )
    )


def configure_agent_run_executor(executor: Callable[..., None]) -> None:
    global _run_executor
    _run_executor = executor


def _snapshot_or_404(user_id: int, run_id: str) -> dict[str, Any]:
    snapshot = agent_runs.get_snapshot(user_id, run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


def _runtime_snapshot_or_404(user_id: int, run_id: str) -> dict[str, Any]:
    snapshot = _snapshot_or_404(user_id, run_id)
    if (
        snapshot["status"] in OPEN_RUN_STATUSES
        and agent_run_events.has_event(user_id, run_id, "run.cancelling")
    ):
        return {**snapshot, "status": "cancelling"}
    return snapshot


def _closed_run_event(
    user_id: int,
    run_id: str,
) -> tuple[str, dict[str, Any]] | None:
    snapshot = _snapshot_or_404(user_id, run_id)
    if snapshot["status"] in ACTIVE_RUN_STATUSES - {
        "waiting_approval",
        "waiting_input",
    }:
        try:
            snapshot = agent_runs.transition_run(
                user_id,
                run_id,
                "failed",
            )
        except AgentRunStoreError:
            snapshot = _snapshot_or_404(user_id, run_id)
    if snapshot["status"] == "completed":
        return (
            "done",
            normalize_agent_event({
                "type": "done",
                "runId": run_id,
                "sessionId": snapshot.get("sessionId"),
                "messageId": snapshot.get("assistantMessageId"),
                "run": snapshot,
            }, run_id=run_id),
        )
    if snapshot["status"] == "cancelled":
        return (
            "cancelled",
            normalize_agent_event(
                {"type": "cancelled", "run": snapshot},
                run_id=run_id,
            ),
        )
    if snapshot["status"] == "failed":
        return (
            "error",
            normalize_agent_event({
                "type": "error",
                "code": "agent_run_failed",
                "message": "Agent run failed.",
                "run": snapshot,
            }, run_id=run_id),
        )
    return None


def _launch(user_id: int, run_id: str, action: str) -> dict[str, Any]:
    snapshot = _snapshot_or_404(user_id, run_id)
    allowed = {
        "start": {"waiting_start"},
        "replan": {"waiting_start"},
        "resume": {"interrupted", "failed", "waiting_approval"},
        "answer": {"waiting_input"},
        "restart": {"planning"},
    }[action]
    if snapshot["status"] not in allowed:
        raise HTTPException(
            status_code=409,
            detail="Agent run cannot perform this action.",
        )
    if _run_executor is None:
        raise HTTPException(
            status_code=503,
            detail="Agent run executor is unavailable.",
        )

    def target(cancel_event, publish) -> None:
        _run_executor(
            user_id,
            run_id,
            action,
            cancel_event,
            publish,
        )

    if not agent_run_coordinator.start(run_id, target):
        raise HTTPException(
            status_code=409,
            detail="Agent run is already active.",
        )
    return _snapshot_or_404(user_id, run_id)


@router.get("/api/agent/runs/{run_id}")
def read_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    snapshot = _runtime_snapshot_or_404(user_id, run_id)
    snapshot.update(agent_run_events.metadata_for_run(user_id, run_id))
    return api_success(snapshot)


@router.get("/api/agent/runs/{run_id}/events")
def stream_agent_run_events(
    run_id: str,
    request: Request,
    after_sequence: int = Query(
        0,
        alias="afterSequence",
        ge=0,
        le=9_223_372_036_854_775_807,
    ),
) -> StreamingResponse:
    user_id = current_user_id(request)
    snapshot = _runtime_snapshot_or_404(user_id, run_id)
    header_event_id = str(request.headers.get("last-event-id") or "")
    if header_event_id.isdigit() and len(header_event_id) <= 19:
        after_sequence = max(after_sequence, int(header_event_id))

    def generate() -> Iterable[str]:
        subscriber = agent_run_coordinator.subscribe(run_id)
        current_snapshot = _runtime_snapshot_or_404(user_id, run_id)
        last_sequence = after_sequence
        latest_persisted = agent_run_events.latest_sequence(run_id)
        terminal_seen = bool(
            latest_persisted
            and after_sequence >= latest_persisted
            and current_snapshot.get("status") in {
                "completed",
                "failed",
                "cancelled",
            }
        )
        while True:
            replay = agent_run_events.list_after(
                user_id,
                run_id,
                after_sequence=last_sequence,
                limit=500,
            )
            if not replay:
                break
            for event in replay:
                sequence = int(event.get("sequence") or 0)
                last_sequence = max(last_sequence, sequence)
                event_name = str(event.get("eventName") or "")
                terminal_seen = terminal_seen or event_name in {
                    "run.completed",
                    "run.cancelled",
                    "run.failed",
                    "error.raised",
                }
                yield sse_event(
                    str(event.get("type") or "run_updated"),
                    event,
                )
            if len(replay) < 500:
                break
        current_snapshot = _runtime_snapshot_or_404(user_id, run_id)
        yield sse_event(
            "run_snapshot",
            normalize_agent_event(
                {"type": "run_snapshot", "run": current_snapshot},
                run_id=run_id,
            ),
        )
        if subscriber is None:
            terminal_event = (
                None
                if terminal_seen
                else _closed_run_event(user_id, run_id)
            )
            if terminal_event:
                event_type, event = terminal_event
                yield sse_event(
                    event_type,
                    normalize_agent_event(event, run_id=run_id),
                )
            return
        try:
            while True:
                try:
                    event = subscriber.get(timeout=15)
                except Empty:
                    yield ": keep-alive\n\n"
                    continue
                event_type = str(event.get("type") or "run_updated")
                if event_type == "stream_closed":
                    terminal_event = (
                        None
                        if terminal_seen
                        else _closed_run_event(user_id, run_id)
                    )
                    if terminal_event:
                        final_type, final_event = terminal_event
                        yield sse_event(final_type, final_event)
                    break
                sequence = int(event.get("sequence") or 0)
                if sequence and sequence <= last_sequence:
                    continue
                last_sequence = max(last_sequence, sequence)
                event_name = str(event.get("eventName") or "")
                terminal_seen = terminal_seen or event_name in {
                    "run.completed",
                    "run.cancelled",
                    "run.failed",
                    "error.raised",
                }
                yield sse_event(event_type, event)
                if event_type in {"done", "error", "cancelled"}:
                    break
        finally:
            agent_run_coordinator.unsubscribe(run_id, subscriber)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/agent/runs/{run_id}/start")
def start_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    return api_success(
        _launch(current_user_id(request), run_id, "start")
    )


@router.post("/api/agent/runs/{run_id}/replan")
def replan_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    return api_success(
        _launch(current_user_id(request), run_id, "replan")
    )


@router.post("/api/agent/runs/{run_id}/resume")
def resume_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    return api_success(
        _launch(current_user_id(request), run_id, "resume")
    )


@router.post("/api/agent/runs/{run_id}/answer")
def answer_agent_question(
    run_id: str,
    payload: AgentQuestionAnswer,
    request: Request,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    answer_text = payload.answer.strip()
    if not answer_text:
        raise HTTPException(status_code=422, detail="Answer cannot be empty.")
    if _run_executor is None:
        raise HTTPException(
            status_code=503,
            detail="Agent run executor is unavailable.",
        )
    try:
        answer = agent_runs.resolve_question(
            user_id,
            run_id,
            question_id=payload.questionId,
            answer=answer_text,
            selected_options=[
                value.strip()[:120]
                for value in payload.selectedOptions
                if value.strip()
            ],
        )
    except AgentRunStoreError as exc:
        status_code = 404 if exc.code == "agent_run_not_found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    launched = _launch(user_id, run_id, "answer")
    return api_success({"run": launched, "answer": answer})


@router.post("/api/agent/runs/{run_id}/restart")
def restart_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    _snapshot_or_404(user_id, run_id)
    if _run_executor is None:
        raise HTTPException(
            status_code=503,
            detail="Agent run executor is unavailable.",
        )
    try:
        replacement = agent_runs.restart_run(user_id, run_id)
    except AgentRunStoreError as exc:
        status_code = (
            404 if exc.code == "agent_run_not_found" else 409
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    launched = _launch(user_id, replacement["id"], "restart")
    return api_success(
        {
            "run": launched,
            "replacesRunId": run_id,
        }
    )


@router.post("/api/agent/runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    snapshot = _snapshot_or_404(user_id, run_id)
    cancelling_snapshot = {**snapshot, "status": "cancelling"}
    requested = agent_run_coordinator.cancel(
        run_id,
        {
            "type": "cancel_requested",
            "status": "cancelling",
            "phase": "正在安全停止当前操作",
            "run": cancelling_snapshot,
        },
    )
    agent_tool_operations.cancel_for_run(user_id, run_id)
    if requested:
        snapshot = cancelling_snapshot
    else:
        snapshot = _snapshot_or_404(user_id, run_id)
        if snapshot["status"] not in {
            "completed",
            "failed",
            "cancelled",
        }:
            try:
                snapshot = agent_runs.transition_run(
                    user_id,
                    run_id,
                    "cancelled",
                )
            except AgentRunStoreError:
                snapshot = _snapshot_or_404(user_id, run_id)
    return api_success(
        {
            "cancelRequested": requested,
            "cancelState": snapshot["status"],
            "run": snapshot,
        }
    )
