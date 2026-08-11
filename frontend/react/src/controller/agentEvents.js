export const AGENT_EVENT_SCHEMA_VERSION = 1;

const LEGACY_EVENT_NAMES = {
  agent_step: "step.updated",
  step_updated: "step.updated",
  tool_started: "tool.started",
  tool_progress: "tool.progress",
  tool_result: "tool.completed",
  tool: "tool.completed",
  approval_required: "approval.required",
  approval_resolved: "approval.resolved",
  approval_submitted: "approval.resolved",
  memory_started: "memory.started",
  memory_result: "memory.completed",
  run_started: "run.started",
  run_snapshot: "run.updated",
  run_updated: "run.updated",
  plan_created: "run.plan_created",
  done: "run.completed",
  cancelled: "run.cancelled",
  error: "error.raised",
  answer: "message.delta",
  message: "message.delta",
  text_delta: "message.delta",
  reference: "artifact.created",
  quality: "run.quality_updated",
};

export function agentEventName(event) {
  const explicit = String(event?.eventName || "").trim();
  if (explicit) return explicit;
  const legacy = String(event?.type || "").trim();
  if (legacy === "agent_step") {
    if (["success", "succeeded", "completed"].includes(event?.status)) return "step.completed";
    if (event?.status === "failed") return "step.failed";
    if (event?.status === "cancelled") return "step.cancelled";
    if (["waiting", "waiting_approval"].includes(event?.status)) return "step.waiting";
  }
  if (["tool_result", "tool"].includes(legacy)) {
    if (event?.status === "failed") return "tool.failed";
    if (event?.status === "cancelled") return "tool.cancelled";
  }
  if (legacy === "memory_result") {
    if (event?.status === "failed") return "memory.failed";
    if (event?.status === "skipped") return "memory.skipped";
    if (event?.status === "cancelled") return "memory.cancelled";
  }
  if (legacy === "done" && event?.status === "cancelled") return "run.cancelled";
  if (["answer", "message", "text_delta"].includes(legacy)) {
    return event?.final ? "message.completed" : "message.delta";
  }
  return LEGACY_EVENT_NAMES[legacy] || legacy.replaceAll("_", ".");
}

export function agentEventIs(event, ...names) {
  return names.includes(agentEventName(event));
}

export function agentEventError(event, fallback = "Agent运行失败。") {
  return {
    code: String(event?.error?.code || event?.errorCode || event?.code || "agent_error"),
    message: String(event?.error?.message || event?.errorMessage || event?.message || fallback),
    retryable: event?.error?.retryable !== false,
    recoveryActions: Array.isArray(event?.recoveryActions) ? event.recoveryActions : [],
  };
}

function mergeTraceStep(trace, step) {
  const next = Array.isArray(trace) ? [...trace] : [];
  const identifier = step?.stepId || step?.id;
  if (!identifier) return next;
  const index = next.findIndex(
    (item) => (item.stepId || item.id) === identifier,
  );
  if (index >= 0) next[index] = { ...next[index], ...step };
  else next.push(step);
  return next;
}

export function markAgentTraceInterrupted(trace) {
  return (Array.isArray(trace) ? trace : []).map((step) => {
    if (step.status === "waiting" && step.kind === "approval") {
      return {
        ...step,
        status: "cancelled",
        title: "确认已取消",
        errorCode: "approval_cancelled",
      };
    }
    return step.status === "running"
      ? {
          ...step,
          status: "failed",
          title: "连接中断",
          errorCode: "stream_interrupted",
        }
      : step;
  });
}

function mergeApproval(approvals, event) {
  const next = Array.isArray(approvals) ? [...approvals] : [];
  const index = next.findIndex(
    (item) => item.approvalId === event.approvalId,
  );
  const value = {
    ...(index >= 0 ? next[index] : {}),
    ...event,
    status: agentEventIs(event, "approval.required")
      ? "waiting"
      : event.status || "cancelled",
  };
  if (index >= 0) next[index] = value;
  else next.push(value);
  return next;
}

export function cancelPendingAgentApprovals(approvals) {
  return (Array.isArray(approvals) ? approvals : []).map((approval) =>
    approval.status === "waiting" && !approval.decision
      ? { ...approval, status: "cancelled", decision: "cancelled" }
      : approval,
  );
}

export function mergeAgentToolCall(toolCalls, event) {
  const next = Array.isArray(toolCalls) ? [...toolCalls] : [];
  const identifier = String(event?.toolCallId || event?.id || "");
  const index = identifier
    ? next.findIndex(
        (item) => String(item?.toolCallId || item?.id || "") === identifier,
      )
    : -1;
  const value = {
    ...(index >= 0 ? next[index] : {}),
    ...event,
    status: event?.normalizedStatus || event?.status,
  };
  if (index >= 0) next[index] = value;
  else next.push(value);
  return next;
}

export function createAgentProjection(initial = {}) {
  return {
    answer: "",
    trace: [],
    approvals: [],
    toolCalls: [],
    references: [],
    run: null,
    memoryActivity: null,
    ragQuality: null,
    retrievalRun: null,
    sessionId: null,
    lastSequence: 0,
    paused: false,
    terminal: null,
    error: null,
    ...initial,
  };
}

export function projectAgentEvent(current, event) {
  const previous = createAgentProjection(current);
  const next = { ...previous };
  const changed = new Set();
  const name = agentEventName(event);
  const sequence = Number(event?.sequence || 0);
  if (Number.isSafeInteger(sequence) && sequence > 0) {
    next.lastSequence = Math.max(previous.lastSequence, sequence);
  }

  if (event?.run) {
    next.run = event.run;
    next.paused = event.run.status === "waiting_approval";
    changed.add("run");
  }
  if (name.startsWith("run.") && event?.run?.status === "waiting_approval") {
    next.paused = true;
  }
  if (name.startsWith("step.")) {
    next.trace = mergeTraceStep(previous.trace, event);
    changed.add("trace");
  }
  if (name === "approval.required" || name === "approval.resolved") {
    next.approvals = mergeApproval(previous.approvals, event);
    next.paused = name === "approval.required"
      ? true
      : next.run?.status === "waiting_approval";
    changed.add("approvals");
  }
  if (name === "message.delta" || name === "message.completed") {
    const content = String(event?.content || "");
    next.answer = name === "message.completed"
      ? content || previous.answer
      : previous.answer + content;
    changed.add("answer");
  }
  if (name.startsWith("tool.")) {
    next.toolCalls = mergeAgentToolCall(previous.toolCalls, event);
    changed.add("toolCalls");
  }
  if (
    (name === "artifact.created" || name === "artifact.updated")
    && event?.artifactType === "reference"
  ) {
    const eventId = String(event?.eventId || "");
    const index = eventId
      ? previous.references.findIndex((item) => item.eventId === eventId)
      : -1;
    next.references = [...previous.references];
    if (index >= 0) next.references[index] = event;
    else next.references.push(event);
    changed.add("references");
  }
  if (name === "run.quality_updated") {
    next.ragQuality = event?.ragQuality || null;
    next.retrievalRun = event?.retrievalRun || null;
    changed.add("quality");
  }
  if (event?.memoryActivity) {
    next.memoryActivity = event.memoryActivity;
    changed.add("memoryActivity");
  }
  if (event?.sessionId) next.sessionId = event.sessionId;

  if (name === "run.completed") {
    if (Array.isArray(event?.trace)) {
      next.trace = event.trace;
      changed.add("trace");
    }
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.paused = false;
    next.terminal = "completed";
    changed.add("approvals");
  } else if (name === "run.cancelled") {
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.trace = markAgentTraceInterrupted(next.trace);
    next.paused = false;
    next.terminal = "cancelled";
    changed.add("approvals");
    changed.add("trace");
  } else if (name === "error.raised" || name === "run.failed") {
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.trace = markAgentTraceInterrupted(next.trace);
    next.paused = false;
    next.terminal = "failed";
    next.error = agentEventError(event);
    changed.add("approvals");
    changed.add("trace");
    changed.add("error");
  }

  return { projection: next, changed: [...changed], eventName: name };
}

export function shouldProcessAgentEvent(seenEventIds, event) {
  const eventId = String(event?.eventId || "");
  if (!eventId) return true;
  if (seenEventIds.has(eventId)) return false;
  seenEventIds.add(eventId);
  if (seenEventIds.size > 5000) {
    const oldest = seenEventIds.values().next().value;
    seenEventIds.delete(oldest);
  }
  return true;
}

export function agentReconnectDelay(attempt, baseMs = 250, maxMs = 4000) {
  const exponent = Math.max(0, Math.min(8, Number(attempt) || 0));
  return Math.min(maxMs, baseMs * (2 ** exponent));
}

export function isRetryableAgentStreamStatus(status) {
  const value = Number(status || 0);
  return value >= 500 || [408, 425, 429].includes(value);
}
