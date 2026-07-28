from __future__ import annotations

from collections.abc import Callable, Iterable
from queue import Empty
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..runtime import (
    agent_run_coordinator,
    agent_runs,
    api_success,
    current_user_id,
    sse_event,
)


router = APIRouter()
_run_executor: Callable[..., None] | None = None


def configure_agent_run_executor(executor: Callable[..., None]) -> None:
    global _run_executor
    _run_executor = executor


def _snapshot_or_404(user_id: int, run_id: str) -> dict[str, Any]:
    snapshot = agent_runs.get_snapshot(user_id, run_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent run not found.")
    return snapshot


def _launch(user_id: int, run_id: str, action: str) -> dict[str, Any]:
    snapshot = _snapshot_or_404(user_id, run_id)
    allowed = {
        "start": {"waiting_start"},
        "replan": {"waiting_start"},
        "resume": {"interrupted", "failed"},
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
    return api_success(
        _snapshot_or_404(current_user_id(request), run_id)
    )


@router.get("/api/agent/runs/{run_id}/events")
def stream_agent_run_events(
    run_id: str,
    request: Request,
) -> StreamingResponse:
    user_id = current_user_id(request)
    snapshot = _snapshot_or_404(user_id, run_id)

    def generate() -> Iterable[str]:
        yield sse_event(
            "run_snapshot",
            {"type": "run_snapshot", "run": snapshot},
        )
        subscriber = agent_run_coordinator.subscribe(run_id)
        if subscriber is None:
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
                    break
                yield sse_event(event_type, event)
                if event_type in {"done", "error", "cancelled"}:
                    break
        finally:
            agent_run_coordinator.unsubscribe(run_id, subscriber)

    return StreamingResponse(generate(), media_type="text/event-stream")


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


@router.post("/api/agent/runs/{run_id}/cancel")
def cancel_agent_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    snapshot = _snapshot_or_404(user_id, run_id)
    requested = agent_run_coordinator.cancel(run_id)
    if not requested and snapshot["status"] not in {
        "completed",
        "failed",
        "cancelled",
    }:
        snapshot = agent_runs.transition_run(
            user_id,
            run_id,
            "cancelled",
        )
    return api_success(
        {
            "cancelRequested": requested,
            "run": snapshot,
        }
    )
