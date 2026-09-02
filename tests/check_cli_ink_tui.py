from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Event
import time
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.services.agent_event_protocol import AGENT_EVENT_SCHEMA_VERSION  # noqa: E402
from knowflow.tui.backend import question_with_workspace_attachments  # noqa: E402
from knowflow.tui.ink_bridge import (  # noqa: E402
    PROTOCOL_VERSION,
    InkRuntimeBridge,
    _history_scope,
)
from knowflow.tui import ink_launcher  # noqa: E402
from knowflow.tui import run_tui  # noqa: E402


def check_launcher_single_run() -> None:
    calls: list[list[str]] = []
    original_run = ink_launcher.subprocess.run
    original_which = ink_launcher.shutil.which
    original_entry_path = ink_launcher._entry_path
    original_node_major = ink_launcher._node_major
    previous_allow = os.environ.get("KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED")

    def fake_run(command, **_kwargs):
        calls.append([str(part) for part in command])
        return SimpleNamespace(returncode=0)

    try:
        os.environ["KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED"] = "1"
        ink_launcher.subprocess.run = fake_run
        ink_launcher.shutil.which = lambda _name: "node"
        ink_launcher._entry_path = lambda: Path("index.mjs")
        ink_launcher._node_major = lambda _node: 22
        backend = SimpleNamespace(remote_client=None, local_agent=None)
        assert ink_launcher.run_ink_tui(backend) is True
    finally:
        ink_launcher.subprocess.run = original_run
        ink_launcher.shutil.which = original_which
        ink_launcher._entry_path = original_entry_path
        ink_launcher._node_major = original_node_major
        if previous_allow is None:
            os.environ.pop("KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED", None)
        else:
            os.environ["KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED"] = previous_allow

    assert len(calls) == 1
    assert calls[0] == ["node", "index.mjs"]


def check_launcher_aligns_child_cwd() -> None:
    original_run = ink_launcher.subprocess.run
    original_which = ink_launcher.shutil.which
    original_entry_path = ink_launcher._entry_path
    original_node_major = ink_launcher._node_major
    previous_allow = os.environ.get("KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = [str(part) for part in command]
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    workspace_root = ROOT / "backend"
    try:
        os.environ["KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED"] = "1"
        ink_launcher.subprocess.run = fake_run
        ink_launcher.shutil.which = lambda _name: "node"
        ink_launcher._entry_path = lambda: Path("index.mjs")
        ink_launcher._node_major = lambda _node: 22
        backend = SimpleNamespace(
            remote_client=None,
            local_agent=SimpleNamespace(workspace_root=workspace_root),
        )
        assert ink_launcher.run_ink_tui(backend) is True
    finally:
        ink_launcher.subprocess.run = original_run
        ink_launcher.shutil.which = original_which
        ink_launcher._entry_path = original_entry_path
        ink_launcher._node_major = original_node_major
        if previous_allow is None:
            os.environ.pop("KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED", None)
        else:
            os.environ["KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED"] = previous_allow

    assert captured["command"] == ["node", "index.mjs"]
    assert captured["cwd"] == str(workspace_root)


def check_auto_falls_back_after_ink_crash() -> None:
    # Patch the launcher module used by run_tui without invoking either UI.
    launcher = __import__("knowflow.tui.ink_launcher", fromlist=["run_ink_tui"])
    original_launcher = launcher.run_ink_tui
    original_textual = __import__("knowflow.tui.app", fromlist=["run_tui"])
    original_textual_run = original_textual.run_tui
    previous_mode = os.environ.get("KNOWFLOW_TUI")
    fallback_calls = []

    def crash(*_args, **_kwargs):
        raise launcher.InkTuiLaunchError("ink crashed")

    try:
        os.environ["KNOWFLOW_TUI"] = "auto"
        launcher.run_ink_tui = crash
        original_textual.run_tui = lambda *_args, **kwargs: fallback_calls.append(kwargs)
        run_tui(SimpleNamespace())
        assert len(fallback_calls) == 1

        os.environ["KNOWFLOW_TUI"] = "ink"
        try:
            run_tui(SimpleNamespace())
        except launcher.InkTuiLaunchError:
            pass
        else:
            raise AssertionError("explicit Ink mode must surface launch failures")
    finally:
        launcher.run_ink_tui = original_launcher
        original_textual.run_tui = original_textual_run
        if previous_mode is None:
            os.environ.pop("KNOWFLOW_TUI", None)
        else:
            os.environ["KNOWFLOW_TUI"] = previous_mode


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

    def local_model_configuration(self):
        return {
            "provider": "custom",
            "baseUrl": "https://api.example.com/v1",
            "modelName": self.model_label,
            "apiMode": "chat_completions",
            "hasApiKey": True,
            "overriddenFields": {},
        }

    def configure_local_model(self, value):
        assert value["apiKey"] == "sk-test-secret"
        self.model_label = str(value["modelName"])
        return {
            "detail": "连接可用",
            "model": self.model_label,
            "config": self.local_model_configuration(),
        }

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

    def workspace_switch_root(self, path):
        self.workspace_root = path
        self.reset()
        return {
            **self.workspace_status(),
            "workspaceKind": "project",
            "message": f"已切换工作区：{path}",
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

    def list_sessions(self, limit=20, archived=False):
        return [
            {
                "runId": "run_ink",
                "title": "测试会话",
                "pinned": False,
                "archived": bool(archived),
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

    def set_session_pinned(self, pinned=False, run_id="", session_id=""):
        return {"runId": run_id or "run_ink", "pinned": bool(pinned)}

    def set_session_archived(self, archived=False, run_id="", session_id=""):
        return {
            "runId": run_id or "run_ink",
            "sessionId": session_id,
            "archived": bool(archived),
            "pinned": False,
        }

    def delete_session(self, run_id="", session_id=""):
        return {
            "runId": run_id or "run_ink",
            "sessionId": session_id,
            "deleted": True,
            "current": False,
        }

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


class LongOutputBackend(FakeBackend):
    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        event_sink(
            {
                "eventName": "tool.completed",
                "type": "tool_result",
                "runId": "run-long-output",
                "sequence": 42,
                "eventId": "event-long-output",
                "toolCallId": "call-long-output",
                "toolName": "run_sandbox_command",
                "status": "success",
                "output": "x" * 20_000,
            }
        )
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run-long-output",
                "answer": "完成",
            }
        )


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


class BlockingShutdownBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__("/shutdown-workspace")
        self.started = Event()
        self.release = Event()
        self.finished = Event()

    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        event_sink({"type": "run_started", "runId": "run-shutdown"})
        self.started.set()
        self.release.wait(2)
        self.finished.set()
        return AgentExecution(
            result={
                "paused": False,
                "runId": "run-shutdown",
                "answer": "",
                "cancelled": True,
            }
        )

    def cancel(self, run_id):
        self.cancelled = True
        self.release.set()
        return True


class BlockingCancelBackend(BlockingShutdownBackend):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_count = 0
        self.cancel_started = Event()
        self.cancel_release = Event()

    def cancel(self, run_id):
        self.cancel_count += 1
        self.cancelled = True
        self.cancel_started.set()
        self.cancel_release.wait(1)
        return True


class PausedAfterCancelBackend(BlockingShutdownBackend):
    def run(
        self,
        question,
        event_sink,
        reasoning_effort="default",
        execution_mode="auto",
        attachment_paths=None,
    ):
        approval = {
            "type": "approval_required",
            "runId": "run-paused-after-cancel",
            "approvalId": "approval-after-cancel",
            "toolName": "write_workspace_file",
            "risk": "write",
        }
        self.started.set()
        self.release.wait(2)
        self.finished.set()
        return AgentExecution(
            result={"paused": True, "runId": "run-paused-after-cancel"},
            events=[approval],
        )


class BrokenOutput(StringIO):
    def write(self, value):
        raise BrokenPipeError("output closed")


def wait_for(output: StringIO, event_type: str) -> list[dict]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        if any(row.get("type") == event_type for row in rows):
            return rows
        time.sleep(0.01)
    raise AssertionError(f"missing bridge event: {event_type}\n{output.getvalue()}")


def main() -> None:
    check_launcher_single_run()
    check_launcher_aligns_child_cwd()
    check_auto_falls_back_after_ink_crash()
    remote_a = SimpleNamespace(
        remote_client=SimpleNamespace(server="https://agent.example", token="session-a")
    )
    remote_b = SimpleNamespace(
        remote_client=SimpleNamespace(server="https://agent.example", token="session-b")
    )
    assert _history_scope(remote_a) != _history_scope(remote_b)
    assert "session-a" not in _history_scope(remote_a)
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

    broken_output_bridge = InkRuntimeBridge(
        FakeBackend("/broken-output-workspace"),
        input_stream=StringIO(),
        output_stream=BrokenOutput(),
    )
    broken_output_bridge.handle(
        {"type": "submit", "requestId": "turn-broken-output", "text": "输出已关闭"}
    )
    broken_output_deadline = time.monotonic() + 1
    while broken_output_bridge._running and time.monotonic() < broken_output_deadline:
        time.sleep(0.01)
    assert broken_output_bridge._running is False
    assert broken_output_bridge._worker_thread is None

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

    detail_output = StringIO()
    detail_bridge = InkRuntimeBridge(
        LongOutputBackend("/long-output-workspace"),
        input_stream=StringIO(),
        output_stream=detail_output,
    )
    detail_bridge.handle(
        {"type": "submit", "requestId": "turn-long-output", "text": "输出长记录"}
    )
    detail_rows = wait_for(detail_output, "turn_completed")
    preview = next(
        row["event"]
        for row in detail_rows
        if row.get("type") == "agent_event"
        and row.get("event", {}).get("eventId") == "event-long-output"
    )
    assert preview["outputTruncated"] is True
    assert len(preview["output"]) == 12_000
    detail_bridge.handle(
        {
            "type": "agent_event_detail",
            "requestId": "detail-1",
            "runId": "run-long-output",
            "sequence": 42,
            "eventId": "event-long-output",
            "toolCallId": "call-long-output",
        }
    )
    detail_rows = wait_for(detail_output, "agent_event_detail")
    full_event = detail_rows[-1]["event"]
    assert not full_event.get("outputTruncated", False)
    assert len(full_event["output"]) == 20_000

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
    assert ready["queueDurable"] is True

    queued_item = {
        "id": "queue-bridge",
        "text": "检查队列恢复",
        "displayText": "检查队列恢复",
        "priority": "next",
        "sequence": 1,
        "mode": "prompt",
        "reasoningEffort": "high",
        "permissionMode": "ask",
        "attachmentPaths": [],
    }
    ready_bridge.handle(
        {"type": "queue", "action": "sync", "items": [queued_item], "paused": True}
    )
    queue_rows = wait_for(ready_output, "queue_saved")
    assert queue_rows[-1]["count"] == 1
    ready_bridge.handle(
        {
            "type": "queue",
            "action": "claim",
            "itemId": "queue-bridge",
            "requestId": "turn-queue",
            "item": queued_item,
        }
    )
    queue_rows = wait_for(ready_output, "queue_claimed")
    assert queue_rows[-1]["requestId"] == "turn-queue"
    assert ready_bridge.queue_store.load()["items"][0]["lifecycle"] == "started"
    restart_output = StringIO()
    restart_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(""),
        output_stream=restart_output,
    )
    restart_bridge.run()
    restart_ready = json.loads(restart_output.getvalue().splitlines()[1])
    assert restart_ready["queueRecovered"] == 1
    assert restart_ready["queuePaused"] is True
    assert restart_ready["queueDurable"] is True
    assert restart_ready["queue"][0]["lifecycle"] == "queued"
    assert ready_bridge.queue_store.sync([], paused=False)
    original_queue_sync = ready_bridge.queue_store.sync
    try:
        ready_bridge.queue_store.sync = lambda _items, paused: False
        ready_bridge.handle(
            {"type": "queue", "action": "sync", "items": [queued_item], "paused": False}
        )
        queue_rows = wait_for(ready_output, "queue_failed")
    finally:
        ready_bridge.queue_store.sync = original_queue_sync
    assert queue_rows[-1]["action"] == "sync"
    assert "仅在本次运行" in queue_rows[-1]["message"]

    shutdown_backend = BlockingShutdownBackend()
    shutdown_bridge = InkRuntimeBridge(
        shutdown_backend,
        input_stream=StringIO(
            json.dumps({
                "type": "submit",
                "requestId": "turn-shutdown",
                "text": "等待取消",
            }) + "\n"
        ),
        output_stream=StringIO(),
    )
    shutdown_bridge.run()
    assert shutdown_backend.cancelled
    assert shutdown_backend.finished.is_set()

    blocking_cancel_backend = BlockingCancelBackend()
    blocking_cancel_output = StringIO()
    blocking_cancel_bridge = InkRuntimeBridge(
        blocking_cancel_backend,
        input_stream=StringIO(),
        output_stream=blocking_cancel_output,
    )
    blocking_cancel_bridge.handle(
        {"type": "submit", "requestId": "turn-blocked-cancel", "text": "取消超时"}
    )
    assert blocking_cancel_backend.started.wait(1)
    cancel_started = time.monotonic()
    blocking_cancel_bridge.handle({"type": "cancel"})
    assert time.monotonic() - cancel_started < 0.5
    assert blocking_cancel_backend.cancel_started.wait(1)
    blocking_cancel_bridge.handle({"type": "cancel"})
    assert blocking_cancel_backend.cancel_count == 1
    blocking_cancel_backend.release.set()
    assert blocking_cancel_backend.finished.wait(1)
    blocking_cancel_bridge.handle({"type": "reset"})
    blocking_cancel_bridge.handle(
        {"type": "models", "action": "use", "modelId": 2}
    )
    blocking_cancel_bridge.handle(
        {"type": "workspace", "action": "cd", "path": "/other"}
    )
    blocking_cancel_bridge.handle(
        {"type": "branch_session", "title": "不得创建"}
    )
    assert blocking_cancel_backend.reset_count == 0
    assert blocking_cancel_backend.selected_model_id == 1
    blocking_cancel_bridge.handle(
        {"type": "submit", "requestId": "turn-too-early", "text": "不得启动"}
    )
    busy_rows = wait_for(blocking_cancel_output, "busy")
    assert busy_rows[-1]["message"] == "当前任务尚未结束。"
    assert not any(
        row.get("type")
        in {"session_reset", "model_changed", "workspace_result", "session_branched"}
        for row in busy_rows
    )
    assert blocking_cancel_bridge._request_id == "turn-blocked-cancel"
    assert "不得启动" not in blocking_cancel_bridge.history_store.load()
    blocking_cancel_backend.cancel_release.set()
    cancel_rows = wait_for(blocking_cancel_output, "cancel_requested")
    cancel_result = next(
        row for row in reversed(cancel_rows) if row.get("type") == "cancel_requested"
    )
    assert cancel_result["accepted"] is True
    blocking_cancel_bridge.handle({"type": "cancel"})
    assert blocking_cancel_backend.cancel_count == 1

    paused_cancel_backend = PausedAfterCancelBackend()
    paused_cancel_output = StringIO()
    paused_cancel_bridge = InkRuntimeBridge(
        paused_cancel_backend,
        input_stream=StringIO(),
        output_stream=paused_cancel_output,
    )
    paused_cancel_bridge.handle(
        {
            "type": "submit",
            "requestId": "turn-paused-after-cancel",
            "text": "取消后不得暂停",
        }
    )
    assert paused_cancel_backend.started.wait(1)
    paused_cancel_bridge.handle({"type": "cancel"})
    paused_cancel_rows = wait_for(paused_cancel_output, "turn_completed")
    assert paused_cancel_backend.finished.is_set()
    assert not any(row.get("type") == "turn_paused" for row in paused_cancel_rows)
    assert paused_cancel_rows[-1]["cancelled"] is True
    assert paused_cancel_bridge._pending is None

    ready_bridge.handle({"type": "models", "action": "list"})
    model_rows = wait_for(ready_output, "model_list")
    assert len(model_rows[-1]["models"]) == 2
    ready_bridge.handle({"type": "models", "action": "use", "modelId": 2})
    model_rows = wait_for(ready_output, "model_changed")
    assert model_rows[-1]["model"] == "GPT 5.5"
    assert backend.selected_model_id == 2

    ready_bridge.handle({"type": "local_model_config", "action": "get"})
    config_rows = wait_for(ready_output, "local_model_config")
    assert config_rows[-1]["config"]["hasApiKey"] is True
    assert "apiKey" not in config_rows[-1]["config"]
    ready_bridge.handle(
        {
            "type": "local_model_config",
            "action": "test_and_save",
            "config": {
                "baseUrl": "https://api.example.com/v1",
                "modelName": "gpt-5.6-sol",
                "apiMode": "responses",
                "apiKey": "sk-test-secret",
            },
        }
    )
    config_rows = wait_for(ready_output, "local_model_config_saved")
    assert config_rows[-1]["model"] == "gpt-5.6-sol"
    assert "sk-test-secret" not in ready_output.getvalue()

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
            "action": "diff",
            "path": "reports/report.md",
            "requestId": "change-diff-1",
        }
    )
    workspace_rows = wait_for(ready_output, "workspace_result")
    assert workspace_rows[-1]["requestId"] == "change-diff-1"
    initial_history_path = ready_bridge.history_store.path
    ready_bridge._running = True
    ready_bridge.handle(
        {"type": "workspace", "action": "switch", "path": "/workspace/busy"}
    )
    assert wait_for(ready_output, "workspace_failed")[-1]["action"] == "switch"
    assert backend.workspace_root == "/workspace"
    ready_bridge._running = False
    ready_bridge.handle(
        {"type": "workspace", "action": "switch", "path": "/workspace/project"}
    )
    workspace_rows = wait_for(ready_output, "workspace_result")
    assert workspace_rows[-1]["action"] == "switch"
    assert workspace_rows[-1]["result"]["projectRoot"] == "/workspace/project"
    assert workspace_rows[-1]["sessions"][0]["runId"] == "run_ink"
    assert ready_bridge.history_store.path != initial_history_path
    assert wait_for(ready_output, "session_reset")
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
        "sessionId",
        "title",
        "pinned",
        "archived",
        "status",
        "updatedAt",
        "cwd",
        "answer",
    }

    class PausedRestoreBackend(FakeBackend):
        def restore_session(self, run_id, event_sink):
            event = {
                "type": "approval_required",
                "runId": run_id,
                "approvalId": "approval_restored",
                "toolName": "write_workspace_file",
                "risk": "write",
            }
            event_sink(event)
            return AgentExecution(
                result={
                    "paused": True,
                    "runId": run_id,
                    "restored": True,
                    "messages": [
                        {"role": "user", "content": "恢复旧问题"},
                        {"role": "assistant", "content": "等待审批"},
                    ],
                },
                events=[event],
            )

    paused_output = StringIO()
    paused_bridge = InkRuntimeBridge(
        PausedRestoreBackend(),
        input_stream=StringIO(),
        output_stream=paused_output,
    )
    paused_bridge.handle(
        {
            "type": "resume_session",
            "requestId": "resume-paused",
            "runId": "run_waiting",
        }
    )
    paused_rows = wait_for(paused_output, "turn_paused")
    paused_result = next(
        row for row in reversed(paused_rows) if row.get("type") == "turn_paused"
    )
    assert paused_result["restored"] is True
    assert paused_result["messages"][0]["content"] == "恢复旧问题"
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
    ready_bridge.handle({"type": "session_pin", "runId": "run_ink", "pinned": True})
    pin_rows = wait_for(ready_output, "session_pinned")
    assert pin_rows[-1]["result"] == {
        "runId": "run_ink",
        "pinned": True,
    }
    ready_bridge.handle({"type": "session_archive", "runId": "run_ink", "archived": True})
    archive_rows = wait_for(ready_output, "session_archived")
    assert archive_rows[-1]["result"] == {
        "runId": "run_ink",
        "sessionId": "",
        "archived": True,
        "pinned": False,
    }
    ready_bridge._running = True
    ready_bridge.handle({"type": "session_delete", "runId": "run_ink"})
    assert wait_for(ready_output, "busy")[-1]["message"] == (
        "请先取消当前任务，再永久删除会话。"
    )
    ready_bridge._running = False
    ready_bridge.handle({"type": "session_delete", "runId": "run_ink"})
    delete_rows = wait_for(ready_output, "session_deleted")
    assert delete_rows[-1]["result"] == {
        "runId": "run_ink",
        "sessionId": "",
        "deleted": True,
        "current": False,
    }
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

    reset_count = backend.reset_count
    bridge.handle({"type": "reset"})
    assert backend.reset_count == reset_count + 1

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
    protocol_source = (ROOT / "cli-tui" / "src" / "protocol.js").read_text(
        encoding="utf-8"
    )
    assert "cwd: String(this.config?.workspaceRoot ?? '').trim() || undefined" in protocol_source
    launcher_source = (ROOT / "backend" / "knowflow" / "tui" / "ink_launcher.py").read_text(
        encoding="utf-8"
    )
    assert '"workspaceRoot"' in launcher_source
    assert '"startupAction"' in launcher_source
    assert 'startup_action in {"resume", "continue"}' in launcher_source
    assert 'launch_options["cwd"] = str(workspace_root)' in launcher_source
    assert "INK_CONFIGURE_EXIT_CODE" not in launcher_source
    assert '[sys.executable, "-m", "knowflow.cli", "configure"]' not in launcher_source
    assert "startupAction={String(config.startupAction || '')}" in entry_source
    assert "CONFIGURE_EXIT_CODE" not in entry_source
    assert "localMode={config.mode !== 'remote'}" in entry_source
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
    assert "startedAt={runStartedAtRef.current}" in app_source
    assert "runProjection={runProjection}" in app_source
    assert "state={runHeader}" in app_source
    assert "runtime_handshake" in app_source
    assert "agentEventSchemaVersion" in app_source
    assert "cli_update_completed" in app_source
    assert "client.send({type: 'cli_update'})" in app_source
    assert "输入/configure可在当前TUI内重新配置模型" in app_source
    assert "requestLocalConfiguration" in app_source
    assert "<LocalModelConfigPanel" in app_source

    shutil.rmtree(history_root, ignore_errors=True)
    print("Ink TUI bridge, bundle, and runtime protocol checks passed")


if __name__ == "__main__":
    main()
