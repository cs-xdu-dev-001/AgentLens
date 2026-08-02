from __future__ import annotations

import importlib
from typing import Any, Callable, Protocol

from .agent_loop import (
    AgentRunResult,
    AgentRunner,
    ToolExecution,
    ToolRegistry,
)


ExecutionCallback = Callable[[ToolExecution, str | None], None]
ModelEventCallback = Callable[[dict[str, Any]], None]


class AgentEngine(Protocol):
    name: str

    def run(
        self,
        *,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        approval_gate=None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback: ExecutionCallback | None = None,
        model_event_callback: ModelEventCallback | None = None,
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


class CurrentAgentEngine:
    name = "current"

    def __init__(self, *, gateway, max_tool_rounds: int = 3):
        self._runner = AgentRunner(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
        )

    def run(
        self,
        *,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        approval_gate=None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback: ExecutionCallback | None = None,
        model_event_callback: ModelEventCallback | None = None,
    ) -> AgentRunResult:
        return self._runner.run(
            messages=messages,
            config=config,
            registry=registry,
            trace=trace,
            parent_step_id=parent_step_id,
            approval_gate=approval_gate,
            skill_snapshot=skill_snapshot,
            execution_callback=execution_callback,
            model_event_callback=model_event_callback,
        )


def build_agent_engine(
    engine_name: str,
    *,
    gateway,
    max_tool_rounds: int = 3,
) -> AgentEngine:
    normalized = str(engine_name or "").strip().lower()
    if normalized == "current":
        return CurrentAgentEngine(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
        )
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
        )
    raise AgentEngineSelectionError(normalized or "unknown")
