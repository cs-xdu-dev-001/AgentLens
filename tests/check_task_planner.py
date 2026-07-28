from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.schemas import ChatRequest  # noqa: E402
from knowflow.services.agent_loop import (  # noqa: E402
    AgentRunner,
    ToolRegistry,
)
from knowflow.services.task_planner import (  # noqa: E402
    TaskPlan,
    parse_execution_mode,
    register_task_planner,
)


def expect_invalid(payload: dict) -> None:
    try:
        TaskPlan.model_validate(payload)
    except ValidationError:
        return
    raise AssertionError(f"plan unexpectedly accepted: {payload!r}")


class Gateway:
    def __init__(self):
        self.count = 0

    def complete(self, messages, config, **kwargs):
        self.count += 1
        if self.count == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "plan-call",
                        "type": "function",
                        "function": {
                            "name": "create_task_plan",
                            "arguments": json.dumps(
                                {
                                    "steps": [
                                        {
                                            "title": "搜索 Notion",
                                            "kind": "mcp",
                                            "tool_name": "notion-fetch",
                                        },
                                        {
                                            "title": "整理回答",
                                            "kind": "answer",
                                        },
                                    ]
                                },
                                ensure_ascii=False,
                            ),
                        },
                    }
                ],
            }
        return {"role": "assistant", "content": "计划已生成。"}


def main() -> None:
    plan = TaskPlan.model_validate(
        {
            "steps": [
                {"title": "  搜索   Notion  ", "kind": "mcp"},
                {"title": "整理结果", "kind": "answer"},
            ]
        }
    )
    assert [step.title for step in plan.steps] == [
        "搜索 Notion",
        "整理结果",
    ]
    expect_invalid({"steps": [{"title": "只有一步", "kind": "answer"}]})
    expect_invalid(
        {
            "steps": [
                {"title": str(index), "kind": "answer"}
                for index in range(9)
            ]
        }
    )
    expect_invalid(
        {
            "steps": [
                {"title": "a" * 81, "kind": "answer"},
                {"title": "结束", "kind": "answer"},
            ]
        }
    )
    expect_invalid(
        {
            "steps": [
                {"title": "执行", "kind": "shell"},
                {"title": "结束", "kind": "answer"},
            ]
        }
    )

    assert parse_execution_mode("/plan 整理资料") == (
        "plan_only",
        "整理资料",
    )
    assert parse_execution_mode("  /PLAN\n整理资料  ") == (
        "plan_only",
        "整理资料",
    )
    assert parse_execution_mode("你好") == ("auto", "你好")
    request = ChatRequest(question="/plan 整理资料")
    assert request.executionMode == "auto"

    captured: list[dict] = []
    registry = ToolRegistry()
    register_task_planner(registry, captured.append)
    callback_executions = []
    result = AgentRunner(gateway=Gateway()).run(
        messages=[{"role": "user", "content": "整理资料"}],
        config={},
        registry=registry,
        execution_callback=lambda execution, step_id: (
            callback_executions.append((execution, step_id))
        ),
    )
    assert result.answer == "计划已生成。"
    assert len(captured) == 1
    assert captured[0]["steps"][0]["title"] == "搜索 Notion"
    assert callback_executions[0][0].tool_name == "create_task_plan"
    assert "create_task_plan" not in registry.names()
    print("task planner protocol checks passed")


if __name__ == "__main__":
    main()
