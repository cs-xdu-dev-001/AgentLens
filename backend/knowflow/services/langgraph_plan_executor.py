from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime


@dataclass(frozen=True)
class PlanStepOutcome:
    answer: str
    public_result: str = ""
    pause_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class PlanExecutionResult:
    answer: str
    completed_context: list[str]
    executed_step_ids: list[str]
    pause_payload: dict[str, Any] | None = None

    @property
    def paused(self) -> bool:
        return self.pause_payload is not None


class PlanExecutionState(TypedDict):
    steps: list[dict[str, Any]]
    step_index: int
    current_step: dict[str, Any] | None
    current_step_resumes: bool
    resume_step_id: str | None
    completed_context: list[str]
    executed_step_ids: list[str]
    answer: str
    pause_payload: dict[str, Any] | None


@dataclass(frozen=True)
class PlanExecutionContext:
    execute_step: Callable[
        [dict[str, Any], bool, list[str]],
        PlanStepOutcome,
    ]


class LangGraphPlanExecutor:
    """Run durable public-plan steps with LangGraph control flow.

    The database remains the source of truth. This graph only selects the
    next executable step and controls the loop around the nested Agent graph.
    """

    def __init__(self) -> None:
        builder = StateGraph(
            PlanExecutionState,
            context_schema=PlanExecutionContext,
        )
        builder.add_node("select_step", self._select_step)
        builder.add_node("execute_step", self._execute_step)
        builder.add_edge(START, "select_step")
        builder.add_conditional_edges(
            "select_step",
            self._route_after_selection,
            {"execute": "execute_step", "end": END},
        )
        builder.add_conditional_edges(
            "execute_step",
            self._route_after_execution,
            {"continue": "select_step", "end": END},
        )
        self._graph = builder.compile()

    @staticmethod
    def _select_step(state: PlanExecutionState) -> dict[str, Any]:
        steps = state.get("steps") or []
        completed = list(state.get("completed_context") or [])
        index = int(state.get("step_index") or 0)
        resume_step_id = state.get("resume_step_id")
        while index < len(steps):
            step = dict(steps[index])
            index += 1
            status = str(step.get("status") or "")
            if status == "completed":
                if step.get("outputSummary"):
                    completed.append(str(step["outputSummary"]))
                continue
            resumes = bool(
                status == "waiting_approval"
                and resume_step_id
                and str(step.get("id") or "") == resume_step_id
            )
            if status not in {"pending", "failed"} and not resumes:
                continue
            return {
                "step_index": index,
                "current_step": step,
                "current_step_resumes": resumes,
                "completed_context": completed,
            }
        return {
            "step_index": index,
            "current_step": None,
            "current_step_resumes": False,
            "completed_context": completed,
        }

    @staticmethod
    def _route_after_selection(state: PlanExecutionState) -> str:
        return "execute" if state.get("current_step") else "end"

    @staticmethod
    def _execute_step(
        state: PlanExecutionState,
        runtime: Runtime[PlanExecutionContext],
    ) -> dict[str, Any]:
        step = state.get("current_step")
        if not isinstance(step, dict):
            raise ValueError("LangGraph plan step is unavailable.")
        outcome = runtime.context.execute_step(
            dict(step),
            bool(state.get("current_step_resumes")),
            list(state.get("completed_context") or []),
        )
        if outcome.pause_payload is not None:
            return {
                "answer": outcome.answer,
                "pause_payload": dict(outcome.pause_payload),
            }
        completed = list(state.get("completed_context") or [])
        if outcome.public_result:
            completed.append(outcome.public_result)
        executed = list(state.get("executed_step_ids") or [])
        step_id = str(step.get("id") or "")
        if step_id:
            executed.append(step_id)
        return {
            "answer": outcome.answer,
            "completed_context": completed,
            "executed_step_ids": executed,
            "current_step": None,
            "current_step_resumes": False,
        }

    @staticmethod
    def _route_after_execution(state: PlanExecutionState) -> str:
        return "end" if state.get("pause_payload") else "continue"

    def run(
        self,
        *,
        steps: list[dict[str, Any]],
        execute_step: Callable[
            [dict[str, Any], bool, list[str]],
            PlanStepOutcome,
        ],
        resume_step_id: str | None = None,
        initial_answer: str = "",
    ) -> PlanExecutionResult:
        output = self._graph.invoke(
            {
                "steps": [dict(step) for step in steps],
                "step_index": 0,
                "current_step": None,
                "current_step_resumes": False,
                "resume_step_id": resume_step_id,
                "completed_context": [],
                "executed_step_ids": [],
                "answer": initial_answer,
                "pause_payload": None,
            },
            {"recursion_limit": max(6, len(steps) * 3 + 4)},
            context=PlanExecutionContext(execute_step=execute_step),
        )
        pause_payload = output.get("pause_payload")
        return PlanExecutionResult(
            answer=str(output.get("answer") or ""),
            completed_context=[
                str(item)
                for item in (output.get("completed_context") or [])
            ],
            executed_step_ids=[
                str(item)
                for item in (output.get("executed_step_ids") or [])
            ],
            pause_payload=(
                dict(pause_payload)
                if isinstance(pause_payload, dict)
                else None
            ),
        )
