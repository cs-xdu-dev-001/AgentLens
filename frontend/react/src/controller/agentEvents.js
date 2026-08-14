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
  user_question_required: "question.required",
  user_question_resolved: "question.resolved",
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
  usage_updated: "usage.updated",
  context_usage_updated: "context.usage_updated",
};

export function agentEventName(event) {
  const explicit = String(event?.eventName || "").trim();
  if (explicit) return explicit;
  const legacy = String(event?.type || "").trim();
  if (legacy === "agent_step") {
    if (["success", "succeeded", "completed"].includes(event?.status)) return "step.completed";
    if (event?.status === "failed") return "step.failed";
    if (event?.status === "cancelled") return "step.cancelled";
    if (["waiting", "waiting_approval", "waiting_input"].includes(event?.status)) return "step.waiting";
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

export function agentRuntimeStatus(event, fallback = "running") {
  const name = agentEventName(event);
  if (name.endsWith(".completed")) return "completed";
  if (name.endsWith(".failed") || name === "error.raised") return "failed";
  if (name.endsWith(".cancelled")) return "cancelled";
  if (name.endsWith(".skipped")) return "skipped";
  if (name.endsWith(".waiting") || name.endsWith(".required")) return "waiting";
  return String(event?.normalizedStatus || event?.status || fallback || "running");
}

export function agentEventError(event, fallback = "Agent运行失败。") {
  return {
    code: String(event?.error?.code || event?.errorCode || event?.code || "agent_error"),
    message: String(event?.error?.message || event?.errorMessage || event?.message || fallback),
    retryable: event?.error?.retryable !== false,
    recoveryActions: Array.isArray(event?.recoveryActions) ? event.recoveryActions : [],
  };
}

function projectRunSummary(event) {
  const source = event?.runSummary;
  if (!source || typeof source !== "object") return null;
  const runId = String(source.runId || event?.runId || "").slice(0, 200);
  if (!runId) return null;
  const integer = (field) => Math.max(0, Number(source[field]) || 0);
  const totalSteps = integer("totalSteps");
  const completedSteps = Math.min(integer("completedSteps"), totalSteps);
  return {
    runId,
    status: String(source.status || "running").slice(0, 40),
    headline: String(source.headline || "").slice(0, 300),
    startedAt: String(source.startedAt || "").slice(0, 80),
    finishedAt: String(source.finishedAt || "").slice(0, 80),
    completedSteps,
    totalSteps,
    progressPercent: totalSteps
      ? Math.min(100, Math.round((completedSteps / totalSteps) * 100))
      : 0,
    toolCalls: integer("toolCalls"),
    artifactCount: integer("artifactCount"),
    referenceCount: integer("referenceCount"),
    inputTokens: integer("inputTokens"),
    outputTokens: integer("outputTokens"),
    totalTokens: integer("totalTokens"),
  };
}

function mergeTraceStep(trace, step) {
  const next = Array.isArray(trace) ? [...trace] : [];
  const identifier = step?.stepId || step?.id;
  if (!identifier) return next;
  const index = next.findIndex(
    (item) => (item.stepId || item.id) === identifier,
  );
  const previous = index >= 0 ? next[index] : null;
  const value = {
    ...(previous || {}),
    ...step,
    status: agentRuntimeStatus(step, previous?.status || "running"),
  };
  if (index >= 0) next[index] = value;
  else next.push(value);
  return next;
}

const ACTIVE_AGENT_STATUSES = new Set([
  "pending",
  "planning",
  "queued",
  "running",
  "started",
  "waiting",
  "waiting_approval",
  "waiting_input",
  "waiting_start",
]);

export function settleAgentTrace(trace, outcome = "completed") {
  return (Array.isArray(trace) ? trace : []).map((step) => {
    if (!ACTIVE_AGENT_STATUSES.has(String(step?.status || ""))) return step;
    if (outcome === "completed" && step?.kind === "memory") return step;
    const awaitingUser = ["approval", "question"].includes(step?.kind)
      || ["waiting_approval", "waiting_input"].includes(step?.status);
    if (awaitingUser) {
      return {
        ...step,
        status: "cancelled",
        ...(step?.kind === "approval" ? { title: "确认已取消", errorCode: "approval_cancelled" } : {}),
      };
    }
    if (outcome === "failed") {
      return {
        ...step,
        status: "failed",
        title: step?.title || "连接中断",
        errorCode: step?.errorCode || "stream_interrupted",
      };
    }
    return { ...step, status: outcome };
  });
}

export function markAgentTraceInterrupted(trace) {
  return settleAgentTrace(trace, "failed");
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

function mergeQuestion(questions, event) {
  const next = Array.isArray(questions) ? [...questions] : [];
  const id = String(event?.questionId || "");
  if (!id) return next;
  const index = next.findIndex((item) => item.questionId === id);
  const value = {
    ...(index >= 0 ? next[index] : {}),
    ...event,
    status: agentEventIs(event, "question.required") ? "waiting" : "answered",
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

function settlePendingQuestions(questions, status) {
  return (Array.isArray(questions) ? questions : []).map((question) => (
    question?.status === "waiting"
      ? { ...question, status }
      : question
  ));
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
    status: agentRuntimeStatus(
      event,
      index >= 0 ? next[index]?.status : "running",
    ),
  };
  if (index >= 0) next[index] = value;
  else next.push(value);
  return next;
}

function settleAgentToolCalls(toolCalls, outcome) {
  return (Array.isArray(toolCalls) ? toolCalls : []).map((toolCall) => (
    ACTIVE_AGENT_STATUSES.has(String(toolCall?.status || ""))
      ? { ...toolCall, status: outcome }
      : toolCall
  ));
}

function settleRunSteps(steps, outcome) {
  return (Array.isArray(steps) ? steps : []).map((step) => {
    const status = String(step?.status || "");
    if (!ACTIVE_AGENT_STATUSES.has(status)) return step;
    if (outcome === "failed" && ["pending", "queued", "waiting_start"].includes(status)) {
      return { ...step, status: "cancelled" };
    }
    return { ...step, status: outcome };
  });
}

function settleRunSummary(summary, outcome, event) {
  const source = summary && typeof summary === "object" ? summary : null;
  const runId = String(source?.runId || event?.runId || event?.run?.id || "").slice(0, 200);
  if (!source && !runId) return null;
  const totalSteps = Math.max(0, Number(source?.totalSteps) || 0);
  const completedSteps = outcome === "completed"
    ? totalSteps
    : Math.min(Math.max(0, Number(source?.completedSteps) || 0), totalSteps);
  return {
    ...(source || {}),
    ...(runId ? { runId } : {}),
    status: outcome,
    finishedAt: String(
      event?.runSummary?.finishedAt
      || event?.occurredAt
      || source?.finishedAt
      || new Date().toISOString(),
    ).slice(0, 80),
    completedSteps,
    totalSteps,
    progressPercent: totalSteps
      ? Math.min(100, Math.round((completedSteps / totalSteps) * 100))
      : 0,
  };
}

function mergeAgentUsage(current, event) {
  const source = event?.usage && typeof event.usage === "object"
    ? event.usage
    : event || {};
  const value = (camel, snake) => source[camel] ?? source[snake];
  const next = { ...(current || {}) };
  const inputTokens = value("inputTokens", "input_tokens")
    ?? value("promptTokens", "prompt_tokens");
  const outputTokens = value("outputTokens", "output_tokens")
    ?? value("completionTokens", "completion_tokens");
  const totalTokens = value("totalTokens", "total_tokens");
  const estimatedTokens = value("estimatedTokens", "estimated_tokens");
  if (inputTokens != null) next.inputTokens = Math.max(0, Number(inputTokens) || 0);
  if (outputTokens != null) next.outputTokens = Math.max(0, Number(outputTokens) || 0);
  if (totalTokens != null) next.totalTokens = Math.max(0, Number(totalTokens) || 0);
  if (estimatedTokens != null) next.estimatedTokens = Math.max(0, Number(estimatedTokens) || 0);
  if (next.totalTokens == null && (next.inputTokens != null || next.outputTokens != null)) {
    next.totalTokens = (next.inputTokens || 0) + (next.outputTokens || 0);
  }
  return next;
}

const AGENT_ARTIFACT_TYPES = new Set(["file", "link", "reference"]);
const AGENT_ARTIFACT_OPERATIONS = new Set(["edit", "write"]);

function safeAgentText(value, maxLength = 1000) {
  return String(value ?? "")
    .replace(/[\r\n\t]+/g, " ")
    .replace(/[\u001b\u009b][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d\/#&.:=?%@~_]+)*)?[\u0007\u001b\\])|(?:(?:\d{1,4}(?:;\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
    .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, "[已隐藏私钥]")
    .replace(/\bsk-[A-Za-z0-9_-]{12,}\b/g, "[已隐藏]")
    .replace(/\bBearer\s+[A-Za-z0-9._~-]{8,}\b/gi, "Bearer [已隐藏]")
    .replace(/(api[_-]?key|token|password|secret|cookie|authorization|private[_-]?key)(\s*[:=]\s*)\S+/gi, "$1$2[已隐藏]")
    .trim()
    .slice(0, maxLength);
}

function safeAgentUrl(value) {
  const source = safeAgentText(value, 4000);
  if (!/^https?:\/\//i.test(source)) return "";
  try {
    const url = new URL(source);
    return `${url.origin}${url.pathname || "/"}`.slice(0, 4000);
  } catch {
    return "";
  }
}

function safeWorkspaceArtifactPath(value) {
  const path = safeAgentText(value);
  if (!path || path.startsWith("/") || path.includes("\\") || path.includes(":")) return "";
  const parts = path.split("/");
  return parts.some((part) => !part || part === "." || part === "..") ? "" : parts.join("/");
}

function agentArtifactProjection(event) {
  const artifactType = safeAgentText(
    event?.artifactType || (event?.type === "reference" ? "reference" : ""),
    40,
  ).toLowerCase();
  if (!AGENT_ARTIFACT_TYPES.has(artifactType)) return null;
  const path = safeWorkspaceArtifactPath(event?.path);
  const url = safeAgentUrl(event?.url || event?.href);
  const filename = safeAgentText(event?.filename, 300);
  const chunkId = safeAgentText(event?.chunkId || event?.chunk_id, 200);
  if (artifactType === "file" && !path) return null;
  if (artifactType === "link" && !url) return null;
  if (artifactType === "reference" && !url && !filename && !chunkId) return null;
  const identity = path || url || `${filename}:${chunkId}`;
  const artifactId = safeAgentText(
    event?.artifactId || event?.id || `${artifactType}:${identity}`,
    300,
  );
  const artifact = {
    artifactId,
    artifactType,
    title: safeAgentText(event?.title, 300) || filename || path || url,
  };
  if (path) artifact.path = path;
  if (url) artifact.url = url;
  if (filename) artifact.filename = filename;
  if (chunkId) artifact.chunkId = chunkId;
  if (artifactType === "reference") {
    artifact.displayLabel = safeAgentText(event?.displayLabel, 300)
      || filename
      || (() => {
        if (!url) return chunkId ? `片段 #${chunkId.slice(0, 40)}` : "引用来源";
        try {
          const parsed = new URL(url);
          const suffix = parsed.pathname === "/" ? "" : parsed.pathname.replace(/\/$/, "");
          return `${parsed.hostname}${suffix}`.slice(0, 300);
        } catch {
          return "引用来源";
        }
      })();
    artifact.sourceType = url ? "web" : "knowledge";
    const documentId = safeAgentText(event?.documentId || event?.document_id, 100);
    if (documentId) artifact.documentId = documentId;
    const excerpt = safeAgentText(event?.excerpt || event?.content || event?.chunk_text, 600);
    if (excerpt) artifact.excerpt = excerpt;
  }
  const operation = safeAgentText(event?.operation, 40).toLowerCase();
  if (AGENT_ARTIFACT_OPERATIONS.has(operation)) artifact.operation = operation;
  ["addedLines", "removedLines", "writtenBytes"].forEach((field) => {
    if (event?.[field] != null) artifact[field] = Math.max(0, Number(event[field]) || 0);
  });
  ["operationId", "sourceTool", "toolCallId", "changeStatus"].forEach((field) => {
    const value = safeAgentText(event?.[field], 200);
    if (value) artifact[field] = value;
  });
  ["diffAvailable", "reverted"].forEach((field) => {
    if (event?.[field] != null) artifact[field] = Boolean(event[field]);
  });
  if (Number.isFinite(Number(event?.score))) {
    artifact.score = Math.max(0, Math.min(1, Number(event.score)));
  }
  return artifact;
}

export function mergeAgentArtifactUpdate(artifacts, event) {
  const next = Array.isArray(artifacts) ? [...artifacts] : [];
  const artifact = agentArtifactProjection(event);
  if (!artifact) return next;
  const identifier = artifact.artifactId;
  const index = identifier
    ? next.findIndex((item) => String(item?.artifactId || item?.id || item?.eventId || "") === identifier)
    : -1;
  if (index >= 0) next[index] = { ...next[index], ...artifact };
  else next.push(artifact);
  return next;
}

const AGENT_VERIFICATION_KINDS = new Set(["build", "check", "test"]);
const AGENT_VERIFICATION_STATUSES = new Set(["failed", "passed"]);
const AGENT_VERIFICATION_TOOLS = new Set([
  "git_diff_check",
  "lint",
  "npm_build",
  "npm_test",
  "pnpm_build",
  "pnpm_test",
  "project_build",
  "project_test",
  "pytest",
  "python_build",
  "python_check",
  "static_check",
  "typecheck",
  "yarn_build",
  "yarn_test",
]);

function mergeAgentVerification(verifications, event) {
  const verification = event?.verification;
  if (!verification || typeof verification !== "object") {
    return Array.isArray(verifications) ? verifications : [];
  }
  const kind = String(verification.kind || "");
  const status = String(verification.status || "");
  const tool = String(verification.tool || "");
  if (
    !AGENT_VERIFICATION_KINDS.has(kind)
    || !AGENT_VERIFICATION_STATUSES.has(status)
    || !AGENT_VERIFICATION_TOOLS.has(tool)
  ) {
    return Array.isArray(verifications) ? verifications : [];
  }
  const next = Array.isArray(verifications) ? [...verifications] : [];
  const identifier = String(verification.id || event?.toolCallId || event?.eventId || "").slice(0, 200);
  const rawExitCode = verification.exitCode;
  const exitCode = rawExitCode == null || rawExitCode === "" ? null : Number(rawExitCode);
  const rawDurationMs = verification.durationMs == null || verification.durationMs === ""
    ? null
    : Number(verification.durationMs);
  const value = {
    id: identifier,
    kind,
    status,
    tool,
    ...(Number.isFinite(exitCode) ? { exitCode } : {}),
    ...(rawDurationMs != null && Number.isFinite(rawDurationMs)
      ? { durationMs: Math.max(0, rawDurationMs) }
      : {}),
  };
  const index = identifier
    ? next.findIndex((item) => String(item?.id || "") === identifier)
    : -1;
  if (index >= 0) next[index] = { ...next[index], ...value };
  else next.push(value);
  return next;
}

function projectRunMetadata(projection, runId = "") {
  if (!projection.run && !runId) return null;
  return {
    ...(projection.run || {}),
    ...(runId && !projection.run?.id ? { id: runId } : {}),
    artifacts: projection.artifacts,
    context: projection.context,
    phase: projection.phase,
    recoveryActions: projection.recoveryActions,
    runSummary: projection.runSummary,
    usage: projection.usage,
    verifications: projection.verifications,
  };
}

export function createAgentProjection(initial = {}) {
  return {
    answer: "",
    trace: [],
    approvals: [],
    questions: [],
    toolCalls: [],
    references: [],
    artifacts: [],
    context: {},
    usage: {},
    verifications: [],
    recoveryActions: [],
    phase: "",
    run: null,
    runSummary: null,
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
  const runSummary = projectRunSummary(event);
  if (runSummary) {
    next.runSummary = runSummary;
    changed.add("runSummary");
  }
  const sequence = Number(event?.sequence || 0);
  if (Number.isSafeInteger(sequence) && sequence > 0) {
    next.lastSequence = Math.max(previous.lastSequence, sequence);
  }

  if (event?.run) {
    next.run = { ...(previous.run || {}), ...event.run };
    next.paused = ["waiting_approval", "waiting_input"].includes(event.run.status);
    changed.add("run");
    if (event.run?.status === "waiting_input" && event.run?.pendingQuestion) {
      next.questions = mergeQuestion(previous.questions, {
        ...event.run.pendingQuestion,
        eventName: "question.required",
        runId: event.run.id,
      });
      changed.add("questions");
    }
  }
  if (
    name.startsWith("run.")
    && ["waiting_approval", "waiting_input"].includes(event?.run?.status)
  ) {
    next.paused = true;
  }
  if (name.startsWith("step.")) {
    next.trace = mergeTraceStep(previous.trace, event);
    next.phase = String(event?.title || event?.name || event?.phase || previous.phase || "");
    changed.add("trace");
  }
  if (name === "approval.required" || name === "approval.resolved") {
    next.approvals = mergeApproval(previous.approvals, event);
    next.paused = name === "approval.required"
      ? true
      : next.run?.status === "waiting_approval";
    changed.add("approvals");
  }
  if (name === "question.required" || name === "question.resolved") {
    next.questions = mergeQuestion(previous.questions, event);
    next.paused = name === "question.required"
      ? true
      : next.run?.status === "waiting_input";
    changed.add("questions");
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
    next.phase = String(event?.toolName || event?.phase || previous.phase || "");
    changed.add("toolCalls");
    if (event?.verification) {
      next.verifications = mergeAgentVerification(previous.verifications, event);
      changed.add("verifications");
    }
  }
  if (
    (name === "artifact.created" || name === "artifact.updated")
  ) {
    next.artifacts = mergeAgentArtifactUpdate(previous.artifacts, event);
    changed.add("artifacts");
    if (event?.artifactType === "reference") {
      next.references = mergeAgentArtifactUpdate(previous.references, event);
      changed.add("references");
    }
  }
  if (name === "usage.updated") {
    next.usage = mergeAgentUsage(previous.usage, event);
    changed.add("usage");
  }
  if (name === "context.usage_updated" || name === "context.compacted") {
    next.context = {
      ...(previous.context || {}),
      ...event,
      ...(name === "context.compacted" ? { compacted: true } : {}),
    };
    changed.add("context");
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
  const metadataPhase = Boolean(event?.phase)
    && !name.startsWith("message.")
    && !name.startsWith("context.");
  if (metadataPhase && !name.startsWith("step.") && !name.startsWith("tool.")) {
    next.phase = String(event.phase);
  }
  if (Array.isArray(event?.recoveryActions) && event.recoveryActions.length) {
    next.recoveryActions = [...new Set(event.recoveryActions.map(String))];
    changed.add("recoveryActions");
  }

  if (name === "run.completed") {
    if (Array.isArray(event?.trace)) {
      next.trace = settleAgentTrace(event.trace, "completed");
    } else {
      next.trace = settleAgentTrace(next.trace, "completed");
    }
    next.toolCalls = settleAgentToolCalls(next.toolCalls, "completed");
    next.runSummary = settleRunSummary(next.runSummary, "completed", event);
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.questions = settlePendingQuestions(next.questions, "answered");
    next.paused = false;
    next.terminal = "completed";
    next.error = null;
    next.recoveryActions = [];
    changed.add("trace");
    changed.add("toolCalls");
    if (next.runSummary) changed.add("runSummary");
    changed.add("approvals");
    changed.add("questions");
    changed.add("recoveryActions");
  } else if (name === "run.cancelled") {
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.questions = settlePendingQuestions(next.questions, "cancelled");
    next.trace = markAgentTraceInterrupted(next.trace);
    next.toolCalls = settleAgentToolCalls(next.toolCalls, "cancelled");
    next.runSummary = settleRunSummary(next.runSummary, "cancelled", event);
    next.paused = false;
    next.terminal = "cancelled";
    next.recoveryActions = [];
    changed.add("approvals");
    changed.add("questions");
    changed.add("trace");
    changed.add("toolCalls");
    if (next.runSummary) changed.add("runSummary");
    changed.add("recoveryActions");
  } else if (name === "error.raised" || name === "run.failed") {
    next.approvals = cancelPendingAgentApprovals(next.approvals);
    next.questions = settlePendingQuestions(next.questions, "cancelled");
    next.trace = markAgentTraceInterrupted(next.trace);
    next.toolCalls = settleAgentToolCalls(next.toolCalls, "failed");
    next.runSummary = settleRunSummary(next.runSummary, "failed", event);
    next.paused = false;
    next.terminal = "failed";
    next.error = agentEventError(event);
    next.recoveryActions = next.error.recoveryActions;
    changed.add("approvals");
    changed.add("questions");
    changed.add("trace");
    changed.add("toolCalls");
    if (next.runSummary) changed.add("runSummary");
    changed.add("error");
    changed.add("recoveryActions");
  }

  if (["completed", "cancelled", "failed"].includes(next.terminal)) {
    const finishedAt = next.runSummary?.finishedAt || event?.occurredAt || new Date().toISOString();
    next.run = {
      ...(next.run || {}),
      ...(event?.runId && !next.run?.id ? { id: event.runId } : {}),
      status: next.terminal,
      steps: settleRunSteps(next.run?.steps, next.terminal),
      currentStepId: null,
      finishedAt,
      updatedAt: finishedAt,
      runSummary: next.runSummary,
    };
    changed.add("run");
  }

  if (
    changed.has("usage")
    || changed.has("context")
    || changed.has("artifacts")
    || changed.has("verifications")
    || changed.has("recoveryActions")
    || changed.has("runSummary")
    || metadataPhase
    || event?.run
  ) {
    next.run = projectRunMetadata(next, event?.runId);
    changed.add("run");
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
