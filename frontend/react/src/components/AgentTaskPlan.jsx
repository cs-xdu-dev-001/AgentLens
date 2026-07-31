import { useEffect, useMemo, useState } from "react";
import {
  currentRunStep,
  isActiveRun,
  traceForPlanStep,
} from "../controller/agentRunState.js";
import { AgentTraceView } from "./AgentTraceView.jsx";


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
}) {
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  const current = currentRunStep(run);
  const [selectedStepId, setSelectedStepId] = useState(
    current?.id || steps[0]?.id || "",
  );

  useEffect(() => {
    if (
      current?.id
      && ["running", "waiting_approval"].includes(current.status)
    ) {
      setSelectedStepId(current.id);
    }
  }, [current?.id, current?.status]);

  const selectedTrace = useMemo(
    () => traceForPlanStep(trace, selectedStepId),
    [selectedStepId, trace],
  );

  if (!run?.id || !steps.length) return null;

  const active = isActiveRun(run);
  return (
    <section
      className={`agent-task-plan${compact ? " compact" : ""}`}
      aria-label={"任务计划"}
    >
      <ol className={"agent-task-steps"}>
        {steps.map((step) => {
          const selected = step.id === selectedStepId;
          const isCurrent = step.id === current?.id;
          return (
            <li
              className={`agent-task-step ${step.status}${selected ? " selected" : ""}`}
              key={step.id}
              aria-current={isCurrent ? "step" : undefined}
            >
              <button
                type={"button"}
                onClick={() => setSelectedStepId(
                  selected ? "" : step.id,
                )}
                aria-expanded={selected}
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
                      trace={selectedTrace}
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
        {["interrupted", "failed"].includes(run.status) ? (
          <button
            type={"button"}
            className={"primary"}
            onClick={() => dispatchAction(run, "resume", messageId)}
          >
            {"继续执行"}
          </button>
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
