import { useEffect, useMemo, useState } from "react";
import {
  hasPendingBackgroundStep,
  runProgress,
} from "../controller/agentRunState.js";

const terminalStatuses = new Set(["success", "failed", "cancelled"]);

function formatDuration(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(2)}s`;
}

function shortRunId(runId) {
  const value = String(runId || "");
  if (!value) return "尚未开始";
  const suffix = value.startsWith("run_")
    ? value.slice(4, 8)
    : value.slice(0, 8);
  return `run_${suffix.toUpperCase()}`;
}

export function AgentRunSummary({ trace = [], run = null }) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const rootStep = (
    safeTrace.find((step) => step.name === "agent_run")
    || safeTrace[0]
  );
  const durableStatus = run?.status || "";
  const running = durableStatus
    ? ["planning", "running"].includes(durableStatus)
    : rootStep?.status === "running";
  const failed = durableStatus
    ? durableStatus === "failed"
    : rootStep?.status === "failed";
  const cancelled = durableStatus
    ? durableStatus === "cancelled"
    : rootStep?.status === "cancelled";
  const approvalWaiting = safeTrace.some(
    (step) =>
      step.status === "waiting" &&
      step.kind === "approval",
  ) || durableStatus === "waiting_approval";
  const backgroundPending = hasPendingBackgroundStep(safeTrace);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [running]);

  const metrics = useMemo(() => {
    const startedAt = Date.parse(
      run?.startedAt || rootStep?.startedAt || "",
    );
    const finishedAt = Date.parse(run?.finishedAt || "");
    const elapsedMs = rootStep?.durationMs != null
      ? rootStep.durationMs
      : Number.isFinite(finishedAt) && Number.isFinite(startedAt)
        ? finishedAt - startedAt
      : Number.isFinite(startedAt)
        ? now - startedAt
        : 0;
    const progress = runProgress(run);
    return {
      completed: progress.total
        ? progress.completed
        : safeTrace.filter((step) =>
          terminalStatuses.has(step.status),
        ).length,
      elapsed: formatDuration(elapsedMs),
      runId: shortRunId(run?.id || rootStep?.runId),
      toolCalls: safeTrace.filter(
        (step) =>
          step.kind === "tool" || step.kind === "mcp",
      ).length,
      total: progress.total || safeTrace.length,
    };
  }, [now, rootStep, run, safeTrace]);

  const status = durableStatus || (!safeTrace.length
    ? "waiting"
    : approvalWaiting
      ? "waiting"
      : running
      ? "running"
      : failed
        ? "failed"
        : cancelled
          ? "cancelled"
          : "success");
  const statusLabel = durableStatus === "completed" && backgroundPending
    ? "回答已完成"
    : ({
        cancelled: "已取消",
        completed: "已完成",
        failed: "失败",
        interrupted: "已中断",
        planning: "规划中",
        running: "执行中",
        success: "已完成",
        waiting: approvalWaiting ? "等待确认" : "等待运行",
        waiting_approval: "等待确认",
        waiting_start: "等待开始",
      }[status]);
  const freshness = backgroundPending
    ? "后台处理中"
    : running
      ? approvalWaiting
        ? "等待确认"
        : "实时"
      : ["waiting", "waiting_start", "waiting_approval"].includes(status)
        ? "等待"
        : "已保存";

  return (
    <section className={"agent-run-summary"} aria-label={"本次运行概览"}>
      <div className={"agent-run-summary-head"}>
        <div>
          <h2>{"本次运行"}</h2>
          <span>{metrics.runId}{" · "}{freshness}</span>
        </div>
        <strong className={`agent-run-status ${status}`}>
          {statusLabel}
        </strong>
      </div>
      <div className={"agent-run-metrics"}>
        <div>
          <span>{"当前进度"}</span>
          <strong>{metrics.completed}{" / "}{metrics.total}</strong>
        </div>
        <div>
          <span>{"已用时间"}</span>
          <strong>{metrics.elapsed}</strong>
        </div>
        <div>
          <span>{"工具调用"}</span>
          <strong>{metrics.toolCalls}{"次"}</strong>
        </div>
      </div>
    </section>
  );
}
