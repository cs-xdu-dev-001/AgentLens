import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Virtuoso } from "react-virtuoso";
import { mergeMemoryActivityTrace } from "../controller/memoryActivity.js";
import { AgentApprovalPrompt } from "./AgentApprovalPrompt.jsx";
import { AgentRunSummary } from "./AgentRunSummary.jsx";
import { AgentRecoveryPanel } from "./AgentRecoveryPanel.jsx";
import { AgentTraceView } from "./AgentTraceView.jsx";
import { AgentTaskPlan } from "./AgentTaskPlan.jsx";
import { AgentArtifactList } from "./AgentArtifactList.jsx";
import {
  agentWorkbenchDefaultTab,
  buildAgentToolOutputPresentation,
} from "./agentRunPresentation.js";
import { evidenceReferenceLabel } from "./agentEvidencePresentation.js";

const toolLabels = {
  activate_skill: "启用Skill",
  list_workspace: "查看工作区",
  read_workspace_file: "读取文件",
  run_sandbox_command: "运行命令",
  tool_search: "查找工具",
  web_fetch: "读取网页",
  write_workspace_file: "更新文件",
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

const workbenchTabs = ["trace", "output", "evidence", "artifacts"];
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

function QualityMetric({ label, value }) {
  return (
    <span className={"quality-metric"}>
      <strong>{value}</strong>
      <small>{label}</small>
    </span>
  );
}

function formatOutputSize(lines, bytes) {
  const parts = [];
  if (lines) parts.push(`${lines}行`);
  if (bytes) parts.push(bytes >= 1024 ? `${(bytes / 1024).toFixed(1)}KB` : `${bytes}B`);
  return parts.join(" · ");
}

function toolOutputItemKey(_index, item) {
  return item.id;
}

function ToolOutputPanel({ focusStepId = "", toolCalls = [] }) {
  const presentations = useMemo(
    () => toolCalls.map(buildAgentToolOutputPresentation),
    [toolCalls],
  );
  const initialId = presentations.some((item) => item.id === focusStepId)
    ? focusStepId
    : presentations.at(-1)?.id || "";
  const [selectedId, setSelectedId] = useState(initialId);
  const [autoFollow, setAutoFollow] = useState(true);
  const [copyState, setCopyState] = useState("idle");
  const scrollRef = useRef(null);
  const toolListRef = useRef(null);
  const virtuosoRef = useRef(null);
  const focusFrameRef = useRef(null);
  const copyTimerRef = useRef(null);
  const selectedIndex = presentations.findIndex((item) => item.id === selectedId);
  const activeIndex = selectedIndex >= 0 ? selectedIndex : presentations.length - 1;
  const selected = activeIndex >= 0 ? presentations[activeIndex] : null;

  useEffect(() => {
    if (!presentations.length) {
      setSelectedId("");
      return;
    }
    if (!presentations.some((item) => item.id === selectedId)) {
      setSelectedId(initialId);
    }
  }, [initialId, presentations.length, selectedId]);

  useEffect(() => {
    if (!autoFollow || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [autoFollow, selected?.copyText]);

  useEffect(() => () => {
    if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
    if (focusFrameRef.current) window.cancelAnimationFrame(focusFrameRef.current);
  }, []);

  const setToolListScroller = useCallback((node) => {
    toolListRef.current = node;
  }, []);

  const queueToolFocus = useCallback((toolId) => {
    if (focusFrameRef.current) window.cancelAnimationFrame(focusFrameRef.current);
    let attempts = 0;
    const focusRenderedTool = () => {
      focusFrameRef.current = null;
      const tool = Array.from(
        toolListRef.current?.querySelectorAll('[data-workbench-item="tool"]') || [],
      ).find((item) => item.getAttribute("data-workbench-item-id") === toolId);
      if (tool) {
        tool.focus();
        return;
      }
      attempts += 1;
      if (attempts < 6) {
        focusFrameRef.current = window.requestAnimationFrame(focusRenderedTool);
      }
    };
    focusFrameRef.current = window.requestAnimationFrame(focusRenderedTool);
  }, []);

  const handleToolKeyDown = useCallback((event, currentIndex) => {
    if (!["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    event.stopPropagation();
    const nextIndex = nextWorkbenchItemIndex(
      presentations.length,
      currentIndex,
      event.key,
    );
    const nextTool = presentations[nextIndex];
    if (!nextTool) return;
    setSelectedId(nextTool.id);
    virtuosoRef.current?.scrollToIndex({
      index: nextIndex,
      align: nextIndex === 0
        ? "start"
        : nextIndex === presentations.length - 1
          ? "end"
          : "center",
      behavior: "auto",
    });
    queueToolFocus(nextTool.id);
  }, [presentations, queueToolFocus]);

  const copyOutput = async () => {
    if (!selected?.copyText) return;
    try {
      await navigator.clipboard.writeText(selected.copyText);
      if (copyTimerRef.current) window.clearTimeout(copyTimerRef.current);
      setCopyState("copied");
      copyTimerRef.current = window.setTimeout(() => {
        copyTimerRef.current = null;
        setCopyState("idle");
      }, 1_600);
    } catch {
      setCopyState("error");
    }
  };

  return (
    <section className={"agent-tool-output"} aria-label={"工具输出"}>
      {presentations.length ? (
        <>
          <Virtuoso
            ref={virtuosoRef}
            className={"agent-tool-output-list"}
            id={"tool-timeline-mini"}
            data={presentations}
            data-tool-count={presentations.length}
            aria-label={"执行记录"}
            role={"group"}
            scrollerRef={setToolListScroller}
            computeItemKey={toolOutputItemKey}
            defaultItemHeight={50}
            initialItemCount={Math.min(presentations.length, 8)}
            initialTopMostItemIndex={Math.max(0, activeIndex)}
            increaseViewportBy={{ top: 100, bottom: 100 }}
            minOverscanItemCount={2}
            skipAnimationFrameInResizeObserver={true}
            style={{ height: `${Math.min(174, Math.max(52, presentations.length * 50 + 4))}px` }}
            itemContent={(index, item) => {
              const active = item.id === selected?.id;
              const meta = [
                item.latencyMs != null ? `${item.latencyMs}ms` : "",
                formatOutputSize(item.totalLines, item.totalBytes),
              ].filter(Boolean).join(" · ");
              return (
                <button
                  className={`agent-tool-output-call ${active ? "is-active" : ""}`}
                  data-workbench-item={"tool"}
                  data-workbench-item-id={item.id}
                  key={item.id}
                  type={"button"}
                  tabIndex={active ? 0 : -1}
                  aria-pressed={active}
                  aria-posinset={index + 1}
                  aria-setsize={presentations.length}
                  onClick={() => setSelectedId(item.id)}
                  onKeyDown={(event) => handleToolKeyDown(event, index)}
                >
                  <span className={`agent-tool-output-status ${item.statusTone}`} aria-hidden={"true"}></span>
                  <span className={"agent-tool-output-call-copy"}>
                    <strong>{toolLabels[item.name] || item.name}</strong>
                    <small>{item.statusLabel}{meta ? ` · ${meta}` : ""}</small>
                  </span>
                  <span className={"agent-tool-output-chevron"} aria-hidden={"true"}>{"›"}</span>
                </button>
              );
            }}
          />
          <div className={"agent-tool-console"} aria-live={selected?.active ? "polite" : "off"}>
            <div className={"agent-tool-console-header"}>
              <div>
                <strong>{toolLabels[selected?.name] || selected?.name}</strong>
                <span className={`agent-tool-console-state ${selected?.statusTone || "muted"}`}>
                  {selected?.statusLabel}
                </span>
              </div>
              <div className={"agent-tool-console-actions"}>
                <button
                  type={"button"}
                  className={autoFollow ? "is-active" : ""}
                  aria-pressed={autoFollow}
                  onClick={() => setAutoFollow((value) => !value)}
                >
                  {"跟随"}
                </button>
                <button
                  type={"button"}
                  disabled={!selected?.copyText}
                  onClick={copyOutput}
                >
                  {copyState === "copied" ? "已复制" : copyState === "error" ? "复制失败" : "复制"}
                </button>
              </div>
            </div>
            {selected?.command ? (
              <div className={"agent-tool-console-command"}>
                <span aria-hidden={"true"}>{"$"}</span>
                <code>{selected.command}</code>
              </div>
            ) : null}
            <div
              className={"agent-tool-console-scroll"}
              ref={scrollRef}
              onScroll={(event) => {
                const target = event.currentTarget;
                const atEnd = target.scrollHeight - target.scrollTop - target.clientHeight < 24;
                if (!atEnd && autoFollow) setAutoFollow(false);
              }}
              tabIndex={0}
            >
              {selected?.sections.length ? selected.sections.map((section) => (
                <div className={`agent-tool-console-section ${section.tone}`} key={section.key}>
                  <span>{section.label}</span>
                  <pre>{section.text}</pre>
                </div>
              )) : (
                <div className={"agent-tool-console-empty"}>
                  <span>{selected?.active ? "等待输出" : "没有可显示的输出"}</span>
                  {selected?.active ? <i aria-hidden={"true"}></i> : null}
                </div>
              )}
            </div>
            <div className={"agent-tool-console-footer"}>
              <span>{formatOutputSize(selected?.totalLines, selected?.totalBytes) || "0行 · 0B"}</span>
              {selected?.exitCode != null ? <span>{`退出码 ${selected.exitCode}`}</span> : null}
            </div>
          </div>
        </>
      ) : (
        <div className={"agent-tool-output-empty"}>
          <strong>{"还没有工具输出"}</strong>
          <span>{"等待Agent输出。"}</span>
        </div>
      )}
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
  const toolCallsRef = useRef([]);
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
  toolCallsRef.current = toolCalls;

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
    const selectLifecycleTab = (
      nextRun,
      nextReferences = referencesRef.current,
      nextToolCalls = toolCallsRef.current,
    ) => {
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
        toolCalls: nextToolCalls,
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
      const nextToolCalls = Array.isArray(event.detail?.toolCalls)
        ? event.detail.toolCalls
        : [];
      toolCallsRef.current = nextToolCalls;
      setToolCalls(nextToolCalls);
      selectLifecycleTab(runRef.current, referencesRef.current, nextToolCalls);
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
        toolCallsRef.current = [];
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
      const nextToolCalls = Array.isArray(event.detail?.toolCalls)
        ? event.detail.toolCalls
        : [];
      toolCallsRef.current = nextToolCalls;
      setToolCalls(nextToolCalls);
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
      if (["trace", "output", "evidence", "artifacts"].includes(requestedTab)) {
        selectTab(requestedTab, { manual: true });
      } else {
        selectLifecycleTab(nextRun, nextReferences, nextToolCalls);
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
          toolCallsRef.current = [];
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
    const handleAgentArtifactsOpen = (event) => {
      const detail = event.detail || {};
      const artifacts = Array.isArray(runRef.current?.artifacts)
        ? runRef.current.artifacts.filter((artifact) => artifact?.artifactType !== "reference")
        : [];
      detail.handled = artifacts.length > 0;
      if (detail.handled) selectTab("artifacts", { manual: true });
    };
    const handleWorkbenchSelectTab = (event) => {
      const requestedTab = String(event.detail?.activeTab || "");
      if (["trace", "evidence", "artifacts"].includes(requestedTab)) {
        selectTab(requestedTab, { manual: true });
      }
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
    window.addEventListener("knowflow:react-agent-artifacts-open", handleAgentArtifactsOpen);
    window.addEventListener("knowflow:react-workbench-select-tab", handleWorkbenchSelectTab);
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
      window.removeEventListener("knowflow:react-agent-artifacts-open", handleAgentArtifactsOpen);
      window.removeEventListener("knowflow:react-workbench-select-tab", handleWorkbenchSelectTab);
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
      && ["1", "2", "3", "4"].includes(event.key)
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
      data-artifact-count={artifacts.length}
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
          aria-keyshortcuts={"Alt+E 1"}
          aria-selected={activeTab === "trace"}
          aria-controls={"agent-trace-panel"}
          tabIndex={activeTab === "trace" ? 0 : -1}
          onClick={() => selectTab("trace", { manual: true })}
        >
          {`过程 ${trace.length}`}
        </button>
        <button
          id={"agent-output-tab"}
          data-workbench-tab={"output"}
          type={"button"}
          role={"tab"}
          aria-keyshortcuts={"2"}
          aria-selected={activeTab === "output"}
          aria-controls={"agent-output-panel"}
          tabIndex={activeTab === "output" ? 0 : -1}
          onClick={() => selectTab("output", { manual: true })}
        >
          {`输出 ${toolCalls.length}`}
        </button>
        <button
          id={"agent-evidence-tab"}
          data-workbench-tab={"evidence"}
          type={"button"}
          role={"tab"}
          aria-keyshortcuts={"3"}
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
          aria-keyshortcuts={"Alt+G 4"}
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
        </div>
      ) : activeTab === "output" ? (
        <div
          className={"drawer-section agent-output-section"}
          id={"agent-output-panel"}
          role={"tabpanel"}
          aria-labelledby={"agent-output-tab"}
          tabIndex={0}
        >
          <ToolOutputPanel focusStepId={focusStepId} toolCalls={toolCalls} />
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
