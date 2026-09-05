import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Virtuoso } from "react-virtuoso";
import { AgentTraceStepDetail } from "./AgentTraceStepDetail.jsx";
import {
  matchesFocusScope,
  nextTraceStepId,
  resolveTreeSelectionId,
} from "./agentTraceNavigation.js";
import {
  displayName,
  safeText,
  traceDurationLabel,
  traceKindLabel,
  traceStatusClass,
  traceStatusLabel,
  traceStepTitle,
} from "./agentTracePresentation.js";


function stepDepth(step, byId) {
  let depth = 0;
  let parent = step.parentId
    ? byId.get(step.parentId)
    : null;
  const visited = new Set();
  while (
    parent
    && !visited.has(parent.stepId)
    && depth < 6
  ) {
    visited.add(parent.stepId);
    depth += 1;
    parent = parent.parentId
      ? byId.get(parent.parentId)
      : null;
  }
  return depth;
}

function preferredStep(rows) {
  return (
    [...rows].reverse().find(
      (step) =>
        step.status === "waiting"
        && step.kind === "approval",
    )
    || [...rows].reverse().find(
      (step) => traceStatusClass(step.status) === "failed",
    )
    || [...rows].reverse().find(
      (step) => step.status === "running",
    )
    || rows[rows.length - 1]
    || null
  );
}

const ACTIVE_TRACE_RUN_STATUSES = new Set([
  "queued",
  "pending",
  "planning",
  "running",
  "waiting",
  "waiting_approval",
  "waiting_input",
  "waiting_start",
]);

export function AgentTraceView({
  trace = [],
  messageId = "",
  run = null,
  focusStepId = "",
  onFocusStepChange = null,
  onExitTree = null,
  onDismiss = null,
  focusScope = "message",
}) {
  const [selectedId, setSelectedId] = useState("");
  const [focusedId, setFocusedId] = useState("");
  const treeRef = useRef(null);
  const virtuosoRef = useRef(null);
  const userSelectedRef = useRef(false);
  const focusedIdRef = useRef(focusedId);
  const preferredIdRef = useRef("");
  const rowsRef = useRef([]);
  const rows = useMemo(() => {
    const safeTrace = Array.isArray(trace) ? trace : [];
    const byId = new Map(
      safeTrace.map((step) => [step.stepId, step]),
    );
    return safeTrace.map((step) => ({
      ...step,
      depth: stepDepth(step, byId),
    }));
  }, [trace]);
  const preferred = useMemo(() => preferredStep(rows), [rows]);
  const preferredId = safeText(preferred?.stepId);
  const requestedId = safeText(focusStepId);
  focusedIdRef.current = focusedId;
  preferredIdRef.current = preferredId;
  rowsRef.current = rows;

  const focusRenderedStep = useCallback((stepId) => {
    const normalizedId = safeText(stepId);
    if (!normalizedId) return;
    let attempts = 0;
    const focus = () => {
      const node = treeRef.current?.querySelector(
        `[data-trace-step-id="${CSS.escape(normalizedId)}"]`,
      );
      if (node) {
        node.focus();
        return;
      }
      attempts += 1;
      if (attempts < 8) window.requestAnimationFrame(focus);
    };
    window.requestAnimationFrame(focus);
  }, []);

  const scrollAndFocusStep = useCallback((stepId) => {
    const normalizedId = safeText(stepId);
    if (!normalizedId) return;
    const index = rowsRef.current.findIndex(
      (step) => safeText(step.stepId) === normalizedId,
    );
    if (index < 0) return;
    virtuosoRef.current?.scrollToIndex?.({
      index,
      align: index === 0
        ? "start"
        : index === rowsRef.current.length - 1
          ? "end"
          : "center",
      behavior: "auto",
    });
    focusRenderedStep(normalizedId);
  }, [focusRenderedStep]);

  useEffect(() => {
    if (!requestedId || !rows.some((step) => step.stepId === requestedId)) return;
    userSelectedRef.current = true;
    setSelectedId(requestedId);
    setFocusedId(requestedId);
  }, [requestedId, rows]);

  useEffect(() => {
    setSelectedId((selected) => {
      const ids = rows.map((step) => step.stepId);
      if (
        userSelectedRef.current
        && selected
        && !ids.includes(selected)
      ) {
        userSelectedRef.current = false;
      }
      return resolveTreeSelectionId(
        ids,
        selected,
        preferredId,
        userSelectedRef.current,
      );
    });
  }, [preferredId, rows]);

  useEffect(() => {
    if (focusedId && rows.some((step) => step.stepId === focusedId)) return;
    setFocusedId(preferredId || safeText(rows[0]?.stepId));
  }, [focusedId, preferredId, rows]);

  useEffect(() => {
    const handleTraceFocus = (event) => {
      if (!matchesFocusScope(event.detail?.scope, focusScope)) return;
      const nextId = focusedIdRef.current
        || preferredIdRef.current
        || safeText(rowsRef.current[0]?.stepId);
      if (!nextId) return;
      focusedIdRef.current = nextId;
      setFocusedId(nextId);
      scrollAndFocusStep(nextId);
    };
    window.addEventListener("knowflow:react-trace-focus", handleTraceFocus);
    return () => window.removeEventListener("knowflow:react-trace-focus", handleTraceFocus);
  }, [focusScope, scrollAndFocusStep]);

  const currentStepId = (
    [...rows].reverse().find(
      (step) =>
        step.status === "waiting"
        && step.kind === "approval",
    )
    || [...rows].reverse().find(
      (step) => step.status === "running",
    )
  )?.stepId;

  const toggleStep = (stepId) => {
    userSelectedRef.current = true;
    setSelectedId((current) =>
      current === stepId ? "" : stepId
    );
  };

  const focusStep = (stepId) => {
    if (!stepId) return;
    focusedIdRef.current = stepId;
    setFocusedId(stepId);
    scrollAndFocusStep(stepId);
  };

  const handleStepKeyDown = (event, step) => {
    const stepId = safeText(step.stepId);
    if (event.key === "Escape") {
      if (selectedId) {
        event.preventDefault();
        event.stopPropagation();
        userSelectedRef.current = true;
        setSelectedId("");
        focusStep(stepId);
      } else if (typeof onDismiss === "function") {
        event.preventDefault();
        event.stopPropagation();
        onDismiss();
      }
      return;
    }
    if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      focusStep(nextTraceStepId(rows.map((row) => row.stepId), stepId, event.key));
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      userSelectedRef.current = true;
      setSelectedId(stepId);
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      if (selectedId === stepId) {
        userSelectedRef.current = true;
        setSelectedId("");
      } else if (step.parentId) {
        focusStep(safeText(step.parentId));
      } else if (typeof onExitTree === "function") {
        onExitTree();
      }
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleStep(stepId);
    }
  };

  if (!rows.length) {
    const runStatus = String(
      run?.runSummary?.status
      || run?.status
      || "",
    ).toLowerCase();
    const activeRun = ACTIVE_TRACE_RUN_STATUSES.has(runStatus);
    return (
      <p className={"empty-state"} aria-live={"polite"}>
        {activeRun
          ? "正在等待Agent事件…"
          : runStatus
            ? "运行已结束，但没有可展示的过程记录。"
            : "本次回答没有Agent运行记录。"}
      </p>
    );
  }

  return (
    <div className={"agent-trace-view"}>
      <div
        ref={treeRef}
        className={"agent-trace-tree"}
        role={"tree"}
        aria-label={"Agent运行步骤"}
      >
        <Virtuoso
          ref={virtuosoRef}
          className={"agent-trace-virtual-list"}
          data={rows}
          data-trace-count={rows.length}
          aria-label={"Agent运行步骤列表"}
          role={"group"}
          computeItemKey={(index, step) => safeText(step.stepId) || String(index)}
          defaultItemHeight={72}
          initialItemCount={Math.min(rows.length, 18)}
          increaseViewportBy={{ top: 320, bottom: 320 }}
          minOverscanItemCount={4}
          skipAnimationFrameInResizeObserver={true}
          style={{
            height: `${Math.min(560, Math.max(128, rows.length * 72))}px`,
          }}
          itemContent={(index, step) => {
            const expanded = selectedId === step.stepId;
            const detailId = `trace-detail-${safeText(step.stepId)}`;
            return (
              <div
                className={[
                  "agent-trace-row",
                  expanded ? "expanded" : "",
                ].filter(Boolean).join(" ")}
                style={{ "--trace-depth": step.depth }}
                role={"none"}
              >
                <button
                  className={[
                    "agent-trace-node",
                    traceStatusClass(step.status),
                    expanded ? "selected" : "",
                  ].filter(Boolean).join(" ")}
                  type={"button"}
                  role={"treeitem"}
                  aria-level={step.depth + 1}
                  aria-selected={focusedId === step.stepId}
                  data-trace-step-id={safeText(step.stepId)}
                  tabIndex={focusedId === step.stepId ? 0 : -1}
                  aria-current={
                    step.stepId === currentStepId
                      ? "step"
                      : undefined
                  }
                  aria-expanded={expanded}
                  aria-controls={detailId}
                  onClick={() => toggleStep(step.stepId)}
                  onFocus={() => {
                    focusedIdRef.current = step.stepId;
                    setFocusedId(step.stepId);
                    onFocusStepChange?.(step.stepId);
                  }}
                  onKeyDown={(event) => handleStepKeyDown(event, step)}
                >
                  <span
                    className={"agent-trace-node-dot"}
                    aria-hidden={"true"}
                  ></span>
                  <span
                    className={[
                      "agent-trace-kind",
                      safeText(step.kind),
                    ].filter(Boolean).join(" ")}
                  >
                    {traceKindLabel(step.kind)}
                  </span>
                  <span className={"agent-trace-node-copy"}>
                    <strong>{traceStepTitle(step)}</strong>
                    <small>
                      {displayName(step)}
                      {" · "}
                      {traceStatusLabel(step.status)}
                    </small>
                  </span>
                  <span className={"agent-trace-node-time"}>
                    {traceDurationLabel(step.durationMs)}
                  </span>
                  <span
                    className={"agent-trace-node-chevron"}
                    aria-hidden={"true"}
                  >
                    {"⌄"}
                  </span>
                </button>
                {expanded ? (
                  <AgentTraceStepDetail
                    id={detailId}
                    step={step}
                    messageId={messageId}
                    run={run}
                  />
                ) : null}
              </div>
            );
          }}
        />
      </div>
    </div>
  );
}

export { traceStepTitle };
