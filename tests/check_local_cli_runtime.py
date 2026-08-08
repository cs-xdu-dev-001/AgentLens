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
