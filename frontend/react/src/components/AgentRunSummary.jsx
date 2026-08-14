import { useEffect, useMemo, useState } from "react";
import { buildAgentRunPresentation } from "./agentRunPresentation.js";

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
  const [now, setNow] = useState(() => Date.now());
  const presentation = useMemo(
    () => buildAgentRunPresentation({ run, trace: safeTrace, now }),
    [now, run, safeTrace],
  );
  const running = Boolean(presentation?.active);

  useEffect(() => {
    if (!running) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  if (!presentation) {
    return (
      <section className={"agent-run-summary idle"} aria-label={"运行工作台"}>
        <div className={"agent-run-summary-head"}>
          <div className={"agent-run-summary-copy"}>
            <h2>{"运行工作台"}</h2>
            <span>{"等待任务"}</span>
          </div>
          <strong className={"agent-run-status waiting"}>{"就绪"}</strong>
        </div>
      </section>
    );
  }
  const {
    completed,
    elapsed,
    headline,
    processSummary,
    progressPercent,
    runId,
    status,
    tokenLabel,
    toolCalls,
    total,
  } = presentation;

  return (
    <section className={"agent-run-summary"} aria-label={"本次运行概览"}>
      <div className={"agent-run-summary-head"}>
        <div className={"agent-run-summary-copy"}>
          <h2 title={headline}>{headline}</h2>
          <span>{shortRunId(runId)}{" · "}{status.freshness}</span>
          <p>{processSummary}</p>
        </div>
        <strong className={`agent-run-status ${status.className}`}>
          {status.label}
        </strong>
      </div>
      <div
        className={"agent-run-progress"}
        role={"progressbar"}
        aria-label={"本次运行进度"}
        aria-valuemin={0}
        aria-valuemax={total || 1}
        aria-valuenow={completed}
      >
        <span style={{ transform: `scaleX(${progressPercent / 100})` }}></span>
      </div>
      <div className={"agent-run-metrics"}>
        <div>
          <span>{"当前进度"}</span>
          <strong>{completed}{" / "}{total}</strong>
        </div>
        <div>
          <span>{"已用时间"}</span>
          <strong>{elapsed}</strong>
        </div>
        <div>
          <span>{"工具调用"}</span>
          <strong>{toolCalls}{"次"}</strong>
        </div>
        <div>
          <span>{"Tokens"}</span>
          <strong>{tokenLabel || "—"}</strong>
        </div>
      </div>
    </section>
  );
}
