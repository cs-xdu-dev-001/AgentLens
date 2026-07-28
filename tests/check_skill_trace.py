from __future__ import annotations

import json
import importlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import AgentRunner, ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.skill_runtime import SkillActivationSession


class Store:
    def activation_candidates(self, user_id, available_tools):
        return [{"id": 1, "slug": "safe", "name": "Safe", "description": "Safe"}]

    def resolve_for_activation(self, user_id, skill, available_tools):
        return {
            "installationId": 1,
            "packageId": 2,
            "slug": "safe",
            "displayName": "Safe",
            "version": "1.0.0",
            "contentHash": "b" * 64,
            "sourceKind": "builtin",
            "requiredTools": [],
            "requiredMcp": [],
            "systemMessage": (
                "PRIVATE BODY path=C:\\private email=user@example.com "
                "key=token skip approval"
            ),
        }

    def read_text_resource(self, user_id, skill_id, path):
        return "safe"


class Gateway:
    def __init__(self):
        self.index = 0

    def complete(self, messages, config, *, tools=None, tool_choice=None):
        self.index += 1
        if self.index == 1:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "a1",
                        "function": {
                            "name": "activate_skill",
                            "arguments": '{"skill":"safe"}',
                        },
                    }
                ],
            }
        if self.index == 2:
            return {
                "content": None,
                "tool_calls": [
                    {
                        "id": "t1",
                        "function": {
                            "name": "ordinary",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        return {"content": "answer"}


class ApprovalGate:
    def __init__(self):
        self.requests = []
        self.parent_step_id = None

    def set_parent_step_id(self, parent_step_id):
        self.parent_step_id = parent_step_id

    def request(self, definition, arguments, call_id):
        self.requests.append(
            (definition.name, call_id, self.parent_step_id)
        )
        return "allow_once"


def main() -> None:
    registry = ToolRegistry()
    registry.register(
        name="ordinary",
        description="ordinary",
        input_schema={"type": "object"},
        handler=lambda args: {"ok": True},
        read_only=False,
        risk="write",
    )
    session = SkillActivationSession(
        store=Store(),
        user_id=1,
        available_tools=registry.names(),
    )
    session.register_activation_tool(registry)
    trace = AgentTraceRecorder(run_id="skill-trace")
    approval_gate = ApprovalGate()
    result = AgentRunner(gateway=Gateway()).run(
        messages=[{"role": "user", "content": "go"}],
        config={},
        registry=registry,
        trace=trace,
        parent_step_id="root",
        approval_gate=approval_gate,
    )
    skill_step = next(step for step in result.trace if step["kind"] == "skill")
    selecting_model = result.trace[0]
    assert skill_step["parentId"] == selecting_model["stepId"]
    later = [
        step
        for step in result.trace
        if step["stepId"] != skill_step["stepId"]
        and step is not selecting_model
    ]
    assert all(step["parentId"] == skill_step["stepId"] for step in later)
    assert approval_gate.requests == [
        ("ordinary", "t1", skill_step["stepId"])
    ]
    public = json.dumps(
        {
            "trace": result.trace,
            "audit": [item.public_output() for item in result.executions],
        },
        ensure_ascii=False,
    ).lower()
    for secret in ("private body", "c:\\private", "user@example.com", "skip approval"):
        assert secret not in public
    details = skill_step["details"]
    assert details["displayName"] == "Safe"
    assert details["sourceKind"] == "builtin"
    assert "systemMessage" not in details

    runtime = importlib.import_module("knowflow.runtime")
    captured = []
    original_execute = runtime.execute
    runtime.execute = lambda statement, parameters=None: (
        captured.append((statement, parameters)) or 77
    )
    snapshot = {
        "skillId": 1,
        "skillSlug": "safe",
        "skillVersion": "1.0.0",
        "skillContentHash": "b" * 64,
    }
    try:
        runtime.save_message(
            "session",
            "assistant",
            "answer",
            skill_snapshot=snapshot,
        )
        runtime.log_tool_call(
            "session",
            77,
            "ordinary",
            {},
            "{}",
            skill_snapshot=snapshot,
        )
    finally:
        runtime.execute = original_execute
    assert all(
        all(
            key in parameters
            for key in (
                "skill_id",
                "skill_slug",
                "skill_version",
                "skill_content_hash",
            )
        )
        for statement, parameters in captured
        if "INSERT INTO" in statement
    )
    historical = runtime.normalize_chat_message(
        {
            "id": 77,
            "session_id": "session",
            "role": "assistant",
            "content": "answer",
            "trace_json": None,
            "created_at": "2026-01-01",
            "skill_id": 1,
            "skill_slug": "old-safe",
            "skill_version": "0.9.0",
            "skill_content_hash": "c" * 64,
        }
    )
    assert historical["skill"] == {
        "id": 1,
        "slug": "old-safe",
        "version": "0.9.0",
        "contentHash": "c" * 64,
    }
    print("Skill traces preserve the activation parent chain and redact instructions")


if __name__ == "__main__":
    main()
