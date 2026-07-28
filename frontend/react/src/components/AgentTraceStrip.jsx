import { traceStepTitle } from "./AgentTraceView.jsx";
import {
  currentRunStep,
  runProgress,
} from "../controller/agentRunState.js";


function currentStep(trace) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  return (
    [...safeTrace].reverse().find(
      (step) =>
        step.status === "waiting" &&
        step.kind === "approval",
    )
    ||
    [...safeTrace].reverse().find(
      (step) => step.status === "running",
    )
    || [...safeTrace].reverse().find(Boolean)
    || null
  );
}

export function AgentTraceStrip({
  messageId,
  trace = [],
  approvals = [],
  run = null,
}) {
  const durableStep = currentRunStep(run);
  const step = durableStep || currentStep(trace);
  if (!step) return null;
  const running = ["planning", "running"].includes(step.status);
  const waiting = ["waiting", "waiting_approval"].includes(
    step.status,
  );
  const progress = runProgress(run);
  const completed = trace.filter(
    (item) => item.status === "success",
  ).length;
  const terminal = trace.filter(
    (item) => (
      item.status === "success"
      || item.status === "failed"
      || item.status === "cancelled"
    ),
  ).length;
  const handleOpen = () => {
    window.dispatchEvent(
      new CustomEvent(
        "knowflow:react-agent-trace-open",
        {
          detail: { messageId, trace, approvals, run },
        },
      ),
    );
    window.dispatchEvent(
      new CustomEvent("knowflow:react-drawer-open"),
    );
  };

  return (
    <button
      className={`agent-trace-strip ${step.status}`}
      type={"button"}
      onClick={handleOpen}
      aria-label={"查看Agent运行过程"}
    >
      <span
        className={"agent-trace-signal"}
        aria-hidden={"true"}
      ></span>
      <span
        className={"agent-trace-strip-copy"}
        aria-live={"polite"}
      >
        <strong>
          {durableStep ? durableStep.title : traceStepTitle(step)}
        </strong>
        <small>
          {waiting
            ? "Agent已暂停，确认后继续"
            : running
            ? run?.id
              ? `${progress.completed}/${progress.total}个步骤完成`
              : `${completed}/${trace.length || 1}个步骤完成`
            : `${terminal}个步骤已结束`}
        </small>
      </span>
      <span className={"agent-trace-strip-time"}>
        {step.durationMs != null
          ? `${step.durationMs}ms`
          : waiting
            ? "等待确认"
            : "运行中"}
      </span>
      <svg
        viewBox={"0 0 20 20"}
        width={"18"}
        height={"18"}
        aria-hidden={"true"}
      >
        <path d={"M6 14 14 6M8 6h6v6"}></path>
      </svg>
    </button>
  );
}
