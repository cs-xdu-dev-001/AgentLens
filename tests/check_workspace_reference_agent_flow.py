from __future__ import annotations

import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.schemas import ChatRequest  # noqa: E402
from knowflow.services.agent_loop import ToolRegistry  # noqa: E402
from knowflow.services.workspace_runtime import WorkspaceRuntime  # noqa: E402


class Gateway:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def complete(self, messages, _config, **_kwargs):
        self.messages = [dict(message) for message in messages]
        return {"role": "assistant", "content": "引用内容已用于回答。"}


class Pool:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def main() -> None:
    runtime = importlib.import_module("knowflow.runtime")
    extensions = importlib.import_module("knowflow.routers.extensions")
    session_id = f"workspace-reference-{uuid.uuid4().hex}"
    runtime.execute(
        """
        INSERT INTO chat_session(id, user_id, title, created_at, updated_at)
        VALUES (:id, 1, 'Workspace reference', :now, :now)
        """,
        {"id": session_id, "now": runtime.now_str()},
    )
    with TemporaryDirectory() as folder:
        workspace_base = Path(folder) / "workspaces"
        workspace = WorkspaceRuntime(
            workspace_base,
            user_id=1,
            max_file_bytes=100_000,
        )
        workspace.write_text(
            "README.md",
            "web-only workspace evidence",
            overwrite=False,
        )
        workspace.write_text(
            "AGENTS.md",
            "Reply with a concise verification summary.",
            overwrite=False,
        )
        gateway = Gateway()
        originals = {
            "WORKSPACE_DIR": extensions.WORKSPACE_DIR,
            "WORKSPACE_ENABLED": extensions.WORKSPACE_ENABLED,
            "WORKSPACE_MAX_FILE_BYTES": extensions.WORKSPACE_MAX_FILE_BYTES,
            "ensure_session": extensions.ensure_session,
            "get_model_config": extensions.get_model_config,
            "build_tool_registry": extensions.build_tool_registry,
            "McpRunSessionPool": extensions.McpRunSessionPool,
            "gateway": extensions.gateway,
        }
        extensions.WORKSPACE_DIR = workspace_base
        extensions.WORKSPACE_ENABLED = True
        extensions.WORKSPACE_MAX_FILE_BYTES = 100_000
        extensions.ensure_session = lambda *args, **kwargs: session_id
        extensions.get_model_config = lambda *args, **kwargs: {}
        extensions.build_tool_registry = lambda *args, **kwargs: ToolRegistry()
        extensions.McpRunSessionPool = Pool
        extensions.gateway = gateway
        try:
            result = extensions.execute_agent_chat(
                ChatRequest(
                    question="总结 @README.md",
                    sessionId=session_id,
                    autoAgent=False,
                    enableTools=False,
                ),
                1,
            )
        finally:
            for name, value in originals.items():
                setattr(extensions, name, value)

    assert gateway.messages[-1]["content"].endswith(
        "User question: 总结 @README.md"
    )
    assert "web-only workspace evidence" in gateway.messages[-2]["content"]
    project_messages = [
        message
        for message in gateway.messages
        if message.get("role") == "system"
        and "Project instructions: AGENTS.md" in str(message.get("content") or "")
    ]
    assert len(project_messages) == 1
    assert "Reply with a concise verification summary." in project_messages[0]["content"]
    visible = runtime.fetch_one(
        """
        SELECT content FROM chat_message
        WHERE session_id=:session_id AND role='user'
        ORDER BY id DESC LIMIT 1
        """,
        {"session_id": session_id},
    )
    assert visible and visible["content"] == "总结 @README.md"
    reference_steps = [
        step
        for step in result["trace"]
        if step.get("name") == "workspace_references"
    ]
    assert len(reference_steps) == 1
    assert reference_steps[0]["status"] == "success"
    public_trace = str(reference_steps[0])
    assert "web-only workspace evidence" not in public_trace
    print("web agent loads hidden workspace references without changing the prompt")


if __name__ == "__main__":
    main()
