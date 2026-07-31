from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, token: str, label: str) -> None:
    assert token in read(path), f"Missing {label}: {path} -> {token}"


def main() -> None:
    chat_flow = read("frontend/react/src/controller/chatFlow.js")
    state_module = (
        ROOT
        / "frontend"
        / "react"
        / "src"
        / "controller"
        / "agentRunState.js"
    )
    script = """
import {
  currentRunStep,
  hasPendingBackgroundStep,
  isActiveRun,
  runProgress,
  traceForPlanStep,
} from "./react/src/controller/agentRunState.js";
const run = {
  id: "run_TASK",
  status: "waiting_approval",
  currentStepId: "plan_2",
  steps: [
    { id: "plan_1", status: "completed", title: "搜索资料" },
    { id: "plan_2", status: "waiting_approval", title: "写入 Notion" },
    { id: "plan_3", status: "pending", title: "整理回答" },
  ],
};
const trace = [
  { stepId: "trace_1", parentId: null, details: { planStepId: "plan_1" } },
  { stepId: "trace_2", parentId: "trace_1", kind: "tool" },
  { stepId: "trace_3", parentId: null, details: { planStepId: "plan_2" } },
  { stepId: "trace_4", parentId: "trace_3", kind: "approval" },
];
console.log(JSON.stringify({
  active: isActiveRun(run),
  current: currentRunStep(run),
  progress: runProgress(run),
  traceProgress: runProgress(
    { id: "run_TRACE", status: "running", steps: [] },
    [
      { status: "success" },
      { status: "success" },
      { status: "running" },
    ],
  ),
  pendingBackground: hasPendingBackgroundStep([
    { kind: "memory", status: "success" },
    { kind: "memory", status: "running" },
  ]),
  completedBackground: hasPendingBackgroundStep([
    { kind: "memory", status: "success" },
  ]),
  selectedTrace: traceForPlanStep(trace, "plan_2"),
}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "frontend",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["active"] is True
    assert result["current"]["id"] == "plan_2"
    assert result["progress"] == {
        "completed": 1,
        "total": 3,
    }
    assert result["traceProgress"] == {
        "completed": 2,
        "total": 3,
    }
    assert result["pendingBackground"] is True
    assert result["completedBackground"] is False
    assert [
        item["stepId"] for item in result["selectedTrace"]
    ] == ["trace_3", "trace_4"]

    component = "frontend/react/src/components/AgentTaskPlan.jsx"
    for token, label in (
        ("开始执行", "plan start action"),
        ("重新规划", "plan replan action"),
        ("停止任务", "running cancel action"),
        ("aria-current", "current step accessibility"),
        ("AgentTraceView", "selected step trace"),
        ("暂无执行记录", "empty selected step feedback"),
        ('role={"status"}', "empty step live status"),
    ):
        require(component, token, label)

    require(
        "frontend/react/src/components/AgentRecoveryPanel.jsx",
        "从失败步骤继续",
        "interrupted resume action",
    )

    require(
        "frontend/react/src/api/client.js",
        "agentRunApi",
        "Agent run API client",
    )
    require(
        "frontend/react/src/controller/messageEvents.js",
        "updateReactMessageRun",
        "message run bridge",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "knowflow:react-message-run",
        "message run listener",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "runProgress(run, trace)",
        "trace progress fallback in the compact run strip",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        '"回答已完成"',
        "completed answer status while background work continues",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        '"后台处理中"',
        "background freshness status",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        'eventPayload.type === "run_snapshot"',
        "run snapshot SSE branch",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "agentRunApi.cancel",
        "durable stop action",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "activeRunReconnectController",
        "active run reconnect controller",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "reconnectAgentRun(",
        "active run reconnect",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "message.streaming = false",
        "reconnect completion state",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        'eventPayload.type === "error"',
        "reconnect error event",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        'eventPayload.type === "cancelled"',
        "reconnect cancellation event",
    )
    if chat_flow.count("cancelPendingApprovals();") < 7:
        raise AssertionError(
            "initial and reconnected terminal events must clear pending approvals"
        )
    require(
        "frontend/styles.css",
        ".agent-task-step-empty",
        "empty step styling",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "<AgentTaskPlan",
        "plan-first drawer",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "run = null",
        "durable run summary",
    )
    assert state_module.exists()
    print("frontend durable Agent task plan checks passed")


if __name__ == "__main__":
    main()
