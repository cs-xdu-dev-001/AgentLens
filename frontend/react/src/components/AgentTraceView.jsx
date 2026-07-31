import {
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AgentTraceStepDetail } from "./AgentTraceStepDetail.jsx";
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

export function AgentTraceView({
  trace = [],
  messageId = "",
}) {
  const [selectedId, setSelectedId] = useState("");
  const userSelectedRef = useRef(false);
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

  useEffect(() => {
    if (userSelectedRef.current) {
      if (
        selectedId
        && !rows.some((step) => step.stepId === selectedId)
      ) {
        userSelectedRef.current = false;
        setSelectedId(preferredId);
      }
      return;
    }
    setSelectedId(preferredId);
  }, [preferredId, rows, selectedId]);

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

  if (!rows.length) {
    return (
      <p className={"empty-state"}>
        {"本次回答没有Agent运行记录。"}
      </p>
    );
  }

  return (
    <div className={"agent-trace-view"}>
      <div
        className={"agent-trace-tree"}
        role={"list"}
        aria-label={"Agent运行步骤"}
      >
        {rows.map((step) => {
          const expanded = selectedId === step.stepId;
          const detailId = `trace-detail-${safeText(step.stepId)}`;
          return (
            <div
              className={[
                "agent-trace-row",
                expanded ? "expanded" : "",
              ].filter(Boolean).join(" ")}
              style={{ "--trace-depth": step.depth }}
              role={"listitem"}
              key={step.stepId}
            >
              <button
                className={[
                  "agent-trace-node",
                  traceStatusClass(step.status),
                  expanded ? "selected" : "",
                ].filter(Boolean).join(" ")}
                type={"button"}
                aria-current={
                  step.stepId === currentStepId
                    ? "step"
                    : undefined
                }
                aria-expanded={expanded}
                aria-controls={detailId}
                onClick={() => toggleStep(step.stepId)}
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
                />
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { traceStepTitle };
