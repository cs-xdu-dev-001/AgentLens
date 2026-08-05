from collections.abc import Callable
import logging
import time

from fastapi import APIRouter, HTTPException, Request

from ..runtime import (
    agent_run_coordinator,
    agent_runs,
    agent_tool_operations,
    api_success,
    current_user_id,
)
from ..schemas import AgentApprovalDecision
from ..services.agent_tool_operations import AgentApprovalRunner


router = APIRouter()
_run_executor: Callable[..., None] | None = None
logger = logging.getLogger(__name__)


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
        try:
            _run_executor(
                user_id,
                run_id,
                f"approval:{approval_id}",
                cancel_event,
                publish,
            )
        except Exception as exc:
            logger.warning(
                "Agent approval resume failed for %s: %s",
                approval_id,
                type(exc).__name__,
            )
            run = agent_runs.get_snapshot(user_id, run_id)
            if run and run["status"] == "waiting_approval":
                try:
                    agent_runs.transition_run(user_id, run_id, "failed")
                except Exception as transition_exc:
                    logger.warning(
                        "Agent approval failure did not converge for %s: %s",
                        approval_id,
                        type(transition_exc).__name__,
                    )

    for _ in range(21):
        run = agent_runs.get_snapshot(user_id, run_id)
        if not run or run["status"] != "waiting_approval":
            return False
        if agent_run_coordinator.start(run_id, target):
            return True
        time.sleep(0.05)
    return False


def _resume_resolved_approval(operation: dict) -> bool:
    user_id = int(operation["userId"])
    run_id = str(operation["runId"])
    run = agent_runs.get_snapshot(user_id, run_id)
    if not run or run["status"] != "waiting_approval":
        return False
    return _launch_resume(
        user_id,
        run_id,
        str(operation["approvalId"]),
    )


approval_runner = AgentApprovalRunner(
    store=agent_tool_operations,
    resume=_resume_resolved_approval,
)


@router.post("/api/agent/approvals/{approval_id}")
def resolve_agent_approval(
    approval_id: str,
    payload: AgentApprovalDecision,
    request: Request,
):
    user_id = current_user_id(request)
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
    approval_runner.wake()
    run = agent_runs.get_snapshot(user_id, operation["runId"])
    resume_allowed = bool(
        run and run["status"] == "waiting_approval"
    )
    resume_started = (
        _launch_resume(user_id, operation["runId"], approval_id)
        if resume_allowed
        else False
    )
    return api_success(
        {
            "resolved": True,
            "runId": operation["runId"],
            "resumeStarted": resume_started,
            "resumeRequired": resume_allowed and not resume_started,
        }
    )
