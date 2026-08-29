import { useCallback, useEffect, useRef, useState } from "react";
import { mergeMemoryActivityTrace } from "../controller/memoryActivity.js";
import { AgentApprovalPrompt } from "./AgentApprovalPrompt.jsx";
import { AgentRunSummary } from "./AgentRunSummary.jsx";
import { AgentRecoveryPanel } from "./AgentRecoveryPanel.jsx";
import { AgentTraceView } from "./AgentTraceView.jsx";
import { AgentTaskPlan } from "./AgentTaskPlan.jsx";
import { AgentArtifactList } from "./AgentArtifactList.jsx";
import { agentWorkbenchDefaultTab } from "./agentRunPresentation.js";
import { evidenceReferenceLabel } from "./agentEvidencePresentation.js";

const toolLabels = {
  knowledge_search: "知识库检索",
  session_memory_search: "会话记忆",
  web_search: "网络搜索",
  calculator: "计算器",
};

const qualityLabels = {
  strong: "强匹配",
  usable: "可用",
  weak: "偏弱",
  no_match: "无匹配",
};

const workbenchTabs = ["trace", "evidence", "artifacts"];
const workbenchItemSelector = "[data-workbench-item]";

function visibleWorkbenchItems(panel) {
  if (!panel) return [];
  return Array.from(panel.querySelectorAll(workbenchItemSelector)).filter((item) => (
    !item.disabled && item.getAttribute("aria-hidden") !== "true"
  ));
}

export function nextWorkbenchItemIndex(length, currentIndex, key) {
  const size = Math.max(0, Number(length) || 0);
  if (!size) return -1;
  if (key === "Home") return 0;
  if (key === "End") return size - 1;
  if (currentIndex < 0 || currentIndex >= size) return 0;
  if (key === "ArrowUp") return (currentIndex - 1 + size) % size;
  if (key === "ArrowDown") return (currentIndex + 1) % size;
  return currentIndex;
}

function focusWorkbenchItem(panel, key, currentTarget = null) {
  const items = visibleWorkbenchItems(panel);
  if (!items.length) {
    panel?.focus();
    return false;
  }
  const currentIndex = items.findIndex((item) => (
    item === currentTarget || item.contains(currentTarget)
  ));
  const nextIndex = nextWorkbenchItemIndex(items.length, currentIndex, key);
  items.forEach((item, index) => {
    item.tabIndex = index === nextIndex ? 0 : -1;
  });
  items[nextIndex].focus();
  return true;
}

function formatScore(value) {
  const score = Number(value || 0);
  return Number.isFinite(score) ? score.toFixed(3) : "0.000";
}

function safePreview(value, limit = 140) {
  if (value == null || value === "") return "";
  const text = typeof value === "string"
    ? value.trim()
    : JSON.stringify(value, null, 2);
  const normalized = String(text || "").trim();
  if (!normalized) return "";
  return normalized.length > limit
    ? `${normalized.slice(0, limit)}…`
    : normalized;
}

function toolCallStatusLabel(status) {
  const value = String(status || "").trim();
  return ({
    success: "已完成",
    completed: "已完成",
    failed: "失败",
    error: "失败",
    running: "运行中",
    waiting: "等待中",
  }[value] || value || "已记录");
}

function QualityMetric({ label, value }) {
  return (
    <span className={"quality-metric"}>
      <strong>{value}</strong>
      <small>{label}</small>
    </span>
  );
}

function ToolCallTimeline({ focusStepId = "", toolCalls = [] }) {
  if (!toolCalls.length) return null;
  return (
    <section className={"agent-tool-fallback"} aria-label={"工具执行记录"}>
      <div className={"section-label"}>{"工具"}</div>
      <div className={"timeline"} id={"tool-timeline-mini"}>
        {toolCalls.map((call, index) => {
          const identifier = String(call.toolCallId || call.id || `${index}`);
          const name = call.toolName || call.tool_name || call.name || "knowledge_search";
          const input = call.arguments || call.inputJson || call.input_json || "";
          const output = call.output || call.outputText || call.output_text || call.content || "";
          const latency = call.durationMs ?? call.latencyMs ?? call.latency_ms ?? 0;
          const status = call.status || call.normalizedStatus || "";
          const errorMessage = call.errorMessage || call.error_message || call.error?.message || "";
          const inputPreview = safePreview(input);
          const outputPreview = safePreview(output);
          return (
            <details
              className={"timeline-item timeline-item-expandable"}
              key={`${identifier}:${focusStepId === identifier}`}
              defaultOpen={focusStepId === identifier}
              onKeyDown={(event) => {
                if (event.key !== "Escape" || !event.currentTarget.open) return;
                event.preventDefault();
                event.stopPropagation();
                const disclosure = event.currentTarget;
                disclosure.open = false;
                disclosure.querySelector("summary")?.focus();
              }}
            >
              <summary
                className={"timeline-summary"}
                data-workbench-item={"tool"}
                data-workbench-item-id={identifier}
                tabIndex={index === 0 ? 0 : -1}
              >
                <div className={"timeline-dot"}></div>
                <div className={"timeline-summary-copy"}>
                  <h4>{toolLabels[name] || name}</h4>
                  <p>
                    {toolCallStatusLabel(status)}
                    {latency ? ` · ${latency}ms` : ""}
                    {inputPreview ? ` · ${inputPreview}` : ""}
                  </p>
                </div>
                <div className={"timeline-summary-meta"}>
                  {outputPreview ? <span>{outputPreview}</span> : null}
                  <span aria-hidden={"true"}>{"⌄"}</span>
                </div>
              </summary>
              <div className={"timeline-body"}>
                {input ? (
                  <div className={"timeline-body-section"}>
                    <span>{"公开输入"}</span>
                    <pre>{typeof input === "string" ? input : JSON.stringify(input, null, 2)}</pre>
                  </div>
                ) : null}
                {output ? (
                  <div className={"timeline-body-section"}>
                    <span>{"结果摘要"}</span>
                    <pre>{typeof output === "string" ? output : JSON.stringify(output, null, 2)}</pre>
                  </div>
                ) : null}
                {errorMessage ? (
                  <div className={"timeline-body-section"}>
                    <span>{"错误信息"}</span>
                    <p>{String(errorMessage)}</p>
                  </div>
                ) : null}
              </div>
            </details>
          );
        })}
      </div>
    </section>
  );
}

export function ChatEvidenceDrawer() {
  const [activeTab, setActiveTab] = useState("trace");
  const [references, setReferences] = useState([]);
  const [toolCalls, setToolCalls] = useState([]);
  const [ragQuality, setRagQuality] = useState(null);
  const [retrievalRun, setRetrievalRun] = useState(null);
  const [trace, setTrace] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [run, setRun] = useState(null);
  const [messageId, setMessageId] = useState("");
  const [focusStepId, setFocusStepId] = useState("");
  const messageIdRef = useRef("");
  const tabListRef = useRef(null);
  const activeTabRef = useRef("trace");
  const traceRef = useRef([]);
  const runRef = useRef(null);
  const referencesRef = useRef([]);
  const manualTabRef = useRef(false);

  const publishFocusStep = useCallback((stepId) => {
    const nextStepId = String(stepId || "");
    if (!nextStepId) return;
    setFocusStepId((current) => current === nextStepId ? current : nextStepId);
    const currentRun = runRef.current;
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-focus-updated", {
      detail: {
        focusStepId: nextStepId,
        messageId: messageIdRef.current,
        runId: String(currentRun?.id || currentRun?.runId || ""),
      },
    }));
  }, []);

  const selectTab = (nextTab, { manual = false } = {}) => {
    if (manual) manualTabRef.current = true;
    activeTabRef.current = nextTab;
    setActiveTab(nextTab);
  };

  activeTabRef.current = activeTab;
  traceRef.current = trace;

  const handleTabKeyDown = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      window.requestAnimationFrame(() => {
        const panel = tabListRef.current
          ?.parentElement
          ?.querySelector(`#agent-${activeTabRef.current}-panel`);
        focusWorkbenchItem(panel, "Home");
      });
      return;
    }
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const currentIndex = Math.max(0, workbenchTabs.indexOf(activeTab));
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? workbenchTabs.length - 1
        : event.key === "ArrowRight"
          ? (currentIndex + 1) % workbenchTabs.length
          : event.key === "ArrowLeft"
            ? (currentIndex - 1 + workbenchTabs.length) % workbenchTabs.length
            : currentIndex;
    const nextTab = workbenchTabs[nextIndex];
    selectTab(nextTab, { manual: true });
    window.requestAnimationFrame(() => {
      tabListRef.current
        ?.querySelector(`[data-workbench-tab="${nextTab}"]`)
        ?.focus();
    });
  };

  useEffect(() => {
    const handleWorkbenchFocus = () => {
      window.requestAnimationFrame(() => {
        if (activeTabRef.current === "trace") {
          if (Array.isArray(runRef.current?.steps) && runRef.current.steps.length) {
            window.dispatchEvent(new CustomEvent("knowflow:react-plan-focus", {
              detail: { scope: "workbench" },
            }));
            return;
          }
          if (traceRef.current.length) {
            window.dispatchEvent(new CustomEvent("knowflow:react-trace-focus", {
              detail: { scope: "workbench" },
            }));
            return;
          }
        }
        tabListRef.current
          ?.querySelector('[role="tab"][aria-selected="true"]')
          ?.focus();
      });
    };
    const selectLifecycleTab = (nextRun, nextReferences = referencesRef.current) => {
      if (manualTabRef.current) return;
      const runArtifacts = Array.isArray(nextRun?.artifacts)
        ? nextRun.artifacts
        : [];
      const deliveryArtifacts = runArtifacts.filter(
        (artifact) => artifact?.artifactType !== "reference",
      );
      const embeddedReferences = runArtifacts.filter(
        (artifact) => artifact?.artifactType === "reference",
      );
      selectTab(agentWorkbenchDefaultTab({
        run: nextRun,
        artifacts: deliveryArtifacts,
        references: nextReferences.length ? nextReferences : embeddedReferences,
      }));
    };
    const handleReferencesUpdated = (event) => {
      const nextReferences = Array.isArray(event.detail?.references)
        ? event.detail.references
        : [];
      referencesRef.current = nextReferences;
      setReferences(nextReferences);
      selectLifecycleTab(runRef.current, nextReferences);
    };
    const handleToolTimelineUpdated = (event) => {
      const eventMessageId = String(event.detail?.messageId || "");
      if (
        eventMessageId
        && messageIdRef.current
        && eventMessageId !== messageIdRef.current
      ) return;
      setToolCalls(Array.isArray(event.detail?.toolCalls) ? event.detail.toolCalls : []);
    };
    const handleRagQualityUpdated = (event) => {
      setRagQuality(event.detail?.ragQuality || null);
      setRetrievalRun(event.detail?.retrievalRun || null);
    };
    const handleAgentTraceUpdated = (event) => {
      const eventMessageId = String(event.detail?.messageId || "");
      if (
        eventMessageId
        && eventMessageId !== messageIdRef.current
      ) {
        messageIdRef.current = eventMessageId;
        setMessageId(eventMessageId);
        setApprovals([]);
        setToolCalls([]);
        setRun(null);
        runRef.current = null;
        referencesRef.current = [];
        setReferences([]);
        manualTabRef.current = false;
        setFocusStepId("");
      }
      const nextTrace = Array.isArray(event.detail?.trace)
        ? event.detail.trace
        : [];
      setTrace(nextTrace);
      if (eventMessageId && eventMessageId === messageIdRef.current && !runRef.current) {
        selectLifecycleTab(null);
      }
    };
    const handleAgentTraceOpen = (event) => {
      setTrace(
        Array.isArray(event.detail?.trace)
          ? event.detail.trace
          : [],
      );
      setApprovals(
        Array.isArray(event.detail?.approvals)
          ? event.detail.approvals
          : [],
      );
      setToolCalls(
        Array.isArray(event.detail?.toolCalls)
          ? event.detail.toolCalls
          : [],
      );
      const nextRun = event.detail?.run || null;
      runRef.current = nextRun;
      setRun(nextRun);
      const eventReferences = Array.isArray(event.detail?.references)
        ? event.detail.references
        : Array.isArray(nextRun?.artifacts)
          ? nextRun.artifacts.filter((artifact) => artifact?.artifactType === "reference")
          : null;
      const nextReferences = eventReferences || [];
      referencesRef.current = nextReferences;
      setReferences(nextReferences);
      setRagQuality(null);
      setRetrievalRun(null);
      const nextMessageId = String(event.detail?.messageId || "");
      messageIdRef.current = nextMessageId;
      setMessageId(nextMessageId);
      setFocusStepId(String(event.detail?.focusStepId || ""));
      const requestedTab = event.detail?.activeTab;
      manualTabRef.current = false;
      if (["trace", "evidence", "artifacts"].includes(requestedTab)) {
        selectTab(requestedTab, { manual: true });
      } else {
        selectLifecycleTab(nextRun, nextReferences);
      }
    };
    const handleAgentRunUpdated = (event) => {
      const nextRun = event.detail?.run || null;
      const previousRunId = String(runRef.current?.id || runRef.current?.runId || "");
      const nextRunId = String(nextRun?.id || nextRun?.runId || "");
      if (event.detail?.messageId) {
        const nextMessageId = String(event.detail.messageId);
        if (
          messageIdRef.current
          && messageIdRef.current !== nextMessageId
        ) {
          setTrace([]);
          setApprovals([]);
          setToolCalls([]);
          setFocusStepId("");
          referencesRef.current = [];
          setReferences([]);
          manualTabRef.current = false;
        }
        messageIdRef.current = nextMessageId;
        setMessageId(nextMessageId);
      }
      if (previousRunId && nextRunId && previousRunId !== nextRunId) {
        manualTabRef.current = false;
      }
      runRef.current = nextRun;
      setRun(nextRun);
      selectLifecycleTab(nextRun);
    };
    const handleAgentArtifactsUpdated = (event) => {
      const eventMessageId = String(event.detail?.messageId || "");
      const eventRunId = String(event.detail?.runId || "");
      const nextArtifacts = Array.isArray(event.detail?.artifacts)
        ? event.detail.artifacts
        : [];
      const current = runRef.current;
      if (!current) return;
      const currentRunId = String(current.id || current.runId || "");
      if (
        (eventMessageId && eventMessageId !== messageIdRef.current)
        || (eventRunId && currentRunId && eventRunId !== currentRunId)
      ) return;
      const nextRun = { ...current, artifacts: nextArtifacts };
      runRef.current = nextRun;
      setRun(nextRun);
      selectLifecycleTab(nextRun);
    };
    const handleAgentApprovalsUpdated = (event) => {
      setApprovals(
        Array.isArray(event.detail?.approvals)
          ? event.detail.approvals
          : [],
      );
    };
    window.addEventListener("knowflow:react-references-updated", handleReferencesUpdated);
    window.addEventListener("knowflow:react-tool-timeline-updated", handleToolTimelineUpdated);
    window.addEventListener("knowflow:react-rag-quality-updated", handleRagQualityUpdated);
    window.addEventListener("knowflow:react-agent-trace-updated", handleAgentTraceUpdated);
    window.addEventListener("knowflow:react-agent-trace-open", handleAgentTraceOpen);
    window.addEventListener("knowflow:react-agent-approvals-updated", handleAgentApprovalsUpdated);
    window.addEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
    window.addEventListener("knowflow:react-agent-artifacts-updated", handleAgentArtifactsUpdated);
    window.addEventListener("knowflow:react-workbench-focus", handleWorkbenchFocus);
    return () => {
      window.removeEventListener("knowflow:react-references-updated", handleReferencesUpdated);
      window.removeEventListener("knowflow:react-tool-timeline-updated", handleToolTimelineUpdated);
      window.removeEventListener("knowflow:react-rag-quality-updated", handleRagQualityUpdated);
      window.removeEventListener("knowflow:react-agent-trace-updated", handleAgentTraceUpdated);
      window.removeEventListener("knowflow:react-agent-trace-open", handleAgentTraceOpen);
      window.removeEventListener("knowflow:react-agent-approvals-updated", handleAgentApprovalsUpdated);
      window.removeEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
      window.removeEventListener("knowflow:react-agent-artifacts-updated", handleAgentArtifactsUpdated);
      window.removeEventListener("knowflow:react-workbench-focus", handleWorkbenchFocus);
    };
  }, []);

  useEffect(() => {
    const handleMemoryActivityUpdated = (event) => {
      if (
        !messageId
        || event.detail?.messageId !== messageId
      ) {
        return;
      }
      setTrace((current) => mergeMemoryActivityTrace(
        current,
        event.detail?.memoryActivity,
      ));
    };
    window.addEventListener(
      "knowflow:react-memory-activity-updated",
      handleMemoryActivityUpdated,
    );
    return () => window.removeEventListener(
      "knowflow:react-memory-activity-updated",
      handleMemoryActivityUpdated,
    );
  }, [messageId]);

  const handleDrawerClose = () => window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close", {
    detail: { restoreFocus: true },
  }));
  const handleDrawerKeyDown = (event) => {
    if (event.defaultPrevented) return;
    const activeItem = event.target.closest?.(workbenchItemSelector);
    if (
      activeItem
      && ["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)
    ) {
      const panel = event.currentTarget.querySelector(
        `#agent-${activeTabRef.current}-panel`,
      );
      event.preventDefault();
      focusWorkbenchItem(panel, event.key, activeItem);
      return;
    }
    if (
      !event.altKey
      && !event.ctrlKey
      && !event.metaKey
      && !event.shiftKey
      && ["1", "2", "3"].includes(event.key)
    ) {
      const nextTab = workbenchTabs[Number(event.key) - 1];
      event.preventDefault();
      selectTab(nextTab, { manual: true });
      window.requestAnimationFrame(() => {
        tabListRef.current
          ?.querySelector(`[data-workbench-tab="${nextTab}"]`)
          ?.focus();
      });
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      handleDrawerClose();
    }
  };
  const qualityLevel = ragQuality?.qualityLevel || "no_match";
  const scoreBuckets = ragQuality?.scoreBuckets || {};
  const artifacts = Array.isArray(run?.artifacts)
    ? run.artifacts.filter((artifact) => artifact?.artifactType !== "reference")
    : [];
  const traceHasToolRows = trace.some((step) => (
    ["tool", "mcp", "sandbox", "workspace"].includes(step?.kind)
  ));
  const hasWorkbenchContent = Boolean(
    run
    || trace.length
    || toolCalls.length
    || references.length
    || approvals.length,
  );

  return (
    <aside
      className={"evidence-drawer"}
      id={"evidence-drawer"}
      data-has-run={hasWorkbenchContent}
      aria-label={"Agent运行面板"}
      onKeyDown={handleDrawerKeyDown}
    >
      <div
        className={"drawer-header"}
        aria-live={"polite"}
        aria-atomic={"true"}
      >
        <AgentRunSummary messageId={messageId} trace={trace} run={run} />
        <button className={"icon-button"} id={"inspector-close"} type={"button"} title={"收起运行面板"} aria-label={"收起运行面板"} onClick={handleDrawerClose}>
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
          </svg>
        </button>
      </div>
      <div
        ref={tabListRef}
        className={"drawer-tabs"}
        role={"tablist"}
        aria-label={"运行详情"}
        aria-orientation={"horizontal"}
        onKeyDown={handleTabKeyDown}
      >
        <button
          id={"agent-trace-tab"}
          data-workbench-tab={"trace"}
          type={"button"}
          role={"tab"}
          aria-keyshortcuts={"1"}
          aria-selected={activeTab === "trace"}
          aria-controls={"agent-trace-panel"}
          tabIndex={activeTab === "trace" ? 0 : -1}
          onClick={() => selectTab("trace", { manual: true })}
        >
          {`过程 ${trace.length}`}
        </button>
        <button
          id={"agent-evidence-tab"}
          data-workbench-tab={"evidence"}
          type={"button"}
          role={"tab"}
          aria-keyshortcuts={"2"}
          aria-selected={activeTab === "evidence"}
          aria-controls={"agent-evidence-panel"}
          tabIndex={activeTab === "evidence" ? 0 : -1}
          onClick={() => selectTab("evidence", { manual: true })}
        >
          {`引用 ${references.length}`}
        </button>
        <button
          id={"agent-artifacts-tab"}
          data-workbench-tab={"artifacts"}
          type={"button"}
          role={"tab"}
          aria-keyshortcuts={"3"}
          aria-selected={activeTab === "artifacts"}
          aria-controls={"agent-artifacts-panel"}
          tabIndex={activeTab === "artifacts" ? 0 : -1}
          onClick={() => selectTab("artifacts", { manual: true })}
        >
          {`变更 ${artifacts.length}`}
        </button>
      </div>
      {activeTab === "trace" ? (
        <div
          className={"drawer-section agent-trace-section"}
          id={"agent-trace-panel"}
          role={"tabpanel"}
          aria-labelledby={"agent-trace-tab"}
          tabIndex={0}
        >
          <AgentRecoveryPanel
            messageId={messageId}
            run={run}
            trace={trace}
          />
          {approvals.length ? (
            <div className={"agent-approval-drawer-list"}>
              {approvals.map((approval) => (
                <AgentApprovalPrompt
                  approval={approval}
                  compact
                  interactive={false}
                  key={approval.approvalId}
                />
              ))}
            </div>
          ) : null}
          <AgentTaskPlan
            messageId={messageId}
            run={run}
            trace={trace}
            focusStepId={focusStepId}
            onFocusStepChange={publishFocusStep}
            focusScope={"workbench"}
            showCancelAction={false}
          />
          {!run?.steps?.length ? (
            <AgentTraceView
              messageId={messageId}
              run={run}
              trace={trace}
              focusStepId={focusStepId}
              onFocusStepChange={publishFocusStep}
              focusScope={"workbench"}
            />
          ) : null}
          {!traceHasToolRows ? (
            <ToolCallTimeline
              focusStepId={focusStepId}
              toolCalls={toolCalls}
            />
          ) : null}
        </div>
      ) : activeTab === "artifacts" ? (
        <div
          className={"drawer-section"}
          id={"agent-artifacts-panel"}
          role={"tabpanel"}
          aria-labelledby={"agent-artifacts-tab"}
          tabIndex={0}
        >
          <AgentArtifactList
            artifacts={artifacts}
            messageId={messageId}
            runId={run?.id || run?.runId}
            runStatus={run?.status}
            onChange={(nextArtifacts) => setRun((current) => (
              current ? { ...current, artifacts: nextArtifacts } : current
            ))}
          />
        </div>
      ) : (
        <div
          id={"agent-evidence-panel"}
          role={"tabpanel"}
          aria-labelledby={"agent-evidence-tab"}
          tabIndex={0}
        >
          <div className={"drawer-section"}>
            <div className={"section-label"}>{"引用来源"}</div>
            {ragQuality?.enabled ? (
              <div className={"rag-quality-card"} id={"rag-quality-card"}>
                <span className={"quality-level " + qualityLevel}>{qualityLabels[qualityLevel] || qualityLevel}</span>
                <strong>{"可信度"}</strong>
                <p>{ragQuality.reason || "已评估本次引用。"}</p>
                <div className={"quality-metrics"} id={"rag-quality-metrics"}>
                  <QualityMetric label={"命中"} value={ragQuality.hitCount || 0} />
                  <QualityMetric label={"最高分"} value={formatScore(ragQuality.maxScore)} />
                  <QualityMetric label={"平均分"} value={formatScore(ragQuality.avgScore)} />
                  <QualityMetric label={"偏弱"} value={ragQuality.belowThresholdCount || 0} />
                </div>
                <small>
                  {"强 " + (scoreBuckets.strong || 0) + " / 可用 " + (scoreBuckets.usable || 0) + " / 偏弱 " + (scoreBuckets.weak || 0)}
                  {retrievalRun?.id ? "，#" + retrievalRun.id : ""}
                </small>
              </div>
            ) : null}
            <div className={"reference-list"} id={"reference-list"}>
              {references.length ? (
                references.map((reference, index) => {
                  const score = Math.round(Number(reference.score || 0) * 100);
                  return (
                    <article
                      className={"item"}
                      data-workbench-item={"reference"}
                      data-workbench-item-id={String(reference.chunkId || reference.chunk_id || index)}
                      key={reference.chunkId || reference.chunk_id || index}
                      tabIndex={index === 0 ? 0 : -1}
                    >
                      <h3>{evidenceReferenceLabel(reference, index)}</h3>
                      <p><span className={"badge ok"}>{"匹配 " + score + "%"}</span></p>
                      <p>{reference.excerpt || reference.content || reference.chunk_text || ""}</p>
                    </article>
                  );
                })
              ) : (
                <p className={"empty-state"}>{"本次回答没有引用片段。"}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
