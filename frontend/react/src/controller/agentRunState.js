const activeStatuses = new Set([
  "planning",
  "running",
  "waiting_approval",
]);

const completedStepStatuses = new Set([
  "completed",
  "skipped",
  "cancelled",
]);
const terminalTraceStatuses = new Set([
  "success",
  "failed",
  "cancelled",
]);

export function isActiveRun(run) {
  return Boolean(run?.id && activeStatuses.has(run.status));
}

export function traceStepWaitState(step) {
  const waiting = ["waiting", "waiting_approval"].includes(
    step?.status,
  );
  return {
    approval: Boolean(
      waiting
      && (
        step?.kind === "approval"
        || step?.status === "waiting_approval"
      )
    ),
    background: Boolean(waiting && step?.kind === "memory"),
  };
}

export function hasPendingBackgroundStep(trace) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  return safeTrace.some(
    (step) =>
      step?.kind === "memory"
      && ["waiting", "running"].includes(step?.status),
  );
}

export function currentRunStep(run) {
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  return (
    steps.find((step) => step.id === run?.currentStepId)
    || steps.find((step) =>
      ["running", "waiting_approval"].includes(step.status),
    )
    || steps.find((step) => step.status === "pending")
    || steps.at(-1)
    || null
  );
}

export function runProgress(run, trace = []) {
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  if (!steps.length) {
    const safeTrace = Array.isArray(trace) ? trace : [];
    return {
      completed: safeTrace.filter((step) =>
        terminalTraceStatuses.has(step.status),
      ).length,
      total: safeTrace.length,
    };
  }
  return {
    completed: steps.filter((step) =>
      completedStepStatuses.has(step.status),
    ).length,
    total: steps.length,
  };
}

export function traceForPlanStep(trace, planStepId) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  if (!planStepId) return safeTrace;
  const roots = new Set(
    safeTrace
      .filter((step) => step.details?.planStepId === planStepId)
      .map((step) => step.stepId),
  );
  if (!roots.size) return [];
  const included = new Set(roots);
  let changed = true;
  while (changed) {
    changed = false;
    safeTrace.forEach((step) => {
      if (
        !included.has(step.stepId)
        && included.has(step.parentId)
      ) {
        included.add(step.stepId);
        changed = true;
      }
    });
  }
  return safeTrace.filter((step) => included.has(step.stepId));
}
