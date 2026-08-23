import { useEffect, useMemo, useRef, useState } from "react";
import {
  currentRunStep,
  isActiveRun,
  traceForPlanStep,
} from "../controller/agentRunState.js";
import { AgentTraceView } from "./AgentTraceView.jsx";
import {
  matchesFocusScope,
  nextTraceStepId,
  resolveTreeSelectionId,
} from "./agentTraceNavigation.js";


const statusLabels = {
  cancelled: "已取消",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  pending: "等待",
  planning: "规划中",
  running: "执行中",
  skipped: "已跳过",
  waiting_approval: "等待确认",
  waiting_input: "等待回答",
  waiting_start: "等待开始",
};

function dispatchAction(run, action, messageId) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-agent-run-action", {
      detail: {
        action,
        messageId: messageId || "",
        runId: run.id,
      },
    }),
  );
}

export function AgentTaskPlan({
  messageId = "",
  run = null,
  trace = [],
  compact = false,
  focusStepId = "",
  onFocusStepChange = null,
  focusScope = "message",
}) {
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  const current = currentRunStep(run);
  const [selectedStepId, setSelectedStepId] = useState(
    current?.id || steps[0]?.id || "",
  );
  const [focusedStepId, setFocusedStepId] = useState(
    current?.id || steps[0]?.id || "",
  );
  const planTreeRef = useRef(null);
  const pendingTraceFocusRef = useRef(false);
  const focusedStepIdRef = useRef(focusedStepId);
  const preferredPlanStepIdRef = useRef("");
  const userSelectedRef = useRef(false);
  const runIdRef = useRef(run?.id || "");

  const selectedTrace = useMemo(
    () => traceForPlanStep(trace, selectedStepId),
    [selectedStepId, trace],
  );
  const focusedPlanStepId = useMemo(() => {
    if (!focusStepId) return "";
    return steps.find((step) => (
      traceForPlanStep(trace, step.id).some((item) => item.stepId === focusStepId)
    ))?.id || "";
  }, [focusStepId, steps, trace]);
  const preferredPlanStepId = current?.id
    || focusedPlanStepId
    || selectedStepId
    || steps[0]?.id
    || "";
  const stepIds = steps.map((step) => step.id);
  const stepIdsKey = stepIds.join("\u001f");

  focusedStepIdRef.current = focusedStepId;
  preferredPlanStepIdRef.current = preferredPlanStepId;

  const focusPlanStep = (stepId) => {
    if (!stepId) return;
    focusedStepIdRef.current = stepId;
    setFocusedStepId(stepId);
    window.requestAnimationFrame(() => {
      planTreeRef.current
        ?.querySelector(`[data-plan-step-id="${CSS.escape(stepId)}"]`)
        ?.focus();
    });
  };

  useEffect(() => {
    const nextRunId = run?.id || "";
    if (runIdRef.current !== nextRunId) {
      runIdRef.current = nextRunId;
      userSelectedRef.current = false;
      setSelectedStepId(preferredPlanStepId);
      setFocusedStepId(preferredPlanStepId);
      return;
    }
    if (focusStepId && steps.some((step) => step.id === focusStepId)) {
      userSelectedRef.current = true;
      setSelectedStepId(focusStepId);
    } else if (focusedPlanStepId) {
      userSelectedRef.current = true;
      setSelectedStepId(focusedPlanStepId);
    } else {
      setSelectedStepId((selected) => {
        if (
          userSelectedRef.current
          && selected
          && !stepIds.includes(selected)
        ) {
          userSelectedRef.current = false;
        }
        return resolveTreeSelectionId(
          stepIds,
          selected,
          preferredPlanStepId,
          userSelectedRef.current,
        );
      });
    }
  }, [focusStepId, focusedPlanStepId, preferredPlanStepId, run?.id, stepIdsKey]);

  useEffect(() => {
    if (focusedStepId && steps.some((step) => step.id === focusedStepId)) return;
    setFocusedStepId(preferredPlanStepId);
  }, [focusedStepId, preferredPlanStepId, steps]);

  useEffect(() => {
    if (!pendingTraceFocusRef.current || !selectedTrace.length) return;
    pendingTraceFocusRef.current = false;
    window.requestAnimationFrame(() => {
      window.dispatchEvent(new CustomEvent("knowflow:react-trace-focus", {
        detail: { scope: focusScope },
      }));
    });
  }, [selectedStepId, selectedTrace.length]);

  useEffect(() => {
    const handlePlanFocus = (event) => {
      if (!matchesFocusScope(event.detail?.scope, focusScope)) return;
      const nextId = focusedStepIdRef.current || preferredPlanStepIdRef.current;
      if (!nextId) return;
      focusedStepIdRef.current = nextId;
      setFocusedStepId(nextId);
      window.requestAnimationFrame(() => {
        planTreeRef.current
          ?.querySelector(`[data-plan-step-id="${CSS.escape(nextId)}"]`)
          ?.focus();
      });
    };
    window.addEventListener("knowflow:react-plan-focus", handlePlanFocus);
    return () => window.removeEventListener("knowflow:react-plan-focus", handlePlanFocus);
  }, [focusScope]);

  if (!run?.id || !steps.length) return null;

  const active = isActiveRun(run);
  const handlePlanStepKeyDown = (event, step) => {
    if (event.key === "Escape" && selectedStepId) {
      event.preventDefault();
      event.stopPropagation();
      userSelectedRef.current = true;
      setSelectedStepId("");
      focusPlanStep(step.id);
      return;
    }
    if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      focusPlanStep(nextTraceStepId(
        steps.map((item) => item.id),
        step.id,
        event.key,
      ));
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      const childTrace = traceForPlanStep(trace, step.id);
      userSelectedRef.current = true;
      setSelectedStepId(step.id);
      if (childTrace.length) {
        pendingTraceFocusRef.current = true;
        if (selectedStepId === step.id) {
          window.requestAnimationFrame(() => {
            pendingTraceFocusRef.current = false;
            window.dispatchEvent(new CustomEvent("knowflow:react-trace-focus", {
              detail: { scope: focusScope },
            }));
          });
        }
      }
      return;
    }
    if (event.key === "ArrowLeft") {
      if (selectedStepId !== step.id) return;
      event.preventDefault();
      userSelectedRef.current = true;
      setSelectedStepId("");
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      userSelectedRef.current = true;
      setSelectedStepId((selected) => selected === step.id ? "" : step.id);
    }
  };

  return (
    <section
      className={`agent-task-plan${compact ? " compact" : ""}`}
      aria-label={"任务计划"}
    >
      <ol
        ref={planTreeRef}
        className={"agent-task-steps"}
        role={"tree"}
        aria-label={"任务步骤"}
      >
        {steps.map((step) => {
          const selected = step.id === selectedStepId;
          const isCurrent = step.id === current?.id;
          return (
            <li
              className={`agent-task-step ${step.status}${selected ? " selected" : ""}`}
              key={step.id}
              role={"none"}
            >
              <button
                type={"button"}
                role={"treeitem"}
                aria-level={1}
                aria-selected={focusedStepId === step.id}
                aria-current={isCurrent ? "step" : undefined}
                aria-expanded={selected}
                data-plan-step-id={step.id}
                tabIndex={focusedStepId === step.id ? 0 : -1}
                onClick={() => {
                  userSelectedRef.current = true;
                  setFocusedStepId(step.id);
                  setSelectedStepId(selected ? "" : step.id);
                }}
                onFocus={() => {
                  focusedStepIdRef.current = step.id;
                  setFocusedStepId(step.id);
                  onFocusStepChange?.(step.id);
                }}
                onKeyDown={(event) => handlePlanStepKeyDown(event, step)}
              >
                <span
                  className={"agent-task-step-marker"}
                  aria-hidden={"true"}
                ></span>
                <span className={"agent-task-step-title"}>
                  {step.title}
                </span>
                <span className={"agent-task-step-status"}>
                  {statusLabels[step.status] || step.status}
                </span>
              </button>
              {selected ? (
                <div className={"agent-task-step-trace"}>
                  {selectedTrace.length ? (
                    <AgentTraceView
                      messageId={messageId}
                      run={run}
                      trace={selectedTrace}
                      focusStepId={focusStepId}
                      onFocusStepChange={onFocusStepChange}
                      focusScope={focusScope}
                      onExitTree={() => focusPlanStep(step.id)}
                      onDismiss={() => {
                        userSelectedRef.current = true;
                        setSelectedStepId("");
                        focusPlanStep(step.id);
                      }}
                    />
                  ) : (
                    <p className={"agent-task-step-empty"} role={"status"}>
                      {"暂无执行记录"}
                    </p>
                  )}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
      <div className={"agent-task-actions"}>
        {run.status === "waiting_start" ? (
          <>
            <button
              type={"button"}
              className={"primary"}
              onClick={() => dispatchAction(run, "start", messageId)}
            >
              {"开始执行"}
            </button>
            <button
              type={"button"}
              onClick={() => dispatchAction(run, "replan", messageId)}
            >
              {"重新规划"}
            </button>
          </>
        ) : null}
        {active ? (
          <button
            type={"button"}
            onClick={() => dispatchAction(run, "cancel", messageId)}
          >
            {"停止任务"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
