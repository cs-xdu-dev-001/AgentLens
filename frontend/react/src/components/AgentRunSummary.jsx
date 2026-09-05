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

export function AgentRunSummary({ messageId = "", trace = [], run = null }) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const [now, setNow] = useState(() => Date.now());
  const [cancelActionState, setCancelActionState] = useState("");
  const presentation = useMemo(
    () => buildAgentRunPresentation({ run, trace: safeTrace, now }),
    [now, run, safeTrace],
  );
  const running = Boolean(presentation?.active);
  const presentationRunId = String(presentation?.runId || run?.id || "");

  useEffect(() => {
    if (!running) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, run?.modelRetry?.retryAt]);

  useEffect(() => {
    setCancelActionState("");
  }, [presentationRunId]);

  useEffect(() => {
    if (!running) setCancelActionState("");
  }, [running]);

  useEffect(() => {
    const handleActionState = (event) => {
      const detail = event.detail || {};
      if (
        detail.action !== "cancel"
        || String(detail.runId || "") !== presentationRunId
        || (messageId && String(detail.messageId || "") !== String(messageId))
      ) return;
      setCancelActionState(detail.status === "failed" ? "" : String(detail.status || ""));
    };
    window.addEventListener("knowflow:react-agent-run-action-state", handleActionState);
    return () => window.removeEventListener("knowflow:react-agent-run-action-state", handleActionState);
  }, [messageId, presentationRunId]);

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
    headline,
    metrics,
    processSummary,
    progressPercent,
    runId,
    status,
    total,
  } = presentation;
  const stopping = status.className === "stopping"
    || (running && ["pending", "succeeded"].includes(cancelActionState));
  const visibleStatus = stopping
    ? { className: "stopping", freshness: "实时", label: "正在停止" }
    : status;
  const visibleProcessSummary = stopping
    ? "正在安全停止当前操作"
    : processSummary;
  const canCancel = Boolean(running && !stopping && messageId && runId);

  const requestCancellation = () => {
    setCancelActionState("pending");
    window.dispatchEvent(
      new CustomEvent("knowflow:react-agent-run-action", {
        detail: {
          action: "cancel",
          messageId,
          runId,
        },
      }),
    );
  };

  return (
    <section
      className={`agent-run-summary${stopping ? " stopping" : ""}`}
      aria-busy={running}
      aria-label={"本次运行概览"}
    >
      <div className={"agent-run-summary-head"}>
        <div className={"agent-run-summary-copy"}>
          <h2 title={headline}>{headline}</h2>
          <div className={"agent-run-summary-meta"}>
            <strong>{metrics || `${completed}/${total}`}</strong>
            <span
              className={"agent-run-summary-freshness"}
              title={runId ? `运行标识：${shortRunId(runId)}` : undefined}
            >
              {visibleStatus.freshness}
            </span>
          </div>
          <p>{visibleProcessSummary}</p>
        </div>
        <div className={"agent-run-summary-actions"}>
          <strong
            className={`agent-run-status ${visibleStatus.className}`}
            key={`${visibleStatus.className}:${visibleStatus.label}`}
          >
            {visibleStatus.label}
          </strong>
          {canCancel ? (
            <button
              className={"agent-run-stop"}
              type={"button"}
              aria-label={"停止任务"}
              onClick={requestCancellation}
            >
              <svg viewBox={"0 0 16 16"} aria-hidden={"true"} focusable={"false"}>
                <rect x={"4"} y={"4"} width={"8"} height={"8"} rx={"1.5"} fill={"currentColor"} />
              </svg>
              <span>{"停止"}</span>
            </button>
          ) : null}
        </div>
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
    </section>
  );
}
