import { useEffect, useMemo, useState } from "react";
import { AgentRecoveryPanel } from "./AgentRecoveryPanel.jsx";
import { buildAgentRunPresentation } from "./agentRunPresentation.js";

function artifactChangeMeta(artifact) {
  const added = Math.max(0, Number(artifact?.addedLines) || 0);
  const removed = Math.max(0, Number(artifact?.removedLines) || 0);
  const bytes = Math.max(0, Number(artifact?.writtenBytes) || 0);
  return [
    added ? `+${added}` : "",
    removed ? `−${removed}` : "",
    bytes ? `${bytes} B` : "",
  ].filter(Boolean).join(" · ");
}

export function AgentTraceStrip({
  interactionPending = false,
  messageId,
  trace = [],
  approvals = [],
  toolCalls = [],
  run = null,
}) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const [now, setNow] = useState(() => Date.now());
  const presentation = useMemo(
    () => buildAgentRunPresentation({ run, trace: safeTrace, now }),
    [now, run, safeTrace],
  );
  const active = Boolean(presentation?.active);
  const status = presentation?.status || { className: "waiting", label: "等待开始" };
  const [expanded, setExpanded] = useState(active);

  useEffect(() => {
    setExpanded(active || status.className === "failed");
  }, [active, run?.id, status.className]);

  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  if (!presentation) return null;
  const {
    activeRow,
    artifacts,
    completed: progressCompleted,
    context,
    hasPlan,
    headline,
    metrics,
    operations,
    processSummary,
    progressPercent,
    rows,
    total: progressTotal,
  } = presentation;

  const handleOpen = (activeTab = "trace", focusStepId = "") => {
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: { messageId, trace: safeTrace, approvals, toolCalls, run, activeTab, focusStepId },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
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
                <button
                  className={"agent-task-capsule-step-button"}
                  type={"button"}
                  onClick={() => handleOpen("trace", item.id)}
                  aria-label={`查看步骤：${item.title}`}
                  tabIndex={expanded ? 0 : -1}
                >
                  <span className={"agent-task-capsule-step-icon"} aria-hidden={"true"}></span>
                  <span className={"agent-task-capsule-step-copy"}>
                    <strong>{item.title}</strong>
                    <small>{item.meta}</small>
                  </span>
                  <span className={"agent-task-capsule-step-open"} aria-hidden={"true"}>↗</span>
                </button>
              </li>
            ))}
          </ol>
          {rows.length > 8 ? (
            <span className={"agent-task-capsule-more"}>{`另有${rows.length - 8}个步骤`}</span>
          ) : null}
          {operations.length && hasPlan ? (
            <div className={"agent-task-capsule-operations"}>
              <div className={"agent-task-capsule-section-head"}>
                <strong>{"操作记录"}</strong>
                <span>{`${operations.length}项`}</span>
              </div>
              <ol className={"agent-task-capsule-steps"}>
                {operations.slice(0, 6).map((item) => (
                  <li
                    className={`${item.status}${active && ["planning", "running", "waiting"].includes(item.status) ? " current" : ""}`}
                    key={`operation-${item.id}`}
                  >
                    <button
                      className={"agent-task-capsule-step-button"}
                      type={"button"}
                      onClick={() => handleOpen("trace", item.id)}
                      aria-label={`查看操作：${item.title}`}
                      tabIndex={expanded ? 0 : -1}
                    >
                      <span className={"agent-task-capsule-step-icon"} aria-hidden={"true"}></span>
                      <span className={"agent-task-capsule-step-copy"}>
                        <strong>{item.title}</strong>
                        {item.meta ? <small>{item.meta}</small> : null}
                      </span>
                      <span className={"agent-task-capsule-step-open"} aria-hidden={"true"}>↗</span>
                    </button>
                  </li>
                ))}
              </ol>
              {operations.length > 6 ? (
                <span className={"agent-task-capsule-more"}>{`另有${operations.length - 6}项操作`}</span>
              ) : null}
            </div>
          ) : null}
          {context ? (
            <div className={`agent-context-pressure${context.trimmed ? " trimmed" : ""}`}>
              <div>
                <strong>{context.label}</strong>
                <span>{context.detail}</span>
              </div>
              <span className={"agent-context-pressure-track"} aria-hidden={"true"}>
                <i style={{ transform: `scaleX(${context.percent / 100})` }}></i>
              </span>
            </div>
          ) : null}
          {active && artifacts.length ? (
            <div className={"agent-task-capsule-artifacts"}>
              <div className={"agent-task-capsule-section-head"}>
                <strong>{`${artifacts.length}个产物`}</strong>
                <span>{"已保存"}</span>
              </div>
              <ul>
                {artifacts.slice(0, 5).map((artifact, index) => {
                  const target = artifact.path || artifact.url || artifact.title || "运行产物";
                  return (
                    <li key={artifact.artifactId || `${target}-${index}`}>
                      <button
                        type={"button"}
                        onClick={() => handleOpen("artifacts")}
                        aria-label={`查看变更：${target}`}
                        tabIndex={expanded ? 0 : -1}
                      >
                        <span aria-hidden={"true"}>◆</span>
                        <strong title={target}>{target}</strong>
                        <small>{artifactChangeMeta(artifact)}</small>
                        <span aria-hidden={"true"}>↗</span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {artifacts.length > 5 ? (
                <span className={"agent-task-capsule-more"}>{`另有${artifacts.length - 5}个产物`}</span>
              ) : null}
            </div>
          ) : null}
          <AgentRecoveryPanel
            compact
            interactive={!interactionPending}
            messageId={messageId}
            run={run}
          />
          <div className={"agent-task-capsule-actions"}>
            <button
              className={"agent-task-capsule-detail"}
              type={"button"}
              onClick={() => handleOpen("trace")}
              tabIndex={expanded ? 0 : -1}
            >
              {"查看完整过程"}
              <span aria-hidden={"true"}>↗</span>
            </button>
            {artifacts.length ? (
              <button
                className={"agent-task-capsule-detail"}
                type={"button"}
                onClick={() => handleOpen("artifacts")}
                tabIndex={expanded ? 0 : -1}
              >
                {"查看变更"}
                <span aria-hidden={"true"}>↗</span>
              </button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
