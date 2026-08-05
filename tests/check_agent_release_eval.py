from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.langgraph_agent_engine import LangGraphAgentEngine


def call(name: str, arguments: dict, call_id: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


class Gateway:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)

    def complete(self, _messages, _config, **_options):
        return self.responses.pop(0)


def scenario(case_id: str) -> tuple[Gateway, ToolRegistry]:
    registry = ToolRegistry()
    registry.register(
        name="inspect_workspace",
        description="Inspect the isolated workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=lambda arguments: {"path": arguments["path"], "files": 1},
        read_only=True,
        engine_names={"langgraph"},
    )
    registry.register(
        name="write_workspace",
        description="Write to the isolated workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        handler=lambda arguments: {"path": arguments["path"]},
        read_only=False,
        destructive=True,
        engine_names={"langgraph"},
    )
    if case_id == "direct_answer":
        return Gateway([{"role": "assistant", "content": "直接回答"}]), registry
    if case_id == "read_tool":
        return Gateway([
            {"role": "assistant", "content": "", "tool_calls": [call("inspect_workspace", {"path": "src"}, "call_read")]},
            {"role": "assistant", "content": "读取完成"},
        ]), registry
    if case_id == "write_requires_approval":
        return Gateway([
            {"role": "assistant", "content": "", "tool_calls": [call("write_workspace", {"path": "result.txt"}, "call_write")]},
        ]), registry
    raise AssertionError(f"Unknown Agent eval case: {case_id}")


def main() -> None:
    cases = json.loads(
        (ROOT / "evals" / "agent_release_cases.json").read_text(
            encoding="utf-8"
        )
    )
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint = Path(temporary) / "checkpoints.sqlite3"
        for case in cases:
            started = time.perf_counter()
            gateway, registry = scenario(case["id"])
            result = LangGraphAgentEngine(
                gateway=gateway,
                checkpoint_db_path=checkpoint,
            ).run(
                user_id=91,
                run_id=f"eval_{case['id']}",
                messages=[{"role": "user", "content": case["id"]}],
                config={"model_name": "deterministic-eval"},
                registry=registry,
            )
            tools = [item.tool_name for item in result.executions]
            assert result.answer == case["expectedAnswer"], case["id"]
            assert tools == case["expectedTools"], case["id"]
            assert result.paused is case["expectedPaused"], case["id"]
            results.append(
                {
                    "id": case["id"],
                    "passed": True,
                    "latencyMs": round((time.perf_counter() - started) * 1000),
                }
            )
    assert len(results) == len(cases) >= 3
    print(json.dumps({"passed": len(results), "cases": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
