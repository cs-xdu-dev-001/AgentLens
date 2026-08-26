import {EventEmitter} from 'node:events';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import stripAnsi from 'strip-ansi';
import parseDiff from 'parse-diff';

export const PROTOCOL_VERSION = 13;
export const AGENT_EVENT_SCHEMA_VERSION = 1;

export function buildDiffPresentation(value) {
  const source = sanitizeTerminalText(String(value ?? '').slice(0, 500_000));
  if (!source.trim()) return [];
  let files;
  try {
    files = parseDiff(source);
  } catch {
    files = [];
  }
  if (!files.length) {
    return source.split('\n').slice(0, 5000).map(text => ({
      kind: 'meta', oldLine: null, newLine: null, text,
    }));
  }
  return files.flatMap(file => {
    const from = String(file?.from || '');
    const to = String(file?.to || '');
    const oldPath = from === '/dev/null' ? from : `a/${from}`;
    const newPath = to === '/dev/null' ? to : `b/${to}`;
    const metadata = [
      `diff --git ${oldPath} ${newPath}`,
      `--- ${oldPath}`,
      `+++ ${newPath}`,
    ].map(text => ({kind: 'meta', oldLine: null, newLine: null, text}));
    return [
      ...metadata,
      ...(file.chunks || []).flatMap(chunk => [
        {kind: 'hunk', oldLine: null, newLine: null, text: String(chunk.content || '')},
        ...(chunk.changes || []).map(change => ({
          kind: change.add ? 'add' : change.del ? 'remove' : 'context',
          oldLine: change.add ? null : Number(change.ln1 ?? change.ln) || null,
          newLine: change.del ? null : Number(change.ln2 ?? change.ln) || null,
          text: String(change.content || ''),
        })),
      ]),
    ];
  }).slice(0, 5000);
}

const LEGACY_AGENT_EVENT_NAMES = {
  run_started: 'run.started',
  agent_step: 'step.updated',
  tool_started: 'tool.started',
  tool_progress: 'tool.progress',
  tool_result: 'tool.completed',
  tool: 'tool.completed',
  approval_required: 'approval.required',
  approval_resolved: 'approval.resolved',
  approval_submitted: 'approval.resolved',
  user_question_required: 'question.required',
  user_question_resolved: 'question.resolved',
  memory_started: 'memory.started',
  memory_result: 'memory.completed',
  model_retry: 'model.retrying',
  done: 'run.completed',
  cancelled: 'run.cancelled',
  error: 'error.raised',
  answer: 'message.delta',
  message: 'message.delta',
  text_delta: 'message.delta',
  reference: 'artifact.created',
  quality: 'run.quality_updated',
  usage_updated: 'usage.updated',
  context_usage_updated: 'context.usage_updated',
};

export function agentEventName(event) {
  const explicit = String(event?.eventName ?? '').trim();
  if (explicit) return explicit;
  const legacy = String(event?.type ?? '').trim();
  if (legacy === 'agent_step') {
    if (['success', 'succeeded', 'completed'].includes(event?.status)) return 'step.completed';
    if (event?.status === 'failed') return 'step.failed';
    if (event?.status === 'cancelled') return 'step.cancelled';
    if (['waiting', 'waiting_approval'].includes(event?.status)) return 'step.waiting';
  }
  if (['tool_result', 'tool'].includes(legacy)) {
    if (event?.status === 'failed') return 'tool.failed';
    if (event?.status === 'cancelled') return 'tool.cancelled';
  }
  if (legacy === 'memory_result') {
    if (event?.status === 'failed') return 'memory.failed';
    if (event?.status === 'skipped') return 'memory.skipped';
    if (event?.status === 'cancelled') return 'memory.cancelled';
  }
  if (legacy === 'done' && event?.status === 'cancelled') return 'run.cancelled';
  if (['answer', 'message', 'text_delta'].includes(legacy)) {
    return event?.final ? 'message.completed' : 'message.delta';
  }
  return LEGACY_AGENT_EVENT_NAMES[legacy] ?? legacy.replaceAll('_', '.');
}

const RECOVERY_ACTIONS = new Set(['continue', 'retry', 'fix', 'allow_once', 'deny']);
const COMPACTABLE_TASK_KINDS = new Set(['memory', 'mcp', 'model', 'skill', 'tool']);
const COMPACTABLE_TASK_STATUSES = new Set(['completed', 'skipped', 'success', 'succeeded']);

export function compactTaskRows(rows = []) {
  const compacted = [];
  for (const source of Array.isArray(rows) ? rows : []) {
    if (!source || typeof source !== 'object') continue;
    const row = {...source, repeatCount: Math.max(1, Number(source.repeatCount) || 1)};
    const previous = compacted.at(-1);
    const sameOperation = previous
      && COMPACTABLE_TASK_KINDS.has(String(row.kind ?? ''))
      && COMPACTABLE_TASK_STATUSES.has(String(row.status ?? ''))
      && previous.kind === row.kind
      && previous.name === row.name
      && previous.status === row.status;
    const sameTarget = (previous?.operationKey ?? '') === (row.operationKey ?? '');
    if (!sameOperation || !sameTarget) {
      compacted.push(row);
      continue;
    }
    previous.repeatCount += row.repeatCount;
    if (previous.durationMs != null || row.durationMs != null) {
      previous.durationMs = (Number(previous.durationMs) || 0) + (Number(row.durationMs) || 0);
    }
    if (previous.latencyMs != null || row.latencyMs != null) {
      previous.latencyMs = (Number(previous.latencyMs) || 0) + (Number(row.latencyMs) || 0);
    }
    if (previous.elapsedSeconds != null || row.elapsedSeconds != null) {
      previous.elapsedSeconds = (Number(previous.elapsedSeconds) || 0) + (Number(row.elapsedSeconds) || 0);
    }
    for (const field of ['totalLines', 'totalBytes']) {
      if (previous[field] != null || row[field] != null) {
        previous[field] = (Number(previous[field]) || 0) + (Number(row[field]) || 0);
      }
    }
  }
  return compacted;
}

export function createRunProjection(initial = {}) {
  return {
    artifacts: [],
    references: [],
    context: {},
    error: null,
    failedStep: null,
    modelRetry: null,
    phase: '',
    recoveryActions: [],
    runSummary: null,
    usage: {},
    verifications: [],
    ...initial,
  };
}

function runSummaryProjection(event) {
  const source = event?.runSummary;
  if (!source || typeof source !== 'object') return null;
  const runId = sanitizeTerminalText(source.runId ?? event?.runId ?? '').slice(0, 200);
  if (!runId) return null;
  const integer = field => Math.max(0, Number(source[field]) || 0);
  const totalSteps = integer('totalSteps');
  const completedSteps = Math.min(integer('completedSteps'), totalSteps);
  return {
    runId,
    status: sanitizeTerminalText(source.status ?? 'running').slice(0, 40),
    headline: redact(source.headline ?? '', 300),
    startedAt: sanitizeTerminalText(source.startedAt ?? '').slice(0, 80),
    finishedAt: sanitizeTerminalText(source.finishedAt ?? '').slice(0, 80),
    lastActivityAt: sanitizeTerminalText(source.lastActivityAt ?? event?.occurredAt ?? '').slice(0, 80),
    completedSteps,
    totalSteps,
    progressPercent: totalSteps ? Math.min(100, Math.round((completedSteps / totalSteps) * 100)) : 0,
    toolCalls: integer('toolCalls'),
    artifactCount: integer('artifactCount'),
    referenceCount: integer('referenceCount'),
    inputTokens: integer('inputTokens'),
    outputTokens: integer('outputTokens'),
    totalTokens: integer('totalTokens'),
  };
}

const PROTOCOL_VERIFICATION_KINDS = new Set(['build', 'check', 'test']);
const PROTOCOL_VERIFICATION_STATUSES = new Set(['failed', 'passed']);
const PROTOCOL_VERIFICATION_TOOLS = new Set([
  'git_diff_check',
  'lint',
  'npm_build',
  'npm_test',
  'pnpm_build',
  'pnpm_test',
  'project_build',
  'project_test',
  'pytest',
  'python_build',
  'python_check',
  'static_check',
  'typecheck',
  'yarn_build',
  'yarn_test',
]);

const PROTOCOL_ARTIFACT_TYPES = new Set(['file', 'link', 'reference']);
const PROTOCOL_ARTIFACT_OPERATIONS = new Set(['edit', 'write']);

function safeWorkspaceArtifactPath(value) {
  const path = sanitizeTerminalText(value).trim().slice(0, 1000);
  if (!path || path.startsWith('/') || path.includes('\\') || path.includes(':')) return '';
  const parts = path.split('/');
  return parts.some(part => !part || part === '.' || part === '..') ? '' : parts.join('/');
}

export function workspaceChangesToArtifactEvents(changes = []) {
  return (Array.isArray(changes) ? changes : []).flatMap((change, index) => {
    if (!change || typeof change !== 'object') return [];
    const path = safeWorkspaceArtifactPath(change.path);
    if (!path) return [];
    const operation = sanitizeTerminalText(change.operation).trim().toLowerCase();
    const operationId = redact(change.operationId ?? '', 200).trim();
    return [{
      eventName: 'artifact.created',
      artifactId: `file:${path}`,
      artifactType: 'file',
      title: path,
      path,
      ...(PROTOCOL_ARTIFACT_OPERATIONS.has(operation) ? {operation} : {}),
      ...(operationId ? {operationId} : {}),
      addedLines: Math.max(0, Number(change.addedLines ?? change.added) || 0),
      removedLines: Math.max(0, Number(change.removedLines ?? change.removed) || 0),
      diffAvailable: change.diffAvailable !== false,
      reverted: Boolean(change.reverted),
      sequence: Math.max(0, Number(change.sequence) || index + 1),
    }];
  });
}

function artifactProjection(event) {
  const artifactType = redact(
    event?.artifactType ?? (event?.type === 'reference' ? 'reference' : ''),
    40,
  ).trim().toLowerCase();
  if (!PROTOCOL_ARTIFACT_TYPES.has(artifactType)) return null;
  const path = safeWorkspaceArtifactPath(event?.path);
  const url = safeReferenceUrl(event?.url ?? event?.href ?? '');
  const filename = redact(event?.filename ?? '', 300).trim();
  const chunkId = redact(event?.chunkId ?? event?.chunk_id ?? '', 200).trim();
  if (artifactType === 'file' && !path) return null;
  if (artifactType === 'link' && !url) return null;
  if (artifactType === 'reference' && !url && !filename && !chunkId) return null;
  const identity = path || url || `${filename}:${chunkId}`;
  const artifactId = redact(
    event?.artifactId ?? event?.id ?? `${artifactType}:${identity}`,
    300,
  ).trim();
  const artifact = {
    artifactId,
    artifactType,
    title: redact(event?.title ?? '', 300).trim() || filename || path || url,
  };
  if (path) artifact.path = path;
  if (url) artifact.url = url;
  if (filename) artifact.filename = filename;
  if (chunkId) artifact.chunkId = chunkId;
  if (artifactType === 'reference') {
    artifact.displayLabel = redact(event?.displayLabel ?? '', 300).trim()
      || referenceDisplayLabel({filename, url, chunkId});
    artifact.sourceType = url ? 'web' : 'knowledge';
    const documentId = redact(event?.documentId ?? event?.document_id ?? '', 100).trim();
    if (documentId) artifact.documentId = documentId;
    const excerpt = redact(
      event?.excerpt ?? event?.content ?? event?.chunk_text ?? '',
      600,
    ).replace(/\s+/g, ' ').trim().slice(0, 600);
    if (excerpt) artifact.excerpt = excerpt;
  }
  const operation = redact(event?.operation ?? '', 40).trim().toLowerCase();
  if (PROTOCOL_ARTIFACT_OPERATIONS.has(operation)) artifact.operation = operation;
  for (const field of ['addedLines', 'removedLines', 'writtenBytes']) {
    if (event?.[field] != null) artifact[field] = Math.max(0, Number(event[field]) || 0);
  }
  for (const field of ['operationId', 'sourceTool', 'toolCallId', 'changeStatus']) {
    const value = redact(event?.[field] ?? '', 200).trim();
    if (value) artifact[field] = value;
  }
  for (const field of ['diffAvailable', 'reverted']) {
    if (event?.[field] != null) artifact[field] = Boolean(event[field]);
  }
  if (Number.isFinite(Number(event?.score))) {
    artifact.score = Math.max(0, Math.min(1, Number(event.score)));
  }
  return artifact;
}

export function projectRunEvent(current, event) {
  const previous = createRunProjection(current);
  const name = agentEventName(event);
  const clearsModelRetry = Boolean(previous.modelRetry) && (
    name.startsWith('message.')
    || name.startsWith('step.')
    || name.startsWith('tool.')
    || ['run.completed', 'run.cancelled', 'run.failed', 'error.raised'].includes(name)
  );
  const projectable = (
    name.startsWith('run.')
    || name.startsWith('step.')
    || name.startsWith('tool.')
    || name.startsWith('artifact.')
    || name === 'usage.updated'
    || name === 'context.usage_updated'
    || name === 'context.compacted'
    || name === 'model.retrying'
    || name === 'error.raised'
    || clearsModelRetry
    || (Boolean(event?.phase) && !name.startsWith('message.'))
    || Array.isArray(event?.recoveryActions)
  );
  if (!projectable) {
    return current && typeof current === 'object' ? current : previous;
  }
  const next = {...previous};
  if (clearsModelRetry) next.modelRetry = null;
  const runSummary = runSummaryProjection(event);
  if (runSummary) next.runSummary = runSummary;
  if (name.startsWith('step.')) next.phase = sanitizeTerminalText(event?.title ?? event?.name ?? event?.phase ?? previous.phase);
  else if (name.startsWith('tool.')) next.phase = sanitizeTerminalText(event?.toolName ?? event?.phase ?? previous.phase);
  else if (event?.phase && !name.startsWith('context.')) {
    next.phase = sanitizeTerminalText(event.phase);
  }

  if (name === 'usage.updated') {
    const source = event?.usage && typeof event.usage === 'object' ? event.usage : event;
    const value = (camel, snake) => source?.[camel] ?? source?.[snake];
    const usage = {...previous.usage};
    for (const [target, camel, snake] of [
      ['inputTokens', 'inputTokens', 'input_tokens'],
      ['outputTokens', 'outputTokens', 'output_tokens'],
      ['totalTokens', 'totalTokens', 'total_tokens'],
      ['estimatedTokens', 'estimatedTokens', 'estimated_tokens'],
    ]) {
      const tokenCount = value(camel, snake);
      if (tokenCount != null) usage[target] = Math.max(0, Number(tokenCount) || 0);
    }
    if (usage.inputTokens == null) {
      const promptTokens = value('promptTokens', 'prompt_tokens');
      if (promptTokens != null) usage.inputTokens = Math.max(0, Number(promptTokens) || 0);
    }
    if (usage.outputTokens == null) {
      const completionTokens = value('completionTokens', 'completion_tokens');
      if (completionTokens != null) usage.outputTokens = Math.max(0, Number(completionTokens) || 0);
    }
    if (usage.totalTokens == null && (usage.inputTokens != null || usage.outputTokens != null)) {
      usage.totalTokens = (usage.inputTokens || 0) + (usage.outputTokens || 0);
    }
    next.usage = usage;
  }

  if (name === 'model.retrying') {
    const retryInMs = Math.max(0, Number(event?.retryInMs) || 0);
    const attempt = Math.max(1, Number(event?.retryAttempt) || 1);
    const maxRetries = Math.max(attempt, Number(event?.maxRetries) || attempt);
    const rateLimited = Number(event?.statusCode || 0) === 429
      || String(event?.errorType || '').toLowerCase() === 'rate_limit';
    next.modelRetry = {
      attempt,
      maxRetries,
      reason: rateLimited ? '模型限流' : '模型请求失败',
      retryAt: Date.now() + retryInMs,
      retryInMs,
      statusCode: Math.max(0, Number(event?.statusCode) || 0),
    };
  }

  if (name === 'context.usage_updated' || name === 'context.compacted') {
    next.context = {
      ...previous.context,
      ...event,
      ...(name === 'context.compacted' ? {compacted: true} : {}),
    };
  }

  if (name === 'artifact.created' || name === 'artifact.updated') {
    const artifact = artifactProjection(event);
    if (!artifact) return next;
    const identifier = artifact.artifactId;
    const artifactType = artifact.artifactType;
    const collectionName = artifactType === 'reference' ? 'references' : 'artifacts';
    const artifacts = [...previous[collectionName]];
    const index = identifier
      ? artifacts.findIndex(item => String(item?.artifactId ?? item?.id ?? item?.eventId ?? '') === identifier)
      : -1;
    if (index >= 0) artifacts[index] = {...artifacts[index], ...artifact};
    else artifacts.push(artifact);
    next[collectionName] = artifacts;
  }

  if (event?.verification && typeof event.verification === 'object') {
    const kind = sanitizeTerminalText(event.verification.kind ?? '');
    const status = sanitizeTerminalText(event.verification.status ?? '');
    const tool = sanitizeTerminalText(event.verification.tool ?? '');
    if (
      PROTOCOL_VERIFICATION_KINDS.has(kind)
      && PROTOCOL_VERIFICATION_STATUSES.has(status)
      && PROTOCOL_VERIFICATION_TOOLS.has(tool)
    ) {
      const identifier = sanitizeTerminalText(
        event.verification.id ?? event?.toolCallId ?? event?.eventId ?? '',
      ).slice(0, 200);
      const verifications = [...previous.verifications];
      const index = identifier
        ? verifications.findIndex(item => String(item?.id ?? '') === identifier)
        : -1;
      const rawExitCode = event.verification.exitCode;
      const rawDurationMs = event.verification.durationMs;
      const exitCode = rawExitCode === undefined || rawExitCode === null || rawExitCode === ''
        ? null
        : Number(rawExitCode);
      const durationMs = rawDurationMs === undefined || rawDurationMs === null || rawDurationMs === ''
        ? null
        : Number(rawDurationMs);
      const verification = {
        id: identifier,
        kind,
        tool,
        status,
        exitCode: Number.isFinite(exitCode) ? exitCode : null,
        durationMs: Number.isFinite(durationMs) ? Math.max(0, durationMs) : null,
      };
      if (index >= 0) verifications[index] = {...verifications[index], ...verification};
      else verifications.push(verification);
      next.verifications = verifications;
    }
  }

  if (Array.isArray(event?.recoveryActions)) {
    next.recoveryActions = [...new Set(event.recoveryActions.map(String).filter(action => RECOVERY_ACTIONS.has(action)))];
  }
  if (name === 'step.failed') {
    const attemptCount = Math.max(0, Number(event?.attemptCount ?? event?.step?.attemptCount) || 0);
    next.failedStep = {
      id: sanitizeTerminalText(event?.stepId ?? event?.id ?? event?.eventId ?? '').slice(0, 200),
      title: redact(event?.title ?? event?.name ?? event?.step?.title ?? '失败步骤', 240).trim(),
      attemptCount,
    };
  }
  if (name === 'error.raised' || name === 'run.failed' || name === 'step.failed' || name === 'tool.failed') {
    next.error = {
      code: sanitizeTerminalText(event?.error?.code ?? event?.errorCode ?? event?.code ?? 'agent_error'),
      message: redact(event?.error?.message ?? event?.errorMessage ?? event?.message ?? 'Agent运行失败。', 1200),
      retryable: event?.error?.retryable !== false,
    };
  }
  if (name === 'run.completed' || name === 'run.cancelled') {
    next.recoveryActions = [];
    if (name === 'run.completed') {
      next.error = null;
      next.failedStep = null;
    }
  }
  return next;
}

export function sanitizeTerminalText(value) {
  return stripAnsi(String(value ?? '')).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '');
}

function safeReferenceUrl(value) {
  const source = sanitizeTerminalText(value).trim();
  if (!/^https?:\/\//i.test(source)) return '';
  try {
    const url = new URL(source);
    return `${url.origin}${url.pathname}`;
  } catch {
    return '';
  }
}

export function referenceDisplayLabel(reference, fallback = '引用来源') {
  const displayLabel = redact(reference?.displayLabel ?? '', 300).trim();
  if (displayLabel) return displayLabel;
  const filename = sanitizeTerminalText(reference?.filename ?? reference?.title ?? '').trim();
  if (filename && filename !== '运行产物') {
    const safeFilenameUrl = safeReferenceUrl(filename);
    if (!safeFilenameUrl) return filename.slice(0, 120);
    try {
      const parsed = new URL(safeFilenameUrl);
      const path = parsed.pathname === '/' ? '' : parsed.pathname.replace(/\/$/, '');
      return `${parsed.hostname}${path}`.slice(0, 120);
    } catch {
      return fallback;
    }
  }
  const url = safeReferenceUrl(reference?.url ?? reference?.href ?? '');
  if (url) {
    try {
      const parsed = new URL(url);
      const path = parsed.pathname === '/' ? '' : parsed.pathname.replace(/\/$/, '');
      return `${parsed.hostname}${path}`.slice(0, 120);
    } catch {
      return fallback;
    }
  }
  const chunkId = sanitizeTerminalText(reference?.chunkId ?? reference?.chunk_id ?? '').trim();
  return chunkId ? `片段 #${chunkId.slice(0, 40)}` : fallback;
}

const SECRET_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[已隐藏私钥]'],
  [/\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b/g, '[已隐藏]'],
  [/\b((?:org|proj)-)[A-Za-z0-9_-]{8,}\b/g, '$1[已隐藏]'],
  [/\bBearer\s+[A-Za-z0-9._~-]{8,}\b/gi, 'Bearer [已隐藏]'],
  [/(api[_-]?key|token|password|secret|cookie|authorization|private[_-]?key)(\s*[:=]\s*)\S+/gi, '$1$2[已隐藏]'],
  [/(--(?:api[-_]?key|token|password|secret|cookie|authorization|private[-_]?key))(?:=|\s+)\S+/gi, '$1=[已隐藏]'],
  [/([a-z][a-z0-9+.-]*:\/\/[^:\s/]+:)[^@\s/]+@/gi, '$1[已隐藏]@'],
];

export function redact(value, limit = 500) {
  let text = sanitizeTerminalText(value);
  for (const [pattern, replacement] of SECRET_PATTERNS) text = text.replace(pattern, replacement);
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export function userFacingErrorMessage(value, fallback = '执行失败。') {
  const text = redact(value, 1200).trim();
  if (!text) return fallback;
  if (/\b(?:http\s*)?429\b|rate[_ -]?limit|max\s+rpm/i.test(text)) {
    return '上游模型请求过于频繁（HTTP 429），自动重试后仍未恢复。';
  }
  return text;
}

const OPERATION_KINDS = new Set(['approval', 'memory', 'mcp', 'sandbox', 'skill', 'tool', 'workspace']);
const OPERATION_VERBS = {
  activate_skill: '激活',
  list_workspace: '查看工作区',
  memory_recall: '召回记忆',
  memory_write: '整理记忆',
  read_workspace_file: '读取',
  run_sandbox_command: '运行',
  tool_search: '查找工具',
  web_fetch: '读取网页',
  web_search: '搜索',
  write_workspace_file: '更新',
};

function publicSummary(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value;
  if (typeof value !== 'string') return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function operationText(value, limit = 84) {
  if (!['string', 'number', 'boolean'].includes(typeof value)) return '';
  return redact(String(value).replace(/\s+/g, ' ').trim(), limit);
}

function operationUrl(value) {
  const text = operationText(value, 300);
  if (!text) return '';
  try {
    const url = new URL(text);
    return operationText(`${url.hostname}${url.pathname === '/' ? '' : url.pathname.replace(/\/$/, '')}`);
  } catch {
    return operationText(text.split(/[?#]/, 1)[0]);
  }
}

export function taskOperationRow(source) {
  if (!source || typeof source !== 'object') return null;
  const kind = String(source.kind ?? '');
  if (!OPERATION_KINDS.has(kind)) return null;
  const name = String(source.name ?? kind ?? 'tool');
  const status = String(source.status ?? 'running');
  const input = publicSummary(source.inputSummary ?? source.arguments);
  const output = publicSummary(source.outputSummary ?? source.output);
  const details = source.details && typeof source.details === 'object' ? source.details : {};
  let target = '';
  if (name === 'web_fetch') target = operationUrl(input.url ?? input.href);
  else if (name === 'web_search') target = operationText(input.query ?? input.q);
  else if (name === 'run_sandbox_command') target = operationText(input.command ?? input.cmd, 100);
  else if (name === 'activate_skill' || kind === 'skill') {
    target = operationText(details.displayName ?? input.skillName ?? input.skill_id ?? input.name);
  } else if (kind === 'mcp') {
    target = operationText(input.page_id ?? input.database_id ?? input.path ?? details.serverName);
  } else target = operationText(input.path ?? input.target ?? input.filename);
  const verb = OPERATION_VERBS[name]
    ?? (kind === 'approval' ? '确认' : kind === 'mcp' ? '调用' : kind === 'skill' ? '激活' : '执行');
  const visibleTarget = target || (
    !OPERATION_VERBS[name] && !['approval', 'skill'].includes(kind)
      ? operationText(name.replaceAll('_', ' '))
      : ''
  );
  const running = ['planning', 'running', 'waiting'].includes(status);
  const failed = ['failed', 'error', 'interrupted'].includes(status);
  const title = kind === 'approval'
    ? failed ? '操作确认失败' : running ? '等待操作确认' : '操作已确认'
    : failed
      ? `${verb}${visibleTarget ? ` ${visibleTarget}` : ''}失败`
      : running
        ? `正在${verb}${visibleTarget ? ` ${visibleTarget}` : ''}`
        : `已${verb}${visibleTarget ? ` ${visibleTarget}` : ''}`;
  const outcome = [];
  const resultCount = output.resultCount ?? (Array.isArray(output.results) ? output.results.length : null);
  const entries = Array.isArray(output.entries) ? output.entries.length : output.entries;
  const writtenBytes = Number(output.writtenBytes ?? output.written_bytes);
  if (resultCount != null) outcome.push(`${Math.max(0, Number(resultCount) || 0)}个结果`);
  if (entries != null) outcome.push(`${Math.max(0, Number(entries) || 0)}个条目`);
  if (Number.isFinite(writtenBytes) && writtenBytes > 0) outcome.push(`${writtenBytes}B`);
  if (output.exit_code != null) outcome.push(`退出码${output.exit_code}`);
  if (source.errorCode) outcome.push(operationText(source.errorCode, 80));
  return {
    id: String(source.id ?? source.stepId ?? `${kind}-${name}-${visibleTarget}`),
    toolCallId: String(source.toolCallId ?? details.toolCallId ?? ''),
    durationMs: source.durationMs ?? null,
    elapsedSeconds: source.elapsedSeconds,
    latencyMs: source.latencyMs,
    kind,
    name,
    operationKey: `${kind}:${name}:${visibleTarget}`,
    outcome: outcome.join(' · '),
    repeatCount: Math.max(1, Number(source.repeatCount) || 1),
    status,
    target: visibleTarget,
    title,
    totalBytes: source.totalBytes,
    totalLines: source.totalLines,
  };
}

const VERIFICATION_STATUSES = new Set([
  'cancelled',
  'completed',
  'error',
  'failed',
  'interrupted',
  'success',
  'succeeded',
]);

const VERIFICATION_RULES = [
  {label: '测试', tool: 'pytest', pattern: /\b(?:pytest|python(?:\d+(?:\.\d+)?)?\s+-m\s+pytest)\b/i},
  {label: '测试', tool: 'Python检查', pattern: /\btests[\\/]check_[^\s"']+\.py\b/i},
  {label: '测试', tool: 'npm test', pattern: /\bnpm\s+(?:run\s+)?test\b/i},
  {label: '测试', tool: 'pnpm test', pattern: /\bpnpm\s+(?:run\s+)?test\b/i},
  {label: '测试', tool: 'yarn test', pattern: /\byarn\s+test\b/i},
  {label: '测试', tool: '项目测试', pattern: /\b(?:vitest|jest|unittest|cargo\s+test|go\s+test|dotnet\s+test)\b/i},
  {label: '构建', tool: 'npm run build', pattern: /\bnpm\s+run\s+build\b/i},
  {label: '构建', tool: 'pnpm build', pattern: /\bpnpm\s+(?:run\s+)?build\b/i},
  {label: '构建', tool: 'yarn build', pattern: /\byarn\s+build\b/i},
  {label: '构建', tool: 'Python构建', pattern: /\bpython(?:\d+(?:\.\d+)?)?\s+-m\s+build\b/i},
  {label: '构建', tool: '项目构建', pattern: /\b(?:vite\s+build|cargo\s+build|go\s+build|mvn\b[^\r\n]*\bpackage|gradle\b[^\r\n]*\bbuild)\b/i},
  {label: '差异检查', tool: 'git diff --check', pattern: /\bgit\s+diff\s+--check\b/i},
  {label: '代码检查', tool: 'lint', pattern: /\b(?:npm|pnpm|yarn)\s+(?:run\s+)?lint\b/i},
  {label: '类型检查', tool: 'typecheck', pattern: /\b(?:(?:npm|pnpm|yarn)\s+(?:run\s+)?typecheck|tsc\s+--noEmit)\b/i},
  {label: '代码检查', tool: '静态检查', pattern: /\b(?:ruff|mypy|flake8|eslint|prettier\s+--check)\b/i},
];

const VERIFICATION_KIND_LABELS = {build: '构建', check: '代码检查', test: '测试'};
const VERIFICATION_TOOL_LABELS = {
  git_diff_check: 'git diff --check',
  lint: 'lint',
  npm_build: 'npm run build',
  npm_test: 'npm test',
  pnpm_build: 'pnpm build',
  pnpm_test: 'pnpm test',
  project_build: '项目构建',
  project_test: '项目测试',
  pytest: 'pytest',
  python_build: 'Python构建',
  python_check: 'Python检查',
  static_check: '静态检查',
  typecheck: 'typecheck',
  yarn_build: 'yarn build',
  yarn_test: 'yarn test',
};

export function verificationToolCallId(verification) {
  const identifier = sanitizeTerminalText(verification?.id ?? '').slice(0, 200);
  return identifier.startsWith('verification:')
    ? identifier.slice('verification:'.length)
    : identifier;
}

export function defaultTaskNavigationIndex(items, {running = false} = {}) {
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) return 0;
  const urgent = rows.findIndex(item => (
    ['failed', 'error', 'running', 'planning', 'waiting'].includes(item?.row?.status)
  ));
  if (urgent >= 0) return urgent;
  if (!running) {
    const delivery = rows.findIndex(item => item?.type === 'artifact');
    if (delivery >= 0) return delivery;
    const evidence = rows.findIndex(item => item?.type === 'reference');
    if (evidence >= 0) return evidence;
  }
  return 0;
}

export function verificationRows(rows = [], protocolVerifications = []) {
  const projected = (Array.isArray(protocolVerifications) ? protocolVerifications : []).flatMap((item, index) => {
    if (!item || typeof item !== 'object' || !['failed', 'passed'].includes(String(item.status ?? ''))) return [];
    const kind = sanitizeTerminalText(item.kind ?? 'check');
    const tool = sanitizeTerminalText(item.tool ?? '');
    const rawExitCode = item.exitCode;
    const exitCode = rawExitCode === undefined || rawExitCode === null || rawExitCode === ''
      ? null
      : Number(rawExitCode);
    return [{
      id: sanitizeTerminalText(item.id ?? `verification-${index}`),
      durationMs: Number.isFinite(Number(item.durationMs)) ? Math.max(0, Number(item.durationMs)) : null,
      exitCode: Number.isFinite(exitCode) ? exitCode : null,
      label: tool === 'git_diff_check' ? '差异检查' : VERIFICATION_KIND_LABELS[kind] ?? '代码检查',
      status: String(item.status),
      statusLabel: item.status === 'failed' ? '失败' : '通过',
      tool: VERIFICATION_TOOL_LABELS[tool] ?? '项目检查',
    }];
  });
  if (projected.length) return projected;
  return (Array.isArray(rows) ? rows : []).flatMap((source, index) => {
    if (String(source?.name ?? '') !== 'run_sandbox_command') return [];
    const status = String(source?.status ?? '').toLowerCase();
    if (!VERIFICATION_STATUSES.has(status)) return [];
    const input = publicSummary(source?.inputSummary ?? source?.arguments);
    const command = operationText(input.command ?? input.cmd, 1000);
    const rule = VERIFICATION_RULES.find(item => item.pattern.test(command));
    if (!rule) return [];
    const output = publicSummary(source?.outputSummary ?? source?.output);
    const rawExitCode = output.exit_code ?? output.exitCode ?? source?.exitCode;
    const exitCode = rawExitCode === undefined || rawExitCode === null || rawExitCode === ''
      ? null
      : Number(rawExitCode);
    const failed = ['cancelled', 'error', 'failed', 'interrupted'].includes(status)
      || (Number.isFinite(exitCode) && exitCode !== 0);
    return [{
      id: String(source?.id ?? source?.stepId ?? `verification-${index}`),
      durationMs: source?.durationMs ?? null,
      exitCode: Number.isFinite(exitCode) ? exitCode : null,
      label: rule.label,
      status: failed ? 'failed' : 'passed',
      statusLabel: failed ? '失败' : '通过',
      tool: rule.tool,
    }];
  });
}

export class RuntimeClient extends EventEmitter {
  constructor({python, config}) {
    super();
    this.python = python;
    this.config = config;
    this.child = null;
    this.stderr = [];
  }

  start() {
    if (this.child) return;
    this.child = spawn(this.python, [
      '-m',
      'knowflow.tui.ink_bridge',
      '--config',
      JSON.stringify(this.config),
    ], {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: process.env,
    });
    const lines = createInterface({input: this.child.stdout});
    lines.on('line', line => {
      if (!String(line ?? '').trim()) return;
      try {
        const event = JSON.parse(line);
        if (event && typeof event === 'object') this.emit('message', event);
      } catch {
        this.emit('message', {
          type: 'protocol_error',
          message: `Python运行时返回了非JSON事件：${redact(line, 300) || '空行'}`,
          stderr: [...this.stderr],
          hint: '运行agentlens doctor --cli检查本地运行环境；如果刚更新过，请重新打开终端后再试。',
        });
      }
    });
    this.child.stderr.on('data', chunk => {
      const lines = redact(chunk, 2000).split(/\r?\n/).filter(Boolean);
      this.stderr.push(...lines);
      this.stderr = this.stderr.slice(-5);
    });
    this.child.on('error', error => {
      this.emit('message', {type: 'startup_failed', message: redact(error.message)});
    });
    this.child.on('exit', code => {
      this.emit('exit', {
        code: Number(code ?? 1),
        detail: this.stderr.at(-1) ?? '',
      });
      this.child = null;
    });
  }

  send(message) {
    if (!this.child?.stdin?.writable) return false;
    this.child.stdin.write(`${JSON.stringify(message)}\n`);
    return true;
  }

  close() {
    if (!this.child) return;
    this.send({type: 'shutdown'});
    const child = this.child;
    setTimeout(() => {
      if (child.exitCode === null) child.kill('SIGTERM');
    }, 500).unref();
  }
}
