from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.services.agent_event_protocol import AGENT_EVENT_SCHEMA_VERSION  # noqa: E402
from knowflow.tui.backend import question_with_workspace_attachments  # noqa: E402
from knowflow.tui.ink_bridge import PROTOCOL_VERSION, InkRuntimeBridge  # noqa: E402


class FakeBackend:
    model_label = "deepseek-chat"

    def __init__(self, workspace_root: str = "/workspace") -> None:
        self.cancelled = False
        self.reset_count = 0
        self.workspace_root = workspace_root
        self.selected_model_id = 1
        self.workspace_undo_args = None
        self.reasoning_effort = "default"
        self.execution_mode = "auto"
        self.attachment_paths = []

    def command_catalog(self):
        return [
            {
                "value": "/tool:read-file",
                "description": "读取文件",
                "source": "tool",
            }
        ]

    def model_catalog(self):
        return [
            {
                "id": 1,
                "name": "deepseek-chat",
                "modelName": "deepseek-chat",
                "provider": "deepseek",
                "apiMode": "chat_completions",
                "selected": self.selected_model_id == 1,
                "switchable": True,
            },
            {
                "id": 2,
                "name": "GPT 5.5",
                "modelName": "gpt-5.5",
                "provider": "openai",
                "apiMode": "responses",
                "selected": self.selected_model_id == 2,
                "switchable": True,
            },
        ]

    def select_model(self, model_id):
        self.selected_model_id = int(model_id)
        selected = next(item for item in self.model_catalog() if item["id"] == self.selected_model_id)
        self.model_label = selected["name"]
        return selected

    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        self.reasoning_effort = reasoning_effort
        self.execution_mode = execution_mode
        self.attachment_paths = list(attachment_paths or [])
        event_sink({"type": "text_delta", "text": "回答"})
        return AgentExecution(
            result={"paused": False, "runId": "run-ink", "answer": "回答"}
        )

    def run_shell(self, command, event_sink):
        event_sink(
            {
                "type": "tool_started",
                "runId": "shell-ink",
                "toolCallId": "shell-call",
                "toolName": "run_sandbox_command",
                "arguments": {"command": command},
            }
        )
        event_sink(
            {
                "type": "tool_result",
                "runId": "shell-ink",
                "toolCallId": "shell-call",
                "toolName": "run_sandbox_command",
                "status": "success",
                "output": {"stdout": "sandbox-ok\n", "exitCode": 0},
            }
        )
        return AgentExecution(
            result={
                "paused": False,
                "runId": "shell-ink",
                "answer": "sandbox-ok\n",
            }
        )

    def resolve(self, execution, decision, event_sink):
        event_sink({"type": "text_delta", "text": decision})
        return AgentExecution(
            result={"paused": False, "runId": "run-ink", "answer": decision}
        )

    def cancel(self, run_id):
        self.cancelled = True
        return True

    def reset(self):
        self.reset_count += 1

    def sandbox_diagnostics(self):
        return [{"name": "sandbox_smoke", "ready": True, "detail": "ok"}]

    def capability_status(self):
        return {
            "webSearch": {"configured": True, "enabled": True},
            "mcp": {"count": 0, "connected": 0, "servers": []},
            "skills": {"count": 1, "items": [{"slug": "research"}]},
            "memory": {"configured": False, "enabled": False},
        }

    def workspace_status(self):
        return {
            "projectRoot": self.workspace_root,
            "cwd": self.workspace_root,
            "allowedDirectories": [self.workspace_root],
            "protectedPatterns": [".git", ".env*"],
            "branch": "main",
            "dirty": False,
            "changedFiles": 0,
        }

    def workspace_diff(self, path=None):
        return {"files": [], "patch": ""}

    def workspace_add_directory(self, path):
        return {**self.workspace_status(), "message": f"Added {path}"}

    def workspace_change_directory(self, path):
        return {**self.workspace_status(), "cwd": path}

    def workspace_undo(self, operation_id=None, run_id=None):
        self.workspace_undo_args = (operation_id, run_id)
        return {
            "operationId": operation_id,
            "path": "file.txt",
            "workspace": self.workspace_status(),
        }

    def list_sessions(self, limit=20):
        return [
            {
                "runId": "run_ink",
                "title": "测试会话",
                "status": "completed",
                "updatedAt": 1_700_000_000,
                "cwd": "/workspace",
                "answer": "恢复后的回答预览",
            }
        ]

    def restore_session(self, run_id, event_sink):
        return AgentExecution(
            result={
                "paused": False,
                "runId": run_id,
                "restored": True,
                "messages": [{"role": "user", "content": "旧问题"}],
            }
        )

    def branch_session(
        self,
        title="",
        *,
        before_message_id=None,
        before_message_index=None,
    ):
        return {
            "runId": "run_branch",
            "title": title or "测试会话（分支）",
            "messageCount": 2,
            "messages": [
                {"role": "user", "content": "旧问题"},
                {"role": "assistant", "content": "旧回答"},
            ],
            "restoredQuestion": "要重新处理的问题" if before_message_index is not None else "",
        }

    def rewind_points(self):
        return [
            {
                "messageId": None,
                "messageIndex": 0,
                "preview": "要重新处理的问题",
            }
        ]

    def rename_session(self, title=""):
        return {"runId": "run_ink", "title": title}

    def export_session(self, filename=""):
        return {
            "path": f"/workspace/{filename or '测试会话.md'}",
            "filename": filename or "测试会话.md",
            "messageCount": 2,
        }

    def context_status(self):
        return {
            "usedTokens": 1200,
            "maxTokens": 96000,
            "usagePercent": 1.2,
            "autoCompactAtPercent": 75,
            "messageCount": 4,
            "transcriptMessageCount": 6,
            "roleTokens": {"system": 100, "user": 400, "assistant": 700},
        }

    def compact_context(self, instructions=""):
        return {
            "compacted": True,
            "metadata": {
                "reason": "manual",
                "originalTokens": 1200,
                "compactedTokens": 500,
            },
            "status": {"usedTokens": 500, "maxTokens": 96000},
            "instructionsSeen": instructions,
        }


class ApprovalBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[str] = []

    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        self.reasoning_effort = reasoning_effort
        self.execution_mode = execution_mode
        self.attachment_paths = list(attachment_paths or [])
        approval = {
            "type": "approval_required",
            "approvalId": "approval-ink",
            "toolName": "write_workspace_file",
            "risk": "write",
        }
        event_sink(approval)
        # Keep the run thread active long enough to exercise the early-decision queue.
        time.sleep(0.05)
        return AgentExecution(
            result={"paused": True, "runId": "run-approval"},
            events=[approval],
        )

    def resolve(self, execution, decision, event_sink):
        self.decisions.append(decision)
        return AgentExecution(
            result={"paused": False, "runId": "run-approval", "answer": "已批准"}
        )


class FailureBackend(FakeBackend):
    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        self.execution_mode = execution_mode
        self.attachment_paths = list(attachment_paths or [])
        event_sink(
            {
                "type": "agent_step",
                "runId": "run-failed",
                "stepId": "step-check",
                "title": "执行检查",
                "status": "failed",
                "errorCode": "project_check_failed",
                "errorMessage": "检查命令失败",
            }
        )
        raise RuntimeError("检查命令失败")


def wait_for(output: StringIO, event_type: str) -> list[dict]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        if any(row.get("type") == event_type for row in rows):
            return rows
        time.sleep(0.01)
    raise AssertionError(f"missing bridge event: {event_type}\n{output.getvalue()}")


def main() -> None:
    history_root = ROOT / ".tmp-check-cli-ink-history"
    os.environ["XDG_DATA_HOME"] = str(history_root)
    if history_root.exists():
        shutil.rmtree(history_root)
    output = StringIO()
    backend = FakeBackend()
    bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(),
        output_stream=output,
    )
    bridge.handle({
        "type": "submit",
        "requestId": "turn-1",
        "text": "你好",
        "reasoningEffort": "high",
        "executionMode": "plan_only",
        "attachmentPaths": ["README.md", "docs/product brief.md"],
    })
    rows = wait_for(output, "turn_completed")
    assert any(
        row.get("type") == "agent_event"
        and row.get("event", {}).get("type") == "text_delta"
        for row in rows
    )
    assert any(row.get("answer") == "回答" for row in rows)
    assert backend.reasoning_effort == "high"
    assert backend.execution_mode == "plan_only"
    assert backend.attachment_paths == ["README.md", "docs/product brief.md"]
    assert question_with_workspace_attachments(
        "检查文档",
        ["README.md", "docs/product brief.md", "../secret.txt", "README.md"],
    ) == '检查文档\n\n工作区上下文：\n@README.md\n@"docs/product brief.md"'

    failure_output = StringIO()
    failure_bridge = InkRuntimeBridge(
        FailureBackend("/failure-workspace"),
        input_stream=StringIO(),
        output_stream=failure_output,
    )
    failure_bridge.handle(
        {"type": "submit", "requestId": "turn-failed", "text": "执行检查"}
    )
    failure_rows = wait_for(failure_output, "turn_failed")
    structured_error = next(
        row["event"]
        for row in failure_rows
        if row.get("type") == "agent_event"
        and row.get("event", {}).get("eventName") == "error.raised"
    )
    assert structured_error["error"]["code"] == "RuntimeError"
    assert structured_error["recoveryActions"] == ["continue", "retry", "fix"]
    turn_failure = next(row for row in failure_rows if row.get("type") == "turn_failed")
    assert turn_failure["errorCode"] == "RuntimeError"
    assert turn_failure["recoveryActions"] == ["continue", "retry", "fix"]

    shell_output = StringIO()
    shell_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(),
        output_stream=shell_output,
    )
    shell_bridge.handle(
        {"type": "shell", "requestId": "shell-1", "command": "echo sandbox-ok"}
    )
    shell_rows = wait_for(shell_output, "turn_completed")
    assert any(
        row.get("type") == "agent_event"
        and row.get("event", {}).get("toolName") == "run_sandbox_command"
        for row in shell_rows
    )
    assert shell_rows[-1]["answer"] == "sandbox-ok\n"

    ready_output = StringIO()
    ready_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(""),
        output_stream=ready_output,
    )
    ready_bridge.run()
    handshake = json.loads(ready_output.getvalue().splitlines()[0])
    assert handshake["type"] == "runtime_handshake"
    assert handshake["protocolVersion"] == PROTOCOL_VERSION
    assert handshake["agentEventSchemaVersion"] == AGENT_EVENT_SCHEMA_VERSION
    assert handshake["workspace"]["branch"] == "main"
    ready = json.loads(ready_output.getvalue().splitlines()[1])
    assert ready["protocolVersion"] == PROTOCOL_VERSION
    assert ready["agentEventSchemaVersion"] == AGENT_EVENT_SCHEMA_VERSION
    assert ready["workspace"]["branch"] == "main"
    assert ready["sessions"][0]["runId"] == "run_ink"
    assert ready["history"] == ["你好", "!echo sandbox-ok"]
    assert ready["models"][0]["selected"] is True

    ready_bridge.handle({"type": "models", "action": "list"})
    model_rows = wait_for(ready_output, "model_list")
    assert len(model_rows[-1]["models"]) == 2
    ready_bridge.handle({"type": "models", "action": "use", "modelId": 2})
    model_rows = wait_for(ready_output, "model_changed")
    assert model_rows[-1]["model"] == "GPT 5.5"
    assert backend.selected_model_id == 2

    isolated_output = StringIO()
    isolated_bridge = InkRuntimeBridge(
        FakeBackend("/other-workspace"),
        input_stream=StringIO(""),
        output_stream=isolated_output,
    )
    isolated_bridge.run()
    isolated_ready = json.loads(isolated_output.getvalue().splitlines()[1])
    assert isolated_ready["history"] == []

    ready_bridge.handle({"type": "history", "action": "list"})
    history_rows = wait_for(ready_output, "history_result")
    assert history_rows[-1]["history"] == ["你好", "!echo sandbox-ok"]
    ready_bridge.handle({"type": "history", "action": "clear"})
    history_rows = wait_for(ready_output, "history_result")
    assert history_rows[-1]["action"] == "clear"
    assert history_rows[-1]["history"] == []

    ready_bridge.handle({"type": "workspace", "action": "status"})
    workspace_rows = wait_for(ready_output, "workspace_result")
    assert workspace_rows[-1]["result"]["projectRoot"] == "/workspace"
    ready_bridge.handle(
        {
            "type": "workspace",
            "action": "undo",
            "operationId": "edit_report",
            "runId": "run_ink",
        }
    )
    workspace_rows = wait_for(ready_output, "workspace_result")
    assert backend.workspace_undo_args == ("edit_report", "run_ink")
    assert workspace_rows[-1]["result"]["operationId"] == "edit_report"
    ready_bridge.handle({"type": "sessions", "limit": 10})
    session_rows = wait_for(ready_output, "session_list")
    assert session_rows[-1]["sessions"][0]["title"] == "测试会话"
    assert session_rows[-1]["sessions"][0]["answer"] == "恢复后的回答预览"
    assert set(session_rows[-1]["sessions"][0]) == {
        "runId",
        "title",
        "status",
        "updatedAt",
        "cwd",
        "answer",
    }
    ready_bridge.handle({"type": "branch_session", "title": "方案B"})
    branch_rows = wait_for(ready_output, "session_branched")
    assert branch_rows[-1]["result"]["runId"] == "run_branch"
    assert branch_rows[-1]["result"]["title"] == "方案B"
    ready_bridge.handle({"type": "rewind_points"})
    rewind_rows = wait_for(ready_output, "rewind_points")
    assert rewind_rows[-1]["points"][0]["messageIndex"] == 0
    ready_bridge.handle({"type": "branch_session", "messageIndex": 0})
    rewound_rows = wait_for(ready_output, "session_branched")
    assert rewound_rows[-1]["result"]["restoredQuestion"] == "要重新处理的问题"
    ready_bridge.handle({"type": "rename_session", "title": "发布复盘"})
    rename_rows = wait_for(ready_output, "session_renamed")
    assert rename_rows[-1]["result"]["runId"] == "run_ink"
    assert rename_rows[-1]["result"]["title"] == "发布复盘"
    ready_bridge.handle({"type": "export_session", "filename": "会话记录.md"})
    export_rows = wait_for(ready_output, "session_exported")
    assert export_rows[-1]["result"]["filename"] == "会话记录.md"
    assert export_rows[-1]["result"]["messageCount"] == 2
    ready_bridge.handle({"type": "context", "action": "status"})
    context_rows = wait_for(ready_output, "context_status")
    assert context_rows[-1]["status"]["usedTokens"] == 1200
    ready_bridge.handle(
        {
            "type": "context",
            "action": "compact",
            "instructions": "保留工作区边界",
        }
    )
    compact_rows = wait_for(ready_output, "context_compacted")
    assert compact_rows[-1]["metadata"]["compactedTokens"] == 500
    assert compact_rows[-1]["instructionsSeen"] == "保留工作区边界"

    approval_output = StringIO()
    approval_backend = ApprovalBackend()
    approval_bridge = InkRuntimeBridge(
        approval_backend,
        input_stream=StringIO(),
        output_stream=approval_output,
    )
    approval_bridge.handle(
        {"type": "submit", "requestId": "turn-approval", "text": "写文件"}
    )
    wait_for(approval_output, "agent_event")
    approval_bridge.handle({"type": "approve", "decision": "allow_once"})
    approval_rows = wait_for(approval_output, "turn_completed")
    assert approval_backend.decisions == ["allow_once"]
    assert approval_rows[-1]["answer"] == "已批准"

    bridge.handle({"type": "doctor"})
    rows = wait_for(output, "doctor_result")
    assert rows[-1]["checks"][0]["ready"] is True
    bridge.handle({"type": "capabilities", "section": "tools"})
    rows = wait_for(output, "capability_status")
    assert rows[-1]["status"]["webSearch"]["enabled"] is True

    from knowflow import cli as cli_module  # noqa: E402
    from knowflow.tui import ink_bridge as ink_bridge_module  # noqa: E402

    update_output = StringIO()
    update_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(),
        output_stream=update_output,
    )
    original_update_command = cli_module._cli_update_command
    original_installed_version = cli_module._installed_cli_version
    original_update_run = ink_bridge_module.subprocess.run
    versions = iter(("0.35.0", "0.36.0"))
    try:
        cli_module._cli_update_command = lambda: ["pipx", "install", "--force", "agentlens"]
        cli_module._installed_cli_version = lambda: next(versions)
        ink_bridge_module.subprocess.run = lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        )
        update_bridge.handle({"type": "cli_update"})
        update_rows = wait_for(update_output, "cli_update_completed")
    finally:
        cli_module._cli_update_command = original_update_command
        cli_module._installed_cli_version = original_installed_version
        ink_bridge_module.subprocess.run = original_update_run
    assert update_rows[0]["type"] == "cli_update_started"
    assert update_rows[-1]["currentVersion"] == "0.35.0"
    assert update_rows[-1]["nextVersion"] == "0.36.0"
    assert update_rows[-1]["restartRequired"] is True

    failed_update_output = StringIO()
    failed_update_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(),
        output_stream=failed_update_output,
    )
    try:
        cli_module._cli_update_command = lambda: ["pipx", "install", "private-package"]
        cli_module._installed_cli_version = lambda: "0.35.0"
        ink_bridge_module.subprocess.run = lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, "", "https://x-access-token:ghp_secretvalue@example.invalid/repo"
        )
        failed_update_bridge.handle({"type": "cli_update"})
        failed_update_rows = wait_for(failed_update_output, "cli_update_failed")
    finally:
        cli_module._cli_update_command = original_update_command
        cli_module._installed_cli_version = original_installed_version
        ink_bridge_module.subprocess.run = original_update_run
    assert "ghp_secretvalue" not in str(failed_update_rows[-1])
    assert "agentlens update" in failed_update_rows[-1]["message"]

    bridge.handle({"type": "reset"})
    assert backend.reset_count == 1

    package = (ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert '"ink_tui/*.mjs"' in package
    bundle = ROOT / "backend" / "knowflow" / "ink_tui" / "index.mjs"
    assert bundle.is_file() and bundle.stat().st_size > 100_000
    bundle_source = bundle.read_text(encoding="utf-8")
    assert "KNOWFLOW_CLI_MOUSE" in bundle_source
    assert "KNOWFLOW_CLI_FULLSCREEN" in bundle_source
    node = shutil.which("node")
    if node:
        result = subprocess.run(
            [node, str(bundle), "--self-test"],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "knowflow-ink-ok"

    entry_source = (ROOT / "cli-tui" / "src" / "index.jsx").read_text(
        encoding="utf-8"
    )
    assert "alternateScreen: fullscreenEnabled" in entry_source
    assert "MouseProvider" in entry_source
    assert "autoEnable={mouseEnabled}" in entry_source
    assert "fullscreenEnabled={fullscreenEnabled}" in entry_source
    assert "mouseEnabled={mouseEnabled}" in entry_source
    assert "mouseEnabled />" not in entry_source
    launcher_source = (ROOT / "backend" / "knowflow" / "tui" / "ink_launcher.py").read_text(
        encoding="utf-8"
    )
    assert '"workspaceRoot"' in launcher_source
    assert '"startupAction"' in launcher_source
    assert 'startup_action in {"resume", "continue"}' in launcher_source
    assert "startupAction={String(config.startupAction || '')}" in entry_source
    app_source = (ROOT / "cli-tui" / "src" / "app.jsx").read_text(
        encoding="utf-8"
    )
    assert "KNOWFLOW_CLI_FULLSCREEN" in app_source
    assert "KNOWFLOW_CLI_MOUSE" in app_source
    assert "<ScrollView" in app_source
    assert "useOnWheel" in app_source
    assert "flexShrink={1}" in app_source
    assert "if (!fullscreenEnabled)" in app_source
    assert "终端滚轮选择复制" in app_source
    assert "const RECOVERY_ACTION_OPTIONS" in app_source
    assert "row?.recoveryActions) && row.recoveryActions.length" in app_source
    assert "←→选择 · Enter执行" in app_source
    assert "recoverFailedTool(recoveryItems[Math.min(recoveryChoiceRef.current" in app_source
    assert "<QueuePreview items={queue}" in app_source
    assert "/tasks remove <序号>" in app_source
    assert "transcriptSnapshot" in app_source
    assert "对话记录" in app_source
    assert "const ActiveTaskAnchor" in app_source
    assert "activeTaskAnchorMetrics" in app_source
    assert "fullscreenEnabled && frozen.running" in app_source
    assert "<ActiveTaskAnchor" in app_source
    assert "goal={lastQuestion}" in app_source
    assert "metrics={activeTaskMetrics}" in app_source
    assert "state={runHeader}" in app_source
    assert "runtime_handshake" in app_source
    assert "agentEventSchemaVersion" in app_source
    assert "cli_update_completed" in app_source
    assert "client.send({type: 'cli_update'})" in app_source

    shutil.rmtree(history_root, ignore_errors=True)
    print("Ink TUI bridge, bundle, and runtime protocol checks passed")


if __name__ == "__main__":
    main()
