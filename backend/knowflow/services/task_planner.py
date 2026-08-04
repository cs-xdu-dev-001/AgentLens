from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agent_loop import ToolHandlerResult, ToolRegistry


class TaskPlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1, max_length=80)
    kind: Literal["reasoning", "tool", "mcp", "skill", "answer"]
    tool_name: str | None = Field(default=None, max_length=160)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Plan step title is required.")
        return normalized


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    steps: list[TaskPlanStep] = Field(min_length=2, max_length=8)


def parse_execution_mode(question: str) -> tuple[str, str]:
    normalized = str(question or "").strip()
    head, separator, tail = normalized.partition(" ")
    if head.lower() == "/plan":
        return "plan_only", tail.strip() if separator else ""
    if normalized[:5].lower() == "/plan" and len(normalized) > 5:
        next_character = normalized[5]
        if next_character.isspace():
            return "plan_only", normalized[6:].strip()
    return "auto", normalized


def register_task_planner(
    registry: ToolRegistry,
    callback: Callable[[dict], None],
) -> None:
    def create_plan(plan: TaskPlan) -> ToolHandlerResult:
        snapshot = plan.model_dump()
        callback(snapshot)
        return ToolHandlerResult(
            output={"created": True, "plan": snapshot},
            audit_output={
                "created": True,
                "stepCount": len(plan.steps),
            },
        )

    registry.register(
        name="create_task_plan",
        description=(
            "Create a concise public plan only when the user's task "
            "requires multiple distinct actions. Do not expose private "
            "reasoning. Simple questions should be answered directly."
        ),
        arguments_model=TaskPlan,
        handler=create_plan,
        read_only=True,
        engine_names={"langgraph"},
        trace_kind="system",
        internal=True,
        remove_after_success=True,
        ends_run_on_success=True,
    )
