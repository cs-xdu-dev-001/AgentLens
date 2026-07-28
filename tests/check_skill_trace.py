from __future__ import annotations

import json
import importlib
from pathlib import Path
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import AgentRunner, ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.skill_runtime import SkillActivationSession
from knowflow.schemas import ChatRequest


class Store:
    def __init__(self):
        self.available_calls = []

    def activation_candidates(self, user_id, available_tools):
        self.available_calls.append(set(available_tools))
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

    failure_registry = ToolRegistry()
    failure_registry.register(
        name="invalid_tool",
        description="invalid",
        input_schema={
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"type": "string"}},
        },
        handler=lambda args: {"ok": True},
    )
    failure_registry.register(
        name="denied_tool",
        description="denied",
        input_schema={"type": "object"},
        handler=lambda args: {"ok": True},
        read_only=False,
        risk="write",
    )

    def fail_after_activation(args):
        raise RuntimeError("expected")

    failure_registry.register(
        name="failing_tool",
        description="failing",
        input_schema={"type": "object"},
        handler=fail_after_activation,
    )
    failure_session = SkillActivationSession(
        store=Store(),
        user_id=1,
        available_tools=failure_registry.names(),
    )
    failure_session.register_activation_tool(failure_registry)

    class FailureGateway:
        def __init__(self):
            self.calls = 0

        def complete(
            self, messages, config, *, tools=None, tool_choice=None
        ):
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "activate-failures",
                            "function": {
                                "name": "activate_skill",
                                "arguments": '{"skill":"safe"}',
                            },
                        },
                        {
                            "id": "invalid",
                            "function": {
                                "name": "invalid_tool",
                                "arguments": "{}",
                            },
                        },
                        {
                            "id": "denied",
                            "function": {
                                "name": "denied_tool",
                                "arguments": "{}",
                            },
                        },
                        {
                            "id": "handler-failure",
                            "function": {
                                "name": "failing_tool",
                                "arguments": "{}",
                            },
                        },
                    ],
                }
            return {"content": "done"}

    class DenyGate:
        def __init__(self):
            self.parent_step_id = None

        def set_parent_step_id(self, parent_step_id):
            self.parent_step_id = parent_step_id

        def request(self, definition, arguments, call_id):
            return "deny"

    failure_result = AgentRunner(gateway=FailureGateway()).run(
        messages=[{"role": "user", "content": "failure snapshots"}],
        config={},
        registry=failure_registry,
        trace=AgentTraceRecorder(run_id="skill-failures"),
        parent_step_id="root",
        approval_gate=DenyGate(),
    )
    assert [item.status for item in failure_result.executions] == [
        "success",
        "failed",
        "failed",
        "failed",
    ]
    assert [
        item.error_code for item in failure_result.executions[1:]
    ] == [
        "invalid_arguments",
        "permission_denied",
        "tool_execution_failed",
    ]
    expected_snapshot = {
        "skillId": 1,
        "skillSlug": "safe",
        "skillVersion": "1.0.0",
        "skillContentHash": "b" * 64,
    }
    assert all(
        item.skill_snapshot == expected_snapshot
        for item in failure_result.executions
    )

    runtime = importlib.import_module("knowflow.runtime")
    extensions = importlib.import_module(
        "knowflow.routers.extensions"
    )
    integration_session = f"skill-snapshot-{uuid.uuid4().hex}"
    runtime.execute(
        """
        INSERT INTO chat_session(
            id, user_id, title, created_at, updated_at
        )
        VALUES (
            :id, 1, 'Skill snapshot check', :now, :now
        )
        """,
        {"id": integration_session, "now": runtime.now_str()},
    )

    class BatchGateway:
        def __init__(self):
            self.calls = 0

        def complete(
            self, messages, config, *, tools=None, tool_choice=None
        ):
            self.calls += 1
            if self.calls == 1:
                return {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "before",
                            "function": {
                                "name": "before_tool",
                                "arguments": "{}",
                            },
                        },
                        {
                            "id": "activate",
                            "function": {
                                "name": "activate_skill",
                                "arguments": '{"skill":"safe"}',
                            },
                        },
                        {
                            "id": "after",
                            "function": {
                                "name": "after_tool",
                                "arguments": "{}",
                            },
                        },
                        {
                            "id": "failed",
                            "function": {
                                "name": "failing_tool",
                                "arguments": "{}",
                            },
                        },
                    ],
                }
            return {"content": "snapshot answer"}

    class Pool:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    snapshot_store = Store()

    def integration_registry(*args, **kwargs):
        value = ToolRegistry()
        value.register(
            name="before_tool",
            description="before",
            input_schema={"type": "object"},
            handler=lambda args: {"stage": "before"},
        )
        value.register(
            name="after_tool",
            description="after",
            input_schema={"type": "object"},
            handler=lambda args: {"stage": "after"},
        )

        def fail(args):
            raise RuntimeError("expected tool failure")

        value.register(
            name="failing_tool",
            description="fail",
            input_schema={"type": "object"},
            handler=fail,
        )
        return value

    originals = {
        "ensure_session": extensions.ensure_session,
        "get_model_config": extensions.get_model_config,
        "build_tool_registry": extensions.build_tool_registry,
        "McpRunSessionPool": extensions.McpRunSessionPool,
        "skills": extensions.skills,
        "gateway": extensions.gateway,
    }
    extensions.ensure_session = lambda *args, **kwargs: integration_session
    extensions.get_model_config = lambda *args, **kwargs: {}
    extensions.build_tool_registry = integration_registry
    extensions.McpRunSessionPool = Pool
    extensions.skills = snapshot_store
    extensions.gateway = BatchGateway()
    try:
        integration_result = extensions.execute_agent_chat(
            ChatRequest(
                question="snapshot sequence",
                sessionId=integration_session,
                autoAgent=True,
                enableTools=False,
            ),
            1,
        )
    finally:
        for name, value in originals.items():
            setattr(extensions, name, value)

    snapshot_rows = runtime.fetch_all(
        """
        SELECT tool_name, skill_id, skill_slug, skill_version,
               skill_content_hash
        FROM agent_tool_call
        WHERE session_id=:session_id
        ORDER BY id
        """,
        {"session_id": integration_session},
    )
    assert [row["tool_name"] for row in snapshot_rows] == [
        "before_tool",
        "activate_skill",
        "after_tool",
        "failing_tool",
    ]
    assert snapshot_rows[0]["skill_id"] is None
    expected_columns = (1, "safe", "1.0.0", "b" * 64)
    assert [
        (
            row["skill_id"],
            row["skill_slug"],
            row["skill_version"],
            row["skill_content_hash"],
        )
        for row in snapshot_rows[1:]
    ] == [expected_columns] * 3
    assistant_row = runtime.fetch_one(
        """
        SELECT skill_id, skill_slug, skill_version, skill_content_hash
        FROM chat_message WHERE id=:message_id
        """,
        {"message_id": integration_result["messageId"]},
    )
    assert tuple(assistant_row.values()) == expected_columns
    assert snapshot_store.available_calls[-1] == {
        "before_tool",
        "after_tool",
        "failing_tool",
    }
    assert "notion" not in snapshot_store.available_calls[-1]
    public_integration = json.dumps(
        {
            "trace": integration_result["trace"],
            "toolCalls": integration_result["toolCalls"],
        },
        ensure_ascii=False,
    ).lower()
    for secret in (
        "private body",
        "c:\\private",
        "user@example.com",
        "skip approval",
    ):
        assert secret not in public_integration

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
    runtime.execute(
        "DELETE FROM agent_tool_call WHERE session_id=:session_id",
        {"session_id": integration_session},
    )
    runtime.execute(
        "DELETE FROM chat_message WHERE session_id=:session_id",
        {"session_id": integration_session},
    )
    runtime.execute(
        "DELETE FROM chat_session WHERE id=:session_id",
        {"session_id": integration_session},
    )
    print("Skill traces preserve the activation parent chain and redact instructions")


if __name__ == "__main__":
    main()
