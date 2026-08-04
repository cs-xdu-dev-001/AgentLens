from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Protocol

from .agent_loop import (
    AgentRunResult,
    ToolExecution,
    ToolRegistry,
)


ExecutionCallback = Callable[[ToolExecution, str | None], None]
ModelEventCallback = Callable[[dict[str, Any]], None]
SkillRestoreCallback = Callable[[dict[str, Any]], None]
MemoryRecallCallback = Callable[[], list[dict[str, Any]]]
RetrievalContextCallback = Callable[[], dict[str, Any]]


class AgentEngine(Protocol):
    name: str

    def run(
        self,
        *,
        user_id: int,
        run_id: str,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback: ExecutionCallback | None = None,
        model_event_callback: ModelEventCallback | None = None,
        resume_from_checkpoint: bool = False,
        tool_operation_store=None,
        approval_decision: str | None = None,
        skill_restore: SkillRestoreCallback | None = None,
        memory_recall: MemoryRecallCallback | None = None,
        memory_enabled: bool = False,
        retrieval_context: RetrievalContextCallback | None = None,
    ) -> AgentRunResult:
        ...


class AgentEngineSelectionError(ValueError):
    def __init__(self, engine_name: str):
        self.engine_name = engine_name
        super().__init__(f"Unsupported Agent engine: {engine_name}")


class AgentEngineUnavailableError(RuntimeError):
    def __init__(self, engine_name: str):
        self.engine_name = engine_name
        super().__init__(f"Agent engine is unavailable: {engine_name}")


def build_agent_engine(
    engine_name: str,
    *,
    gateway,
    max_tool_rounds: int = 3,
    checkpoint_db_path: Path | None = None,
) -> AgentEngine:
    normalized = str(engine_name or "").strip().lower()
    if normalized == "langgraph":
        try:
            module = importlib.import_module(
                ".langgraph_agent_engine",
                __package__,
            )
        except ModuleNotFoundError as exc:
            if str(exc.name or "").startswith("langgraph"):
                raise AgentEngineUnavailableError("langgraph") from exc
            raise
        return module.LangGraphAgentEngine(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
            checkpoint_db_path=checkpoint_db_path,
        )
    raise AgentEngineSelectionError(normalized or "unknown")
