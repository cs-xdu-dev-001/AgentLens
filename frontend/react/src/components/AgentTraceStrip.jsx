import { useEffect, useMemo, useState } from "react";
import { traceStepTitle } from "./AgentTraceView.jsx";
import {
  currentRunStep,
  runProgress,
  traceStepWaitState,
} from "../controller/agentRunState.js";


const terminalStatuses = new Set([
  "cancelled",
  "completed",
  "failed",
  "skipped",
  "success",
]);

const kindLabels = {
  agent: "Agent",
  approval: "确认",
  memory: "记忆",
  mcp: "MCP",
  model: "模型",
  plan: "计划",
  skill: "Skill",
  tool: "工具",
};

const stepStatusLabels = {
  cancelled: "已取消",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  pending: "等待",
  planning: "规划中",
  running: "运行中",
  skipped: "已跳过",
  success: "已完成",
  waiting: "等待",
  waiting_approval: "等待确认",
  waiting_start: "等待开始",
};

function currentStep(trace) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  return (
    [...safeTrace].reverse().find(
      (step) => step.status === "waiting" && step.kind === "approval",
    )
    || [...safeTrace].reverse().find((step) => step.status === "running")
    || [...safeTrace].reverse().find(Boolean)
    || null
  );
}

function parseSummary(value) {
  if (value && typeof value === "object") return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function estimatedTokens(trace) {
  return trace.reduce((total, step) => {
    if (step.kind !== "model") return total;
    const summary = parseSummary(step.inputSummary);
    return total + Math.max(0, Number(summary.estimatedTokenCount) || 0);
  }, 0);
}

function formatTokens(value) {
  const tokens = Math.max(0, Number(value) || 0);
  if (!tokens) return "";
  if (tokens < 1000) return `~${Math.round(tokens)} tokens`;
  const compact = (tokens / 1000).toFixed(tokens < 10_000 ? 1 : 0);
  return `~${compact.replace(/\.0$/, "")}k tokens`;
}

function formatElapsed(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${Math.round(value / 1000)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.floor((value % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

function runRows(run, trace) {
  const planSteps = Array.isArray(run?.steps) ? run.steps : [];
  if (planSteps.length) {
    return planSteps.map((step) => {
      const relatedTrace = [...trace].reverse().find((item) => (
        item.details?.planStepId === step.id
        || item.planStepId === step.id
      ));
      return {
        durationMs: relatedTrace?.durationMs,
        id: step.id,
        kind: step.kind || relatedTrace?.kind || "plan",
        status: step.status,
        title: step.title,
      };
    });
  }
  return trace
    .filter((step) => step.name !== "agent_run")
    .map((step) => ({
      durationMs: step.durationMs,
      id: step.stepId,
      kind: step.kind,
      status: step.status,
      title: traceStepTitle(step),
    }));
}

function rowMeta(row) {
  const duration = row.durationMs == null
    ? ""
    : formatElapsed(row.durationMs);
  return [
    kindLabels[row.kind] || row.kind || "步骤",
    stepStatusLabels[row.status] || row.status,
    duration,
  ].filter(Boolean).join(" · ");
}

function statusPresentation(run, step, waitState) {
  const status = run?.status || step?.status || "waiting";
  if (waitState.background) {
    return {
      className: "running",
      detail: "后台整理中，不影响继续对话",
      label: "后台整理中",
    };
  }
  if (waitState.approval || status === "waiting_approval") {
    return { className: "waiting", label: "等待确认" };
  }
  if (["failed", "interrupted"].includes(status)) {
    return { className: "failed", label: status === "failed" ? "失败" : "已中断" };
  }
  if (status === "cancelled") return { className: "cancelled", label: "已取消" };
  if (["planning", "running"].includes(status)) {
    return { className: "running", label: status === "planning" ? "规划中" : "执行中" };
  }
  if (["completed", "success"].includes(status)) {
    return { className: "success", label: "已完成" };
  }
  return { className: "waiting", label: "等待开始" };
}

export function AgentTraceStrip({
  messageId,
  trace = [],
  approvals = [],
  run = null,
}) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const durableStep = currentRunStep(run);
  const liveStep = currentStep(safeTrace);
  const liveWaitState = traceStepWaitState(liveStep);
  const step = (
    liveWaitState.approval
    || liveWaitState.background
    || liveStep?.status === "running"
  ) ? liveStep : (durableStep || liveStep);
  const rows = useMemo(() => runRows(run, safeTrace), [run, safeTrace]);
  const waitState = traceStepWaitState(step);
  const status = statusPresentation(run, step, waitState);
  const active = status.className === "running" || status.className === "waiting";
  const [expanded, setExpanded] = useState(active);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setExpanded(active);
  }, [active, run?.id]);

  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!step) return null;

  const rootStep = safeTrace.find((item) => item.name === "agent_run") || safeTrace[0];
  const startedAt = Date.parse(run?.startedAt || rootStep?.startedAt || "");
  const finishedAt = Date.parse(run?.finishedAt || run?.updatedAt || "");
  const elapsedMs = rootStep?.durationMs != null
    ? rootStep.durationMs
    : Number.isFinite(startedAt)
      ? ((active || !Number.isFinite(finishedAt) ? now : finishedAt) - startedAt)
      : safeTrace.reduce((total, item) => total + (Number(item.durationMs) || 0), 0);
  const progress = runProgress(run, rows);
  const completed = rows.filter((item) => terminalStatuses.has(item.status)).length;
  const progressCompleted = progress.total ? progress.completed : completed;
  const progressTotal = progress.total || rows.length;
  const tokenLabel = formatTokens(estimatedTokens(safeTrace));
  const metrics = [
    formatElapsed(elapsedMs),
    tokenLabel,
    progressTotal ? `${progressCompleted}/${progressTotal}` : "",
  ].filter(Boolean).join(" · ");
  const activeRow = (
    [...rows].reverse().find((item) => [
      "running",
      "planning",
      "waiting",
      "waiting_approval",
    ].includes(item.status))
    || [...rows].reverse().find(Boolean)
  );
  const answerRow = [...rows].reverse().find((item) => item.kind === "answer");
  const headline = (
    active
      ? activeRow?.title
      : answerRow?.title || rows.at(-1)?.title
  ) || "本次任务";
  const progressPercent = progressTotal
    ? Math.min(100, Math.round((progressCompleted / progressTotal) * 100))
    : 0;
  const processSummary = active
    ? status.detail || `当前：${headline}`
    : `${progressCompleted}个步骤已结束`;

  const handleOpen = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: { messageId, trace: safeTrace, approvals, run },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open"));
  };

  return (
    <section
      className={`agent-task-capsule ${status.className}${expanded ? " expanded" : ""}`}
      aria-label={"本次运行过程"}
    >
      <div className={"agent-task-capsule-head"}>
        <button
          className={"agent-task-capsule-toggle"}
          type={"button"}
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-label={expanded ? "收起任务过程" : "展开任务过程"}
        >
          <span className={"agent-task-capsule-chevron"} aria-hidden={"true"}>⌄</span>
          <span className={"agent-task-capsule-title"}>
            <strong>{headline}</strong>
            <small>{processSummary}</small>
          </span>
        </button>
        <div className={"agent-task-capsule-meta"}>
          <span className={"agent-task-capsule-metrics"} aria-live={"polite"}>{metrics}</span>
          <span
            className={`agent-task-capsule-status ${status.className}`}
            aria-label={status.detail || status.label}
          >
            {status.label}
          </span>
        </div>
      </div>
      <div
        className={"agent-task-capsule-progress"}
        role={"progressbar"}
        aria-label={"任务进度"}
        aria-valuemin={0}
        aria-valuemax={progressTotal || 1}
        aria-valuenow={progressCompleted}
      >
        <span style={{ transform: `scaleX(${progressPercent / 100})` }}></span>
      </div>
      <div className={"agent-task-capsule-disclosure"} aria-hidden={!expanded}>
        <div className={"agent-task-capsule-body"}>
          <div className={"agent-task-capsule-section-head"}>
            <strong>{"执行过程"}</strong>
            <span>{`${progressCompleted}/${progressTotal || rows.length}完成`}</span>
          </div>
          <ol className={"agent-task-capsule-steps"}>
            {rows.slice(0, 8).map((item) => (
              <li
                className={`${item.status}${item.id === activeRow?.id && active ? " current" : ""}`}
                key={item.id}
              >
                <span className={"agent-task-capsule-step-icon"} aria-hidden={"true"}></span>
                <span className={"agent-task-capsule-step-copy"}>
                  <strong>{item.title}</strong>
                  <small>{rowMeta(item)}</small>
                </span>
              </li>
            ))}
          </ol>
          {rows.length > 8 ? (
            <span className={"agent-task-capsule-more"}>{`另有${rows.length - 8}个步骤`}</span>
          ) : null}
          <button
            className={"agent-task-capsule-detail"}
            type={"button"}
            onClick={handleOpen}
            tabIndex={expanded ? 0 : -1}
          >
            {"查看运行详情"}
            <span aria-hidden={"true"}>↗</span>
          </button>
        </div>
      </div>
    </section>
  );
}
