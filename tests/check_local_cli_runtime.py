from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.local_cli_runtime import (  # noqa: E402
    gateway_config,
    LocalAgentRuntime,
    LocalCliConfigError,
    LocalCliConfigStore,
    local_cli_max_tool_rounds,
    validate_local_config,
)
from knowflow.services.agent_trace import sanitize_trace_value  # noqa: E402
from knowflow.services.agent_loop import ToolRegistry  # noqa: E402
from knowflow.services.langgraph_agent_engine import (  # noqa: E402
    AgentRunCancelledError,
    LangGraphAgentEngine,
)
from knowflow.services.workspace_runtime import (  # noqa: E402
    SandboxCommandResult,
    WorkspaceRuntime,
    register_workspace_tools,
)
from knowflow.tui.state import PromptHistoryStore, TuiSessionState  # noqa: E402


def main() -> None:
    sanitized = sanitize_trace_value(
        {
            "command": "curl --token cli-secret https://example.test",
            "authorization": "Bearer header-secret",
            "jwt": "eyJheader.payload.signature",
        }
    )
    assert sanitized is not None
    for secret in (
        "cli-secret",
        "header-secret",
        "eyJheader.payload.signature",
    ):
        assert secret not in sanitized

    with TemporaryDirectory() as folder:
        history = PromptHistoryStore(Path(folder) / "state" / "history.jsonl")
        assert history.append("first prompt")
        assert history.append("second prompt")
        assert history.load() == ["first prompt", "second prompt"]
        if os.name != "nt":
            assert history.path.parent.stat().st_mode & 0o777 == 0o700
            assert history.path.stat().st_mode & 0o777 == 0o600
        assert history.clear()
        assert history.load() == []

    session = TuiSessionState()
    session.enqueue("later", priority="later")
    session.enqueue("next", priority="next")
    session.enqueue("now", priority="now")
    assert [session.dequeue().text for _ in range(3)] == [
        "now",
        "next",
        "later",
    ]

    with TemporaryDirectory() as folder:
        store = LocalCliConfigStore(Path(folder) / "config")
        store.save(
            provider="custom",
            base_url="https://gateway.example/v1/",
            model_name="agent-model",
            api_mode="responses",
            api_key="secret-value",
        )
        public = json.loads(store.config_path.read_text(encoding="utf-8"))
        private = json.loads(
            store.credentials_path.read_text(encoding="utf-8")
        )
        assert "api_key" not in public
        assert "secret-value" not in store.config_path.read_text(
            encoding="utf-8"
        )
        assert private["api_key"] == "secret-value"
        assert store.load()["base_url"] == "https://gateway.example/v1"
        if os.name != "nt":
            assert store.root.stat().st_mode & 0o777 == 0o700
            assert store.credentials_path.stat().st_mode & 0o777 == 0o600

        with patch.dict(
            os.environ,
            {
                "KNOWFLOW_MODEL": "environment-model",
                "KNOWFLOW_API_KEY": "environment-secret",
            },
        ):
            loaded = store.load()
        assert loaded["model_name"] == "environment-model"
        assert loaded["api_key"] == "environment-secret"

    try:
        validate_local_config(
            {
                "base_url": "http://remote.example/v1",
                "model_name": "model",
                "api_mode": "responses",
                "api_key": "secret",
            }
        )
    except LocalCliConfigError:
        pass
    else:
        raise AssertionError("insecure remote API URL accepted")

    loopback = validate_local_config(
        {
            "base_url": "http://127.0.0.1:11434/v1",
            "model_name": "local-model",
            "api_mode": "chat_completions",
            "api_key": "local",
        }
    )
    assert loopback["api_mode"] == "chat_completions"

    gateway = gateway_config(
        {
            **loopback,
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": 4096,
        }
    )
    assert set(gateway) == {
        "provider",
        "base_url",
        "model_name",
        "api_mode",
        "api_key_cipher",
        "model_type",
    }
    assert "temperature" not in gateway
    assert "top_p" not in gateway
    assert "max_tokens" not in gateway

    class FourRoundGateway:
        def __init__(self):
            self.calls = 0

        def complete(self, _messages, _config, **_kwargs):
            self.calls += 1
            if self.calls <= 4:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call_list_{self.calls}",
                            "type": "function",
                            "function": {
                                "name": "list_workspace",
                                "arguments": json.dumps({"path": "."}),
                            },
                        }
                    ],
                }
            return {"role": "assistant", "content": "四轮检查完成。"}

    with TemporaryDirectory() as folder, patch.dict(
        os.environ,
        {"KNOWFLOW_CLI_MAX_TOOL_ROUNDS": "4"},
    ):
        root = Path(folder)
        store = LocalCliConfigStore(root / "config")
        store.save(
            provider="custom",
            base_url="https://gateway.example/v1",
            model_name="agent-model",
            api_mode="responses",
            api_key="secret-value",
        )
        runtime = LocalAgentRuntime(
            config_store=store,
            workspace_root=root / "workspace",
            data_root=root / "data",
        )
        gateway = FourRoundGateway()
        runtime.engine._gateway = gateway
        execution = runtime.run("连续检查四次")
        assert local_cli_max_tool_rounds() == 4
        assert runtime.engine._max_tool_rounds == 4
        assert execution.result["answer"] == "四轮检查完成。"
        assert gateway.calls == 5
        assert len(
            [
                event
                for event in execution.events
                if event.get("type") == "tool_result"
            ]
        ) == 4
        trace_events = [
            event
            for event in execution.events
            if event.get("type") == "agent_step"
        ]
        assert trace_events
        assert any(event.get("kind") == "model" for event in trace_events)
        assert any(
            event.get("kind") in {"tool", "workspace", "sandbox"}
            for event in trace_events
        )
        stored = runtime.list_sessions()
        assert stored and stored[0]["status"] == "completed"
        loaded = runtime.load_session(stored[0]["runId"])
        assert loaded["answer"] == "四轮检查完成。"
        assert loaded["projectRoot"] == str((root / "workspace").resolve())
        renamed = runtime.rename_session(stored[0]["runId"], "  发布 复盘  ")
        assert renamed["title"] == "发布 复盘"
        assert runtime.load_session(stored[0]["runId"])["title"] == "发布 复盘"
        runtime.sessions.save(
            "run_rewindsource",
            title="回退来源",
            status="completed",
            messages=[
                {"role": "user", "content": "第一个问题"},
                {"role": "assistant", "content": "第一个回答"},
                {"role": "user", "content": "需要重新处理的问题"},
                {"role": "assistant", "content": "应被丢弃的回答"},
            ],
            contextMessages=[
                {"role": "user", "content": "第一个问题"},
                {"role": "assistant", "content": "第一个回答"},
                {"role": "user", "content": "需要重新处理的问题"},
                {"role": "assistant", "content": "应被丢弃的回答"},
            ],
            compaction={"summary": "不应带入新分支"},
            answer="应被丢弃的回答",
            **runtime._session_workspace_fields(),
        )
        rewound = runtime.branch_session(
            "run_rewindsource",
            before_message_index=2,
        )
        assert rewound["restoredQuestion"] == "需要重新处理的问题"
        assert rewound["messages"] == [
            {"role": "user", "content": "第一个问题"},
            {"role": "assistant", "content": "第一个回答"},
        ]
        assert rewound["contextMessages"] == rewound["messages"]
        assert rewound["compaction"] == {}
        assert rewound["answer"] == "第一个回答"
        assert runtime.workspace_status()["cwd"] == str((root / "workspace").resolve())
        extra = root / "extra-workspace"
        extra.mkdir()
        runtime.workspace_add_directory(str(extra))
        runtime.workspace_change_directory(str(extra))
        runtime.sessions.save(
            "run_workspacerestore",
            title="恢复额外工作目录",
            status="completed",
            messages=[],
            **runtime._session_workspace_fields(),
        )
        restored_runtime = LocalAgentRuntime(
            config_store=store,
            workspace_root=root / "workspace",
            data_root=root / "data",
        )
        restored_runtime.load_session("run_workspacerestore")
        restored_status = restored_runtime.workspace_status()
        assert restored_status["cwd"] == str(extra.resolve())
        assert str(extra.resolve()) in restored_status["allowedDirectories"]
        assert "edit_workspace_file" in {
            item["function"]["name"] for item in runtime.tool_schemas()
        }
        shell_events = []
        with patch(
            "knowflow.services.local_cli_runtime.SrtSandboxRunner"
        ) as sandbox_runner:
            sandbox_runner.return_value.run.return_value = SandboxCommandResult(
                exit_code=0,
                stdout="sandbox-ok\n",
                stderr="",
                timed_out=False,
                elapsed_seconds=0.1,
                total_lines=1,
                total_bytes=11,
            )
            shell_execution = runtime.run_shell_command(
                "echo sandbox-ok",
                event_sink=shell_events.append,
            )
        assert shell_execution.result["answer"] == "sandbox-ok\n"
        assert shell_execution.result["runId"].startswith("shell_")
        assert [event["type"] for event in shell_events] == [
            "run_started",
            "tool_started",
            "tool_result",
            "done",
        ]
        sandbox_runner.return_value.run.assert_called_once()

    class PlanGateway:
        def __init__(self):
            self.tool_names: set[str] = set()

        def complete(self, _messages, _config, **kwargs):
            self.tool_names = {
                str(item.get("function", {}).get("name") or "")
                for item in (kwargs.get("tools") or [])
            }
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_plan",
                        "type": "function",
                        "function": {
                            "name": "create_task_plan",
                            "arguments": json.dumps(
                                {
                                    "steps": [
                                        {
                                            "title": "检查现有实现",
                                            "kind": "tool",
                                            "tool_name": "read_workspace_file",
                                        },
                                        {
                                            "title": "整理最小改造方案",
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

    with TemporaryDirectory() as folder:
        root = Path(folder)
        store = LocalCliConfigStore(root / "config")
        store.save(
            provider="custom",
            base_url="https://gateway.example/v1",
            model_name="agent-model",
            api_mode="responses",
            api_key="secret-value",
        )
        runtime = LocalAgentRuntime(
            config_store=store,
            workspace_root=root / "workspace",
            data_root=root / "data",
        )
        gateway = PlanGateway()
        runtime.engine._gateway = gateway
        execution = runtime.run(
            "检查项目并给出方案",
            execution_mode="plan_only",
        )
        assert "计划已生成，本轮未执行修改" in execution.result["answer"]
        assert "1. 检查现有实现" in execution.result["answer"]
        assert "create_task_plan" in gateway.tool_names
        assert "read_workspace_file" in gateway.tool_names
        assert "write_workspace_file" not in gateway.tool_names
        assert "edit_workspace_file" not in gateway.tool_names
        assert "run_sandbox_command" not in gateway.tool_names
        assert any(
            event.get("eventName") == "run.plan_created"
            for event in execution.events
        )
        loaded = runtime.load_session(execution.result["runId"])
        assert loaded["executionMode"] == "plan_only"
        assert loaded["changes"] == []

    class ReferenceGateway:
        def __init__(self):
            self.messages = []

        def complete(self, messages, _config, **_kwargs):
            self.messages = [dict(item) for item in messages]
            return {"role": "assistant", "content": "引用读取完成。"}

    with TemporaryDirectory() as folder:
        root = Path(folder)
        workspace_root = root / "workspace"
        workspace_root.mkdir()
        (workspace_root / "notes.md").write_text(
            "private workspace evidence\n",
            encoding="utf-8",
        )
        store = LocalCliConfigStore(root / "config")
        store.save(
            provider="custom",
            base_url="https://gateway.example/v1",
            model_name="agent-model",
            api_mode="responses",
            api_key="secret-value",
        )
        runtime = LocalAgentRuntime(
            config_store=store,
            workspace_root=workspace_root,
            data_root=root / "data",
        )
        gateway = ReferenceGateway()
        runtime.engine._gateway = gateway
        execution = runtime.run("总结 @notes.md", tools=False)
        assert gateway.messages[-1]["content"] == "总结 @notes.md"
        assert "private workspace evidence" in gateway.messages[-2]["content"]
        assert "untrusted data" in gateway.messages[-2]["content"]
        assert execution.result["transcriptMessages"][-1] == {
            "role": "user",
            "content": "总结 @notes.md",
        }
        assert all(
            "private workspace evidence" not in str(message.get("content") or "")
            for message in execution.result["transcriptMessages"]
        )
        assert any(
            event.get("type") == "agent_step"
            and event.get("name") == "workspace_references"
            and event.get("status") == "success"
            for event in execution.events
        )
        assert execution.events[0]["type"] == "run_started"
        loaded = runtime.load_session(execution.result["runId"])
        assert any(
            "private workspace evidence" in str(message.get("content") or "")
            for message in loaded["contextMessages"]
        )
        assert all(
            "private workspace evidence" not in str(message.get("content") or "")
            for message in loaded["messages"]
        )

    class FakeGateway:
        def __init__(self):
            self.calls = 0

        def complete(self, _messages, _config, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_write",
                            "type": "function",
                            "function": {
                                "name": "write_workspace_file",
                                "arguments": json.dumps(
                                    {
                                        "path": "result.txt",
                                        "content": "done",
                                        "overwrite": False,
                                    }
                                ),
                            },
                        }
                    ],
                }
            return {"role": "assistant", "content": "写入完成。"}

    with TemporaryDirectory() as folder:
        root = Path(folder)
        registry = ToolRegistry()
        workspace = WorkspaceRuntime(
            root / "workspace",
            user_id=1,
            isolated_namespace=False,
            manage_root_permissions=False,
        )
        register_workspace_tools(registry, workspace)
        engine = LangGraphAgentEngine(
            gateway=FakeGateway(),
            checkpoint_db_path=root / "checkpoints.sqlite3",
        )
        try:
            engine.run(
                user_id=1,
                run_id="cancel_before_model",
                messages=[{"role": "user", "content": "stop"}],
                config={},
                registry=registry,
                cancel_check=lambda: True,
            )
        except AgentRunCancelledError:
            pass
        else:
            raise AssertionError("cancel check did not stop the graph")
        lifecycle_events = []
        first = engine.run(
            user_id=1,
            run_id="local_approval",
            messages=[{"role": "user", "content": "写入文件"}],
            config={},
            registry=registry,
            tool_event_callback=lifecycle_events.append,
        )
        assert first.paused
        assert lifecycle_events[-1]["status"] == "waiting"
        assert lifecycle_events[-1]["toolCallId"] == "call_write"
        second = engine.run(
            user_id=1,
            run_id="local_approval",
            messages=[],
            config={},
            registry=registry,
            resume_from_checkpoint=True,
            approval_decision="allow_once",
            tool_event_callback=lifecycle_events.append,
        )
        assert not second.paused
        assert second.answer == "写入完成。"
        assert (workspace.root / "result.txt").read_text(
            encoding="utf-8"
        ) == "done"
        assert lifecycle_events[-1]["status"] == "running"

    print("local cli runtime checks passed")


if __name__ == "__main__":
    main()
