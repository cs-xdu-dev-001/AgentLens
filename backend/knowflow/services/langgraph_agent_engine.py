from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .agent_loop import AgentRunResult, ToolRegistry


class LangGraphState(TypedDict):
    messages: list[dict[str, Any]]
    answer: str


@dataclass(frozen=True)
class LangGraphRunContext:
    gateway: Any
    config: dict[str, Any] | None
    trace: Any = None
    parent_step_id: str | None = None
    model_event_callback: Callable[[dict[str, Any]], None] | None = None


class LangGraphToolCallError(RuntimeError):
    code = "langgraph_tools_not_supported"

    def __init__(self):
        super().__init__(
            "LangGraph model-only mode does not support tool calls."
        )


class LangGraphAgentEngine:
    name = "langgraph"

    def __init__(self, *, gateway, max_tool_rounds: int = 3):
        self._gateway = gateway
        del max_tool_rounds
        builder = StateGraph(
            LangGraphState,
            context_schema=LangGraphRunContext,
        )
        builder.add_node("model", self._call_model)
        builder.add_edge(START, "model")
        builder.add_edge("model", END)
        self._graph = builder.compile()

    @staticmethod
    def _call_model(
        state: LangGraphState,
        runtime: Runtime[LangGraphRunContext],
    ) -> dict[str, str]:
        context = runtime.context
        config = context.config or {}
        trace = context.trace
        model_step = (
            trace.start_step(
                kind="model",
                name="model_completion",
                title="Model is analyzing",
                parent_id=context.parent_step_id,
                input_summary={
                    "messageCount": len(state["messages"]),
                    "toolCount": 0,
                },
                details={
                    "modelName": str(config.get("model_name") or ""),
                    "apiMode": str(
                        config.get("api_mode") or "chat_completions"
                    ),
                    "engineName": "langgraph",
                },
            )
            if trace
            else None
        )
        completion_options: dict[str, Any] = {
            "tools": None,
            "tool_choice": None,
        }
        if context.model_event_callback is not None:
            completion_options["event_callback"] = (
                context.model_event_callback
            )
        try:
            message = context.gateway.complete(
                state["messages"],
                context.config,
                **completion_options,
            )
        except Exception:
            if trace and model_step:
                trace.finish_step(
                    model_step,
                    status="failed",
                    title="Model request failed",
                    error_code="model_request_failed",
                )
            raise

        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            if trace and model_step:
                trace.finish_step(
                    model_step,
                    status="failed",
                    title="Model requested an unavailable tool",
                    output_summary={"toolCallCount": len(tool_calls)},
                    error_code="langgraph_tools_not_supported",
                )
            raise LangGraphToolCallError()

        answer = str(message.get("content") or "").strip()
        if not answer:
            if trace and model_step:
                trace.finish_step(
                    model_step,
                    status="failed",
                    title="Model response was invalid",
                    error_code="invalid_model_response",
                )
            raise ValueError("Model returned no text response.")

        if trace and model_step:
            trace.finish_step(
                model_step,
                status="success",
                title="Model generated an answer",
                output_summary={"toolCallCount": 0},
            )
        return {"answer": answer}

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
        execution_callback=None,
        model_event_callback=None,
    ) -> AgentRunResult:
        output = self._graph.invoke(
            {
                "messages": [dict(message) for message in messages],
                "answer": "",
            },
            context=LangGraphRunContext(
                gateway=self._gateway,
                config=config,
                trace=trace,
                parent_step_id=parent_step_id,
                model_event_callback=model_event_callback,
            ),
        )
        return AgentRunResult(
            answer=str(output["answer"]),
            executions=[],
            trace=trace.snapshot() if trace else [],
        )
