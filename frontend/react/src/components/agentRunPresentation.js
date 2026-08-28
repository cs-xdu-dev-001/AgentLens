import {
  currentRunStep,
  hasPendingBackgroundStep,
  runProgress,
  traceStepWaitState,
} from "../controller/agentRunState.js";
import { traceStepTitle } from "./agentTracePresentation.js";
export { mergeAgentArtifactUpdate } from "../controller/agentEvents.js";

const terminalStatuses = new Set([
  "cancelled",
  "completed",
  "failed",
  "skipped",
  "success",
]);

const kindLabels = {
  agent: "Agent",
  approval: "确认",
  memory: "记忆",
  mcp: "MCP",
  model: "模型",
  plan: "计划",
  skill: "Skill",
  tool: "工具",
};

const stepStatusLabels = {
  cancelled: "已取消",
  completed: "已完成",
  failed: "失败",
  interrupted: "已中断",
  pending: "等待",
  planning: "规划中",
  running: "运行中",
  skipped: "已跳过",
  success: "已完成",
  waiting: "等待",
  waiting_approval: "等待确认",
  waiting_input: "等待回答",
  waiting_start: "等待开始",
};

const operationKinds = new Set([
  "approval",
  "memory",
  "mcp",
  "sandbox",
  "skill",
  "tool",
  "workspace",
]);

const operationVerbs = {
  activate_skill: "激活",
  list_workspace: "查看工作区",
  memory_recall: "召回记忆",
  memory_write: "整理记忆",
  read_workspace_file: "读取",
  run_sandbox_command: "运行",
  tool_search: "查找工具",
  web_fetch: "读取网页",
  web_search: "搜索",
  write_workspace_file: "更新",
};

const RUN_QUIET_AFTER_MS = 15_000;
const RUN_STALLED_AFTER_MS = 45_000;

export function pendingAgentInteractions({ approvals = [], questions = [] } = {}) {
  const safeApprovals = Array.isArray(approvals) ? approvals : [];
  const safeQuestions = Array.isArray(questions) ? questions : [];
  const rows = [
    ...safeApprovals.flatMap((approval, index) => (
      approval?.status === "waiting" && !approval?.decision
        ? [{ kind: "approval", value: approval, fallbackOrder: index }]
        : []
    )),
    ...safeQuestions.flatMap((question, index) => (
      question?.status === "waiting"
        ? [{ kind: "question", value: question, fallbackOrder: safeApprovals.length + index }]
        : []
    )),
  ];
  const order = (row) => {
    const sequence = Number(row.value?.sequence);
    if (Number.isFinite(sequence)) return sequence;
    const occurredAt = Date.parse(row.value?.occurredAt || row.value?.createdAt || "");
    return Number.isFinite(occurredAt) ? occurredAt : Number.MAX_SAFE_INTEGER;
  };
  return rows.sort((left, right) => (
    order(left) - order(right) || left.fallbackOrder - right.fallbackOrder
  ));
}

export function pendingAgentInteractionOwners(messages = []) {
  const safeMessages = Array.isArray(messages) ? messages : [];
  return safeMessages.flatMap((message, messageOrder) => (
    pendingAgentInteractions(message).map((interaction, interactionOrder) => ({
      interaction,
      interactionOrder,
      messageId: String(message?.id || ""),
      messageOrder,
    }))
  ));
}

export function activeAgentInteractionOwner(messages = []) {
  const owners = pendingAgentInteractionOwners(messages);
  return owners.length
    ? { ...owners[0], queuedCount: Math.max(0, owners.length - 1) }
    : null;
}

export function agentWorkbenchDefaultTab({
  run = null,
  artifacts = [],
  references = [],
} = {}) {
  const status = String(run?.runSummary?.status || run?.status || "");
  if (["failed", "interrupted"].includes(status)) return "trace";
  if (!["completed", "success"].includes(status)) return "trace";
  if (Array.isArray(artifacts) && artifacts.length) return "artifacts";
  if (Array.isArray(references) && references.length) return "evidence";
  return "trace";
}

const redactionPatterns = [
  [/\bsk-[A-Za-z0-9_-]{12,}\b/g, "[已隐藏]"],
  [/\bBearer\s+[A-Za-z0-9._~-]{8,}\b/gi, "Bearer [已隐藏]"],
  [/(api[_-]?key|token|password|secret|cookie|authorization)(\s*[:=]\s*)\S+/gi, "$1$2[已隐藏]"],
  [/(--(?:api[-_]?key|token|password|secret|cookie|authorization))(?:=|\s+)\S+/gi, "$1=[已隐藏]"],
];

function parseSummary(value) {
  if (value && typeof value === "object") return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

export function compactPublicText(value, limit = 84) {
  if (!["string", "number", "boolean"].includes(typeof value)) return "";
  let text = String(value).replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim();
  redactionPatterns.forEach(([pattern, replacement]) => {
    text = text.replace(pattern, replacement);
  });
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function publicUrlTarget(value) {
  const text = compactPublicText(value, 300);
  if (!text) return "";
  try {
    const url = new URL(text);
    const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
    return compactPublicText(`${url.hostname}${path}`, 84);
  } catch {
    return compactPublicText(text.split(/[?#]/, 1)[0], 84);
  }
}

function operationTarget(step, input) {
  const details = step?.details && typeof step.details === "object" ? step.details : {};
  const name = String(step?.name || "");
  if (name === "web_fetch") return publicUrlTarget(input.url || input.href);
  if (name === "web_search") return compactPublicText(input.query || input.q);
  if (name === "run_sandbox_command") return compactPublicText(input.command || input.cmd, 100);
  if (name === "activate_skill" || step?.kind === "skill") {
    return compactPublicText(details.displayName || input.skillName || input.skill_id || input.name);
  }
  if (step?.kind === "mcp") {
    return compactPublicText(
      input.page_id || input.database_id || input.path || details.serverName || "",
    );
  }
  return compactPublicText(input.path || input.target || input.filename || "");
}

function operationOutcome(step, output) {
  const values = [];
  const resultCount = output.resultCount ?? (Array.isArray(output.results) ? output.results.length : null);
  const entries = Array.isArray(output.entries) ? output.entries.length : output.entries;
  const writtenBytes = Number(output.writtenBytes ?? output.written_bytes);
  if (resultCount != null) values.push(`${Math.max(0, Number(resultCount) || 0)}个结果`);
  if (entries != null) values.push(`${Math.max(0, Number(entries) || 0)}个条目`);
  if (Number.isFinite(writtenBytes) && writtenBytes > 0) values.push(`${writtenBytes} B`);
  if (output.exit_code != null) values.push(`退出码${output.exit_code}`);
  if (step?.errorCode) values.push(String(step.errorCode));
  return values.join(" · ");
}

export function buildAgentOperationPresentation(step) {
  const kind = String(step?.kind || "");
  if (!operationKinds.has(kind)) return null;
  const name = String(step?.name || kind || "tool");
  const status = String(step?.status || "running");
  const input = parseSummary(step?.inputSummary ?? step?.arguments);
  const output = parseSummary(step?.outputSummary ?? step?.output);
  const target = operationTarget(step, input);
  const verb = operationVerbs[name]
    || (kind === "approval" ? "确认" : kind === "mcp" ? "调用" : kind === "skill" ? "激活" : "执行");
  const visibleTarget = target || (
    !operationVerbs[name] && !["approval", "skill"].includes(kind)
      ? compactPublicText(name.replaceAll("_", " "))
      : ""
  );
  const running = ["planning", "running", "waiting"].includes(status);
  const failed = ["failed", "interrupted"].includes(status);
  const title = kind === "approval"
    ? failed
      ? "操作确认失败"
      : running
        ? "等待操作确认"
        : "操作已确认"
    : failed
      ? `${verb}${visibleTarget ? ` ${visibleTarget}` : ""}失败`
      : running
      ? `正在${verb}${visibleTarget ? ` ${visibleTarget}` : ""}`
      : `已${verb}${visibleTarget ? ` ${visibleTarget}` : ""}`;
  return {
    durationMs: step?.durationMs ?? null,
    elapsedSeconds: step?.elapsedSeconds,
    id: String(step?.id || step?.stepId || `${kind}-${name}-${visibleTarget}`),
    kind,
    latencyMs: step?.latencyMs,
    name,
    operationKey: `${kind}:${name}:${visibleTarget}`,
    outcome: operationOutcome(step, output),
    repeatCount: Math.max(1, Number(step?.repeatCount) || 1),
    status,
    target: visibleTarget,
    title,
    totalBytes: step?.totalBytes,
    totalLines: step?.totalLines,
  };
}

function formatElapsed(milliseconds) {
  const value = Math.max(0, Number(milliseconds) || 0);
  if (value < 1000) return `${Math.round(value)}ms`;
  if (value < 60_000) return `${Math.round(value / 1000)}s`;
  const minutes = Math.floor(value / 60_000);
  const seconds = Math.floor((value % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

export function buildAgentDeliveryPresentation({
  artifacts = [],
  verifications = [],
  runStatus = "",
} = {}) {
  const safeArtifacts = Array.isArray(artifacts) ? artifacts : [];
  const safeVerifications = Array.isArray(verifications) ? verifications : [];
  const status = String(runStatus || "").trim().toLowerCase();
  const cancelled = ["cancelled", "canceled", "已取消"].includes(status);
  const failedRun = ["error", "failed", "interrupted", "执行失败", "失败"].includes(status);
  const failedCount = safeVerifications.filter((item) => item?.status === "failed").length;
  const passedCount = safeVerifications.filter((item) => item?.status === "passed").length;
  const externalCount = safeArtifacts.filter((artifact) => /^https?:\/\//i.test(String(
    artifact?.url || artifact?.href || artifact?.path || "",
  ))).length;
  const fileCount = Math.max(0, safeArtifacts.length - externalCount);
  const revertedCount = safeArtifacts.filter((artifact) => artifact?.reverted).length;
  const metrics = safeArtifacts.reduce((total, artifact) => ({
    added: total.added + Math.max(0, Number(artifact?.addedLines) || 0),
    removed: total.removed + Math.max(0, Number(artifact?.removedLines) || 0),
  }), { added: 0, removed: 0 });
  const summary = [
    fileCount ? `${fileCount}个文件已更改` : "",
    externalCount ? `${externalCount}个链接已生成` : "",
    revertedCount ? `${revertedCount}项已撤销` : "",
    safeVerifications.length ? `${passedCount}/${safeVerifications.length}项验证通过` : "",
  ].filter(Boolean).join(" · ");

  let state = { className: "unverified", label: "待验证" };
  if (cancelled) state = { className: "cancelled", label: "已取消" };
  else if (failedRun) state = { className: "failed", label: "运行失败" };
  else if (failedCount) state = { className: "failed", label: `${failedCount}项未通过` };
  else if (safeVerifications.length) state = { className: "passed", label: "验证通过" };

  const partial = cancelled || failedRun;
  const failedVerification = failedCount > 0;
  return {
    ...metrics,
    cancelled,
    externalCount,
    failedRun,
    failedVerification,
    fileCount,
    passedCount,
    revertedCount,
    summary,
    title: partial ? "本轮结果" : safeArtifacts.length ? "本轮交付" : "本轮验收",
    state,
    expandByDefault: partial || failedVerification,
    actionLabel: failedVerification
      ? "查看失败步骤与恢复操作"
      : partial
        ? "查看未完成步骤"
        : safeArtifacts.length
          ? "审阅文件变更"
          : "查看验证过程",
    actionTarget: failedVerification || partial
      ? "trace"
      : safeArtifacts.length ? "artifacts" : "trace",
  };
}

const verificationStatuses = new Set([
  "cancelled",
  "completed",
  "error",
  "failed",
  "interrupted",
  "success",
  "succeeded",
]);

const verificationRules = [
  { label: "测试", tool: "pytest", pattern: /\b(?:pytest|python(?:\d+(?:\.\d+)?)?\s+-m\s+pytest)\b/i },
  { label: "测试", tool: "Python检查", pattern: /\btests[\\/]check_[^\s"']+\.py\b/i },
  { label: "测试", tool: "npm test", pattern: /\bnpm\s+(?:run\s+)?test\b/i },
  { label: "测试", tool: "pnpm test", pattern: /\bpnpm\s+(?:run\s+)?test\b/i },
  { label: "测试", tool: "yarn test", pattern: /\byarn\s+test\b/i },
  { label: "测试", tool: "项目测试", pattern: /\b(?:vitest|jest|unittest|cargo\s+test|go\s+test|dotnet\s+test)\b/i },
  { label: "构建", tool: "npm run build", pattern: /\bnpm\s+run\s+build\b/i },
  { label: "构建", tool: "pnpm build", pattern: /\bpnpm\s+(?:run\s+)?build\b/i },
  { label: "构建", tool: "yarn build", pattern: /\byarn\s+build\b/i },
  { label: "构建", tool: "Python构建", pattern: /\bpython(?:\d+(?:\.\d+)?)?\s+-m\s+build\b/i },
  { label: "构建", tool: "项目构建", pattern: /\b(?:vite\s+build|cargo\s+build|go\s+build|mvn\b[^\r\n]*\bpackage|gradle\b[^\r\n]*\bbuild)\b/i },
  { label: "差异检查", tool: "git diff --check", pattern: /\bgit\s+diff\s+--check\b/i },
  { label: "代码检查", tool: "lint", pattern: /\b(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b/i },
  { label: "类型检查", tool: "typecheck", pattern: /\b(?:(?:npm|pnpm|yarn)\s+(?:run\s+)?typecheck|tsc\s+--noEmit)\b/i },
  { label: "代码检查", tool: "静态检查", pattern: /\b(?:ruff|mypy|flake8|eslint|prettier\s+--check)\b/i },
];

const verificationKindLabels = {
  build: "构建",
  check: "代码检查",
  test: "测试",
};

const verificationToolLabels = {
  git_diff_check: "git diff --check",
  lint: "lint",
  npm_build: "npm run build",
  npm_test: "npm test",
  pnpm_build: "pnpm build",
  pnpm_test: "pnpm test",
  project_build: "项目构建",
  project_test: "项目测试",
  pytest: "pytest",
  python_build: "Python构建",
  python_check: "Python检查",
  static_check: "静态检查",
  typecheck: "typecheck",
  yarn_build: "yarn build",
  yarn_test: "yarn test",
};

function verificationRule(command) {
  const safeCommand = compactPublicText(command, 1000);
  if (!safeCommand) return null;
  return verificationRules.find((rule) => rule.pattern.test(safeCommand)) || null;
}

function protocolVerificationPresentation(items = []) {
  return (Array.isArray(items) ? items : []).flatMap((item, index) => {
    if (!item || typeof item !== "object") return [];
    const status = String(item.status || "");
    if (!['failed', 'passed'].includes(status)) return [];
    const kind = String(item.kind || "check");
    const tool = String(item.tool || "");
    const rawExitCode = item.exitCode;
    const exitCode = rawExitCode == null || rawExitCode === "" ? null : Number(rawExitCode);
    return [{
      duration: item.durationMs == null ? "" : formatElapsed(item.durationMs),
      durationMs: item.durationMs ?? null,
      exitCode: Number.isFinite(exitCode) ? exitCode : null,
      id: String(item.id || `verification-${index}`),
      label: tool === "git_diff_check" ? "差异检查" : verificationKindLabels[kind] || "代码检查",
      status,
      statusLabel: status === "failed" ? "失败" : "通过",
      tool: verificationToolLabels[tool] || "项目检查",
    }];
  });
}

export function buildAgentVerificationPresentation(trace = [], protocolVerifications = []) {
  const projected = protocolVerificationPresentation(protocolVerifications);
  if (projected.length) return projected;
  return (Array.isArray(trace) ? trace : []).flatMap((step, index) => {
    if (String(step?.name || "") !== "run_sandbox_command") return [];
    const status = String(step?.status || "").toLowerCase();
    if (!verificationStatuses.has(status)) return [];
    const input = parseSummary(step?.inputSummary ?? step?.arguments);
    const rule = verificationRule(input.command ?? input.cmd);
    if (!rule) return [];
    const output = parseSummary(step?.outputSummary ?? step?.output);
    const rawExitCode = output.exit_code ?? output.exitCode ?? step?.exitCode;
    const exitCode = rawExitCode == null || rawExitCode === "" ? null : Number(rawExitCode);
    const failed = ["cancelled", "error", "failed", "interrupted"].includes(status)
      || (Number.isFinite(exitCode) && exitCode !== 0);
    return [{
      duration: step?.durationMs == null ? "" : formatElapsed(step.durationMs),
      durationMs: step?.durationMs ?? null,
      exitCode: Number.isFinite(exitCode) ? exitCode : null,
      id: String(step?.id || step?.stepId || `verification-${index}`),
      label: rule.label,
      status: failed ? "failed" : "passed",
      statusLabel: failed ? "失败" : "通过",
      tool: rule.tool,
    }];
  });
}

export function verificationTraceStepId(verification, trace = []) {
  const identifier = String(verification?.id || "");
  if (!identifier) return "";
  const rows = Array.isArray(trace) ? trace : [];
  const exact = rows.find(
    (step) => String(step?.stepId || step?.id || "") === identifier,
  );
  if (exact) return String(exact.stepId || exact.id || "");
  const toolCallId = identifier.replace(/^verification:/, "");
  const related = rows.find((step) => String(
    step?.details?.toolCallId || step?.toolCallId || "",
  ) === toolCallId);
  return String(related?.stepId || related?.id || "");
}

function formatTokens(value, { estimated = false } = {}) {
  const tokens = Math.max(0, Number(value) || 0);
  if (!tokens) return "";
  const prefix = estimated ? "~" : "";
  if (tokens < 1000) return `${prefix}${Math.round(tokens)} tokens`;
  const compact = (tokens / 1000).toFixed(tokens < 10_000 ? 1 : 0);
  return `${prefix}${compact.replace(/\.0$/, "")}k tokens`;
}

function contextPresentation(run) {
  const context = run?.context;
  if (!context || typeof context !== "object") return null;
  const maxTokens = Math.max(0, Number(context.maxTokens) || 0);
  if (!maxTokens) return null;
  const usedTokens = Math.max(0, Number(context.usedTokens) || 0);
  const usagePercent = Math.max(
    0,
    Number(context.usagePercent) || ((usedTokens / maxTokens) * 100),
  );
  const warningAtPercent = Math.max(
    1,
    Number(context.warningAtPercent ?? context.autoCompactAtPercent) || 75,
  );
  const trimmed = Boolean(context.contextTrimmed || context.compacted);
  const warning = Boolean(
    trimmed
    || context.shouldWarn
    || context.shouldAutoCompact
    || usagePercent >= warningAtPercent,
  );
  if (!warning) return null;
  return {
    label: trimmed ? "上下文已安全裁剪" : `上下文${Math.round(usagePercent)}%`,
    detail: trimmed
      ? "已保留系统规则和最近完整工具轮次"
      : `剩余${formatTokens(context.remainingTokens || (maxTokens - usedTokens)) || "0 tokens"}`,
    percent: Math.min(100, usagePercent),
    trimmed,
  };
}

function currentTraceStep(trace) {
  return (
    [...trace].reverse().find(
      (step) => step.status === "waiting" && step.kind === "approval",
    )
    || [...trace].reverse().find((step) => step.status === "running")
    || [...trace].reverse().find(Boolean)
    || null
  );
}

const compactableKinds = new Set(["memory", "mcp", "model", "skill", "tool"]);
const compactableStatuses = new Set(["completed", "skipped", "success", "succeeded"]);

function compactRunRows(rows) {
  const compacted = [];
  rows.forEach((source) => {
    const row = { ...source, repeatCount: Math.max(1, Number(source.repeatCount) || 1) };
    const previous = compacted.at(-1);
    const sameOperation = previous
      && compactableKinds.has(row.kind)
      && compactableStatuses.has(row.status)
      && previous.kind === row.kind
      && previous.name === row.name
      && (previous.operationKey || "") === (row.operationKey || "")
      && previous.status === row.status;
    if (!sameOperation) {
      compacted.push(row);
      return;
    }
    previous.repeatCount += row.repeatCount;
    if (previous.durationMs != null || row.durationMs != null) {
      previous.durationMs = (Number(previous.durationMs) || 0) + (Number(row.durationMs) || 0);
    }
  });
  return compacted;
}

function runRows(run, trace) {
  const planSteps = Array.isArray(run?.steps) ? run.steps : [];
  if (planSteps.length) {
    return planSteps.map((step) => {
      const relatedTrace = [...trace].reverse().find((item) => (
        item.details?.planStepId === step.id || item.planStepId === step.id
      ));
      return {
        durationMs: relatedTrace?.durationMs ?? null,
        elapsedSeconds: step.elapsedSeconds ?? relatedTrace?.elapsedSeconds ?? null,
        id: step.id,
        kind: step.kind || relatedTrace?.kind || "plan",
        name: step.name || relatedTrace?.name || step.id,
        repeatCount: 1,
        status: step.status,
        title: step.title,
        toolCallId: step.toolCallId || relatedTrace?.toolCallId || "",
        toolName: step.toolName || relatedTrace?.toolName || "",
        totalBytes: step.totalBytes ?? relatedTrace?.totalBytes ?? null,
        totalLines: step.totalLines ?? relatedTrace?.totalLines ?? null,
      };
    });
  }
  const operations = compactRunRows(trace
    .map(buildAgentOperationPresentation)
    .filter(Boolean));
  const liveInternal = trace
    .filter((step) => !buildAgentOperationPresentation(step))
    .filter((step) => ["failed", "interrupted", "planning", "running", "waiting"].includes(step.status))
    .map((step) => ({
      durationMs: step.durationMs ?? null,
      id: step.stepId,
      kind: step.kind,
      name: step.name,
      status: step.status,
      title: traceStepTitle(step),
    }));
  if (operations.length) return [...operations, ...liveInternal];
  return compactRunRows(trace
    .filter((step) => step.name !== "agent_run")
    .map((step) => ({
      durationMs: step.durationMs ?? null,
      id: step.stepId,
      kind: step.kind,
      name: step.name,
      status: step.status,
      title: traceStepTitle(step),
    })));
}

function liveProgressMeta(value) {
  if (!value || typeof value !== "object") return "";
  const parts = [];
  const elapsed = Number(value.elapsedSeconds);
  const lines = Number(value.totalLines);
  const bytes = Number(value.totalBytes);
  if (Number.isFinite(elapsed) && elapsed >= 0) parts.push(`${elapsed.toFixed(1)}s`);
  if (Number.isFinite(lines) && lines > 0) parts.push(`${Math.round(lines)}行`);
  if (Number.isFinite(bytes) && bytes > 0) parts.push(`${Math.round(bytes)}B`);
  return parts.join(" · ");
}

function statusPresentation(run, step, waitState, backgroundPending) {
  const status = run?.status || step?.status || "waiting";
  if (run?.modelRetry) {
    return {
      className: "waiting",
      freshness: "自动恢复中",
      label: "等待重试",
    };
  }
  if (waitState.background || backgroundPending) {
    return {
      className: "running",
      detail: "后台整理中，不影响继续对话",
      freshness: "后台处理中",
      label: run?.status === "completed" ? "回答已完成" : "后台整理中",
    };
  }
  if (waitState.approval || status === "waiting_approval") {
    return { className: "waiting", freshness: "等待", label: "等待确认" };
  }
  if (status === "waiting_input") {
    return { className: "waiting", freshness: "等待", label: "等待回答" };
  }
  if (["failed", "interrupted"].includes(status)) {
    return {
      className: "failed",
      freshness: "已保存",
      label: status === "failed" ? "失败" : "已中断",
    };
  }
  if (status === "cancelled") {
    return { className: "cancelled", freshness: "已保存", label: "已取消" };
  }
  if (["planning", "running"].includes(status)) {
    return {
      className: "running",
      freshness: "实时",
      label: status === "planning" ? "规划中" : "执行中",
    };
  }
  if (["completed", "success"].includes(status)) {
    return { className: "success", freshness: "已保存", label: "已完成" };
  }
  return { className: "waiting", freshness: "等待", label: "等待开始" };
}

function latestActivityAt(run, trace, startedAt) {
  const candidates = [
    run?.runSummary?.lastActivityAt,
    run?.lastActivityAt,
    run?.updatedAt,
    ...trace.flatMap((item) => [
      item?.occurredAt,
      item?.updatedAt,
      item?.finishedAt,
      item?.startedAt,
    ]),
  ].map((value) => Date.parse(value || "")).filter(Number.isFinite);
  return candidates.length ? Math.max(...candidates) : startedAt;
}

function quietRunStatus(status, { active, lastActivityAt, now, protectedState }) {
  if (!active || protectedState || !Number.isFinite(lastActivityAt)) return status;
  const quietForMs = Math.max(0, now - lastActivityAt);
  if (quietForMs >= RUN_STALLED_AFTER_MS) {
    return {
      className: "waiting",
      detail: "暂未收到新进展，任务仍在运行",
      freshness: "等待上游",
      label: "等待响应",
    };
  }
  if (quietForMs >= RUN_QUIET_AFTER_MS) {
    return {
      ...status,
      detail: "仍在运行，等待下一条进展",
      freshness: "暂未更新",
    };
  }
  return status;
}

function modelRetrySummary(modelRetry, now) {
  if (!modelRetry) return "";
  const remainingSeconds = Math.max(
    0,
    Math.ceil((Number(modelRetry.retryAt) - now) / 1000),
  );
  return remainingSeconds > 0
    ? `${modelRetry.reason || "模型请求失败"}，${remainingSeconds}秒后重试（${modelRetry.attempt}/${modelRetry.maxRetries}）`
    : `正在重新连接模型（${modelRetry.attempt}/${modelRetry.maxRetries}）`;
}

export function shouldAutoExpandAgentTrace(active = false, statusClassName = "") {
  return Boolean(active || ["failed", "warning"].includes(String(statusClassName || "")));
}

export function buildAgentRunPresentation({ run = null, trace = [], now = Date.now() } = {}) {
  const safeTrace = Array.isArray(trace) ? trace : [];
  const protocolSummary = run?.runSummary && typeof run.runSummary === "object"
    ? run.runSummary
    : null;
  const durableStep = currentRunStep(run);
  const liveStep = currentTraceStep(safeTrace);
  const liveWaitState = traceStepWaitState(liveStep);
  const step = (
    liveWaitState.approval
    || liveWaitState.background
    || liveStep?.status === "running"
  ) ? liveStep : (durableStep || liveStep);
  if (!step) return null;

  const rows = runRows(run, safeTrace);
  const operations = compactRunRows(safeTrace
    .map(buildAgentOperationPresentation)
    .filter(Boolean));
  const visibleOperations = Array.isArray(run?.steps) && run.steps.length
    ? operations
    : [];
  const waitState = traceStepWaitState(step);
  const backgroundPending = hasPendingBackgroundStep(safeTrace);
  const statusRun = protocolSummary?.status
    ? { ...(run || {}), status: protocolSummary.status }
    : run;
  let status = statusPresentation(statusRun, step, waitState, backgroundPending);
  const failedOperationCount = operations.reduce((total, row) => (
    ["failed", "interrupted"].includes(row.status)
      ? total + Math.max(1, Number(row.repeatCount) || 1)
      : total
  ), 0);
  const completedWithWarnings = status.className === "success" && failedOperationCount > 0;
  if (completedWithWarnings) {
    status = {
      className: "warning",
      detail: `任务已完成，${failedOperationCount}个工具调用未成功`,
      freshness: "已保存",
      label: "完成，有警告",
    };
  }
  const active = ["running", "waiting"].includes(status.className);
  const rootStep = safeTrace.find((item) => item.name === "agent_run") || safeTrace[0];
  const startedAt = Date.parse(protocolSummary?.startedAt || run?.startedAt || rootStep?.startedAt || "");
  const finishedAt = Date.parse(protocolSummary?.finishedAt || run?.finishedAt || run?.updatedAt || "");
  const lastActivityAt = latestActivityAt(run, safeTrace, startedAt);
  status = quietRunStatus(status, {
    active,
    lastActivityAt,
    now,
    protectedState: Boolean(
      run?.modelRetry
      || waitState.approval
      || waitState.background
      || backgroundPending
      || status.className === "waiting"
    ),
  });
  const elapsedMs = rootStep?.durationMs != null
    ? rootStep.durationMs
    : Number.isFinite(startedAt)
      ? ((active || !Number.isFinite(finishedAt) ? now : finishedAt) - startedAt)
      : safeTrace.reduce((total, item) => total + (Number(item.durationMs) || 0), 0);
  const progress = runProgress(run, rows);
  const terminalCount = rows.filter((item) => terminalStatuses.has(item.status)).length;
  const protocolTotal = Math.max(0, Number(protocolSummary?.totalSteps) || 0);
  const protocolCompleted = Math.min(
    Math.max(0, Number(protocolSummary?.completedSteps) || 0),
    protocolTotal,
  );
  const completed = protocolTotal
    ? protocolCompleted
    : progress.total ? progress.completed : terminalCount;
  const total = protocolTotal || progress.total || rows.length;
  const estimatedTokenCount = safeTrace.reduce((sum, item) => (
    item.kind === "model"
      ? sum + Math.max(0, Number(parseSummary(item.inputSummary).estimatedTokenCount) || 0)
      : sum
  ), 0);
  const exactTokens = protocolSummary?.totalTokens
    ?? run?.usage?.totalTokens
    ?? run?.usage?.estimatedTokens;
  const tokenLabel = formatTokens(exactTokens || estimatedTokenCount, {
    estimated: !exactTokens && Boolean(estimatedTokenCount),
  });
  const toolCalls = protocolSummary?.toolCalls
    ?? safeTrace.filter((item) => ["tool", "mcp", "sandbox", "workspace"].includes(item.kind)).length;
  const artifacts = Array.isArray(run?.artifacts)
    ? run.artifacts.filter((artifact) => artifact?.artifactType !== "reference")
    : [];
  const activeRow = (
    [...rows].reverse().find((item) => [
      "running", "planning", "waiting", "waiting_approval", "waiting_input",
    ].includes(item.status))
    || [...rows].reverse().find(Boolean)
  );
  const answerRow = [...rows].reverse().find((item) => item.kind === "answer");
  const headline = protocolSummary?.headline || run?.goalSummary || run?.goal_summary || (
    active ? activeRow?.title : answerRow?.title || rows.at(-1)?.title
  ) || run?.phase || "本次任务";
  const progressPercent = total
    ? Math.min(100, Math.round((completed / total) * 100))
    : 0;
  const activeProgress = liveProgressMeta(run?.activeTool || activeRow);
  const processSummary = active
    ? modelRetrySummary(run?.modelRetry, now)
      || status.detail
      || `当前：${activeRow?.title || headline}${activeProgress ? ` · ${activeProgress}` : ""}`
    : completedWithWarnings
      ? status.detail
      : artifacts.length
      ? `已完成并保存${artifacts.length}个产物`
      : `已完成${completed}个步骤`;
  const context = contextPresentation(run);

  return {
    active,
    activeRow,
    artifacts,
    completed,
    context,
    elapsed: formatElapsed(elapsedMs),
    elapsedMs,
    failedOperationCount,
    headline,
    lastActivityAt: Number.isFinite(lastActivityAt) ? new Date(lastActivityAt).toISOString() : "",
    hasPlan: Boolean(Array.isArray(run?.steps) && run.steps.length),
    metrics: [
      formatElapsed(elapsedMs),
      tokenLabel,
      toolCalls ? `${toolCalls}次工具` : "",
      artifacts.length ? `${artifacts.length}个产物` : "",
      total ? `${completed}/${total}` : "",
    ].filter(Boolean).join(" · "),
    processSummary,
    progressPercent,
    operations: visibleOperations.map((row) => ({
      ...row,
      meta: [
        row.repeatCount > 1 ? `${row.repeatCount}次` : "",
        row.outcome,
        row.durationMs == null ? "" : formatElapsed(row.durationMs),
      ].filter(Boolean).join(" · "),
    })),
    rows: rows.map((row) => ({
      ...row,
      meta: (row.operationKey ? [
        row.repeatCount > 1 ? `${row.repeatCount}次` : "",
        row.outcome,
        row.durationMs == null ? "" : formatElapsed(row.durationMs),
      ] : [
        row.repeatCount > 1 ? `${row.repeatCount}次` : "",
        kindLabels[row.kind] || row.kind || "步骤",
        stepStatusLabels[row.status] || row.status,
        liveProgressMeta(row),
        row.durationMs == null ? "" : formatElapsed(row.durationMs),
      ]).filter(Boolean).join(" · "),
    })),
    runId: String(protocolSummary?.runId || run?.id || rootStep?.runId || ""),
    status,
    step,
    tokenLabel,
    toolCalls,
    total,
  };
}
import parseDiff from "parse-diff";

function diffMetaRows(file) {
  const from = String(file?.from || "");
  const to = String(file?.to || "");
  const oldPath = from === "/dev/null" ? from : `a/${from}`;
  const newPath = to === "/dev/null" ? to : `b/${to}`;
  return [
    `diff --git ${oldPath} ${newPath}`,
    `--- ${oldPath}`,
    `+++ ${newPath}`,
  ].map((text) => ({ kind: "meta", oldLine: null, newLine: null, text }));
}

export function buildAgentDiffPresentation(value) {
  const source = String(value || "").slice(0, 500_000);
  if (!source.trim()) return [];
  let files;
  try {
    files = parseDiff(source);
  } catch {
    files = [];
  }
  if (!files.length) {
    return source.split("\n").slice(0, 5000).map((text) => ({
      kind: "meta",
      oldLine: null,
      newLine: null,
      text,
    }));
  }
  return files.flatMap((file) => [
    ...diffMetaRows(file),
    ...(file.chunks || []).flatMap((chunk) => [
      { kind: "hunk", oldLine: null, newLine: null, text: String(chunk.content || "") },
      ...(chunk.changes || []).map((change) => ({
        kind: change.add ? "add" : change.del ? "remove" : "context",
        oldLine: change.add ? null : Number(change.ln1 ?? change.ln) || null,
        newLine: change.del ? null : Number(change.ln2 ?? change.ln) || null,
        text: String(change.content || ""),
      })),
    ]),
  ]).slice(0, 5000);
}
