import { useEffect, useMemo, useRef, useState } from "react";
import { AgentRecoveryPanel } from "./AgentRecoveryPanel.jsx";
import { evidenceReferences } from "./agentEvidencePresentation.js";
import { nextTraceStepId } from "./agentTraceNavigation.js";
import {
  buildAgentRunPresentation,
  buildAgentVerificationPresentation,
  shouldAutoExpandAgentTrace,
  verificationTraceStepId,
} from "./agentRunPresentation.js";

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
  const verifications = useMemo(
    () => buildAgentVerificationPresentation(safeTrace, run?.verifications),
    [run?.verifications, safeTrace],
  );
  const references = useMemo(() => evidenceReferences(run), [run]);
  const active = Boolean(presentation?.active);
  const status = presentation?.status || { className: "waiting", label: "等待开始" };
  const [expanded, setExpanded] = useState(active);
  const [focusedStepId, setFocusedStepId] = useState("");
  const capsuleRef = useRef(null);
  const navigationIds = Array.isArray(presentation?.rows)
    ? presentation.rows.slice(0, 5).map((item) => String(item.id || "")).filter(Boolean)
    : [];
  const navigationKey = navigationIds.join("\u001f");
  const scopedRunId = String(presentation?.runId || run?.id || run?.runId || "");

  useEffect(() => {
    setExpanded(shouldAutoExpandAgentTrace(active, status.className));
  }, [active, run?.id, status.className]);

  useEffect(() => {
    if (!active) return undefined;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, run?.modelRetry?.retryAt]);

  useEffect(() => {
    setFocusedStepId((current) => {
      if (navigationIds.includes(current)) return current;
      const preferred = String(presentation?.activeRow?.id || "");
      return navigationIds.includes(preferred) ? preferred : navigationIds[0] || "";
    });
  }, [navigationKey, presentation?.activeRow?.id, scopedRunId]);

  useEffect(() => {
    const handleFocusUpdated = (event) => {
      const eventMessageId = String(event.detail?.messageId || "");
      const eventRunId = String(event.detail?.runId || "");
      if (
        (eventMessageId && String(messageId || "") !== eventMessageId)
        || (eventRunId && scopedRunId && eventRunId !== scopedRunId)
      ) return;
      const nextStepId = String(event.detail?.focusStepId || "");
      if (navigationIds.includes(nextStepId)) setFocusedStepId(nextStepId);
    };
    window.addEventListener("knowflow:react-agent-focus-updated", handleFocusUpdated);
    return () => window.removeEventListener("knowflow:react-agent-focus-updated", handleFocusUpdated);
  }, [messageId, navigationKey, scopedRunId]);

  if (!presentation) return null;
  const {
    activeRow,
    artifacts,
    completed: progressCompleted,
    context,
    headline,
    metrics,
    processSummary,
    progressPercent,
    rows,
    total: progressTotal,
  } = presentation;
  const settled = status.className === "success" && !expanded;
  const failedVerification = verifications.find((item) => item.status === "failed");
  const passedVerificationCount = verifications.filter((item) => item.status === "passed").length;

  const handleOpen = (activeTab = "trace", focusStepId = "") => {
    if (focusStepId) setFocusedStepId(String(focusStepId));
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: { messageId, trace: safeTrace, approvals, toolCalls, run, activeTab, focusStepId },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
  };

  const focusNavigationRow = (stepId) => {
    if (!stepId) return;
    setFocusedStepId(stepId);
    window.requestAnimationFrame(() => {
      capsuleRef.current
        ?.querySelector(`[data-capsule-step-id="${CSS.escape(stepId)}"]`)
        ?.focus();
    });
  };

  const handleNavigationKeyDown = (event, stepId) => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    focusNavigationRow(nextTraceStepId(navigationIds, stepId, event.key));
  };

  return (
    <section
      ref={capsuleRef}
      className={`agent-task-capsule ${status.className}${expanded ? " expanded" : ""}${settled ? " settled" : ""}`}
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
          <svg
            className={"agent-task-capsule-chevron"}
            viewBox={"0 0 20 20"}
            aria-hidden={"true"}
            focusable={"false"}
          >
            {settled ? (
              <path d={"M4.5 10.3 8.2 14l7.3-8"} />
            ) : (
              <path d={"m6 8 4 4 4-4"} />
            )}
          </svg>
          <span className={"agent-task-capsule-title"}>
            <strong>{headline}</strong>
            {!settled ? <span className={"agent-task-capsule-summary"}>{processSummary}</span> : null}
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
            <strong>{"运行时间线"}</strong>
            <span>{`${progressCompleted}/${progressTotal || rows.length}完成`}</span>
          </div>
          <ol className={"agent-task-capsule-steps"}>
            {rows.slice(0, 5).map((item) => {
              const itemId = String(item.id || "");
              return (
              <li
                className={`${item.status}${itemId === String(activeRow?.id || "") && active ? " current" : ""}${focusedStepId === itemId ? " selected" : ""}`}
                key={itemId}
              >
                <button
                  className={"agent-task-capsule-step-button"}
                  type={"button"}
                  onClick={() => handleOpen("trace", itemId)}
                  onFocus={() => setFocusedStepId(itemId)}
                  onKeyDown={(event) => handleNavigationKeyDown(event, itemId)}
                  aria-label={`查看步骤：${item.title}`}
                  aria-current={itemId === String(activeRow?.id || "") && active ? "step" : undefined}
                  data-capsule-step-id={itemId}
                  tabIndex={expanded && focusedStepId === itemId ? 0 : -1}
                >
                  <span className={"agent-task-capsule-step-icon"} aria-hidden={"true"}></span>
                  <span className={"agent-task-capsule-step-copy"}>
                    <strong>{item.title}</strong>
                    <small>{item.meta}</small>
                  </span>
                  <span className={"agent-task-capsule-step-open"} aria-hidden={"true"}>↗</span>
                </button>
              </li>
              );
            })}
          </ol>
          {rows.length > 5 ? (
            <span className={"agent-task-capsule-more"}>{`另有${rows.length - 5}个步骤`}</span>
          ) : null}
          {context && (context.trimmed || context.percent >= 70) ? (
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
          {artifacts.length || verifications.length || references.length ? (
            <div className={"agent-task-capsule-outcomes"} aria-label={"运行结果"}>
              <strong>{"结果"}</strong>
              <div>
                {artifacts.length ? (
                  <button type={"button"} onClick={() => handleOpen("artifacts")}>
                    <span>{"变更"}</span>
                    <b>{`${artifacts.length}项`}</b>
                  </button>
                ) : null}
                {verifications.length ? (
                  <button
                    className={failedVerification ? "failed" : "passed"}
                    type={"button"}
                    onClick={() => handleOpen(
                      "trace",
                      verificationTraceStepId(failedVerification || verifications.at(-1), safeTrace),
                    )}
                  >
                    <span>{"验证"}</span>
                    <b>{`${passedVerificationCount}/${verifications.length}通过`}</b>
                  </button>
                ) : null}
                {references.length ? (
                  <button type={"button"} onClick={() => handleOpen("evidence")}>
                    <span>{"来源"}</span>
                    <b>{`${references.length}个`}</b>
                  </button>
                ) : null}
              </div>
            </div>
          ) : null}
          <AgentRecoveryPanel
            compact
            interactive={!interactionPending}
            messageId={messageId}
            presentation={presentation}
            run={run}
            trace={safeTrace}
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
