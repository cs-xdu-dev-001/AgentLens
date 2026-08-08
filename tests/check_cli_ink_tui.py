from __future__ import annotations

from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_execution import AgentExecution  # noqa: E402
from knowflow.tui.ink_bridge import PROTOCOL_VERSION, InkRuntimeBridge  # noqa: E402


class FakeBackend:
    model_label = "deepseek-chat"

    def __init__(self) -> None:
        self.cancelled = False
        self.reset_count = 0

    def command_catalog(self):
        return [
            {
                "value": "/tool:read-file",
                "description": "读取文件",
                "source": "tool",
            }
        ]

    def run(self, question, event_sink):
        event_sink({"type": "text_delta", "text": "回答"})
        return AgentExecution(
            result={"paused": False, "runId": "run-ink", "answer": "回答"}
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


class ApprovalBackend(FakeBackend):
    def __init__(self) -> None:
        super().__init__()
        self.decisions: list[str] = []

    def run(self, question, event_sink):
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


def wait_for(output: StringIO, event_type: str) -> list[dict]:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        if any(row.get("type") == event_type for row in rows):
            return rows
        time.sleep(0.01)
    raise AssertionError(f"missing bridge event: {event_type}\n{output.getvalue()}")


def main() -> None:
    output = StringIO()
    backend = FakeBackend()
    bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(),
        output_stream=output,
    )
    bridge.handle({"type": "submit", "requestId": "turn-1", "text": "你好"})
    rows = wait_for(output, "turn_completed")
    assert any(
        row.get("type") == "agent_event"
        and row.get("event", {}).get("type") == "text_delta"
        for row in rows
    )
    assert any(row.get("answer") == "回答" for row in rows)

    ready_output = StringIO()
    ready_bridge = InkRuntimeBridge(
        backend,
        input_stream=StringIO(""),
        output_stream=ready_output,
    )
    ready_bridge.run()
    ready = json.loads(ready_output.getvalue().splitlines()[0])
    assert ready["protocolVersion"] == PROTOCOL_VERSION

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
    assert "R重试本轮  F让Agent分析错误并继续" in app_source
    assert "transcriptSnapshot" in app_source
    assert "对话记录" in app_source

    print("Ink TUI bridge, bundle, and runtime protocol checks passed")


if __name__ == "__main__":
    main()
