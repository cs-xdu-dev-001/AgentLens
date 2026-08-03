from collections.abc import Callable
import time

from fastapi import APIRouter, HTTPException, Request

from ..runtime import (
    agent_run_coordinator,
    agent_tool_operations,
    api_success,
    approval_broker,
    current_user_id,
)
from ..schemas import AgentApprovalDecision


router = APIRouter()
_run_executor: Callable[..., None] | None = None


def configure_approval_run_executor(executor: Callable[..., None]) -> None:
    global _run_executor
    _run_executor = executor


def _launch_resume(
    user_id: int,
    run_id: str,
    approval_id: str,
) -> bool:
    if _run_executor is None:
        return False

    def target(cancel_event, publish) -> None:
        _run_executor(
            user_id,
            run_id,
            f"approval:{approval_id}",
            cancel_event,
            publish,
        )

    for _ in range(21):
        if agent_run_coordinator.start(run_id, target):
            return True
        time.sleep(0.05)
    return False


@router.post("/api/agent/approvals/{approval_id}")
def resolve_agent_approval(
    approval_id: str,
    payload: AgentApprovalDecision,
    request: Request,
):
    user_id = current_user_id(request)
    if approval_broker.resolve(
        user_id,
        approval_id,
        payload.decision,
    ):
        return api_success({"resolved": True})
    operation = agent_tool_operations.resolve(
        user_id,
        approval_id,
        payload.decision,
    )
    if operation is None:
        raise HTTPException(
            status_code=404,
            detail="Approval not found.",
        )
    resume_started = _launch_resume(
        user_id,
        operation["runId"],
        approval_id,
    )
    return api_success(
        {
            "resolved": True,
            "runId": operation["runId"],
            "resumeStarted": resume_started,
            "resumeRequired": not resume_started,
        }
    )
