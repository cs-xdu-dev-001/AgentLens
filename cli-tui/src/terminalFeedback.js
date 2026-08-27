import {useEffect, useRef} from 'react';
import stripAnsi from 'strip-ansi';
import {useStdout} from 'ink';
import {redact} from './protocol.js';

const OSC = '\u001b]';
const ST = '\u001b\\';
const BEL = '\u0007';
const DEFAULT_NOTIFICATION_DELAY_MS = 6000;
const COPY_TEXT_LIMIT = 100_000;

function envDisabled(value) {
  return ['0', 'false', 'no', 'off'].includes(String(value ?? '').trim().toLowerCase());
}

export function terminalNotificationsEnabled(environment = process.env) {
  if (Object.hasOwn(environment, 'AGENTLENS_CLI_TERMINAL_NOTIFICATIONS')) {
    return !envDisabled(environment.AGENTLENS_CLI_TERMINAL_NOTIFICATIONS);
  }
  return !envDisabled(environment.KNOWFLOW_CLI_TERMINAL_NOTIFICATIONS);
}

export function sanitizeTerminalTitle(value) {
  return stripAnsi(String(value ?? ''))
    .replace(/[\u0000-\u001f\u007f-\u009f]/gu, '')
    .trim()
    .slice(0, 80);
}

export function terminalTitleSequence(title) {
  return `${OSC}0;${sanitizeTerminalTitle(title) || 'AgentLens'}${ST}`;
}

export function terminalClipboardSequence(value) {
  const safeValue = redact(String(value ?? ''), 100_000)
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/gu, '')
    .trim()
    .slice(0, 100_000);
  if (!safeValue) return '';
  return `${OSC}52;c;${Buffer.from(safeValue, 'utf8').toString('base64')}${ST}`;
}

function copyValue(value, limit = 12_000) {
  if (value === undefined || value === null || value === '') return '';
  const source = typeof value === 'string' ? value : (() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  })();
  return redact(source, limit).trim();
}

function copyToolRow(row, index = 0) {
  const name = copyValue(row?.name || row?.toolName || row?.details?.toolName || '工具调用', 160) || '工具调用';
  const status = copyValue(row?.status || 'running', 80) || 'running';
  const lines = [`[${status}] ${name}`];
  const fields = [
    ['输入', row?.arguments || row?.inputSummary || row?.inputJson || row?.input_json],
    ['输出', row?.output || row?.outputSummary || row?.details?.output],
    ['stdout', row?.stdout || row?.details?.stdout],
    ['stderr', row?.stderr || row?.details?.stderr],
    ['错误', row?.errorMessage || row?.errorCode],
  ];
  for (const [label, value] of fields) {
    const text = copyValue(value);
    if (text) lines.push(`${label}:\n${text}`);
  }
  const elapsedSeconds = row?.elapsedSeconds ?? (
    row?.durationMs !== undefined && row?.durationMs !== null
      ? Number(row.durationMs) / 1000
      : undefined
  );
  if (elapsedSeconds !== undefined && elapsedSeconds !== null && Number.isFinite(Number(elapsedSeconds))) {
    lines.push(`耗时: ${copyValue(elapsedSeconds, 40)}s`);
  }
  return `${index + 1}. ${lines.join('\n')}`;
}

const TOOL_TRACE_KINDS = new Set(['tool', 'mcp', 'sandbox', 'workspace']);
const TOOL_TRACE_NAMES = new Set([
  'web_search',
  'web_fetch',
  'run_sandbox_command',
  'list_workspace',
  'read_workspace_file',
  'write_workspace_file',
]);

function isToolTraceRow(row) {
  const kind = String(row?.kind || '').trim().toLowerCase();
  const name = String(row?.name || row?.toolName || '').trim().toLowerCase();
  return TOOL_TRACE_KINDS.has(kind) || TOOL_TRACE_NAMES.has(name);
}

function rowIdentityKeys(row) {
  return [row?.toolCallId, row?.id]
    .map(value => String(value ?? '').trim())
    .filter(Boolean);
}

function rowNameKey(row) {
  return String(row?.name || row?.toolName || '').trim().toLowerCase();
}

function toolRowsForContext(context = {}) {
  const activityRows = Array.isArray(context?.toolRows) ? context.toolRows.filter(Boolean) : [];
  const traceRows = Array.isArray(context?.traceRows)
    ? context.traceRows.filter(isToolTraceRow)
    : [];
  if (!traceRows.length) return activityRows;
  const activityByKey = new Map();
  const activitiesByName = new Map();
  activityRows.forEach(row => rowIdentityKeys(row).forEach(key => {
    if (!activityByKey.has(key)) activityByKey.set(key, row);
  }));
  activityRows.forEach(row => {
    const name = rowNameKey(row);
    if (!name) return;
    const rows = activitiesByName.get(name) || [];
    rows.push(row);
    activitiesByName.set(name, rows);
  });
  const usedActivities = new Set();
  const merged = traceRows.map(row => {
    const activity = rowIdentityKeys(row).map(key => activityByKey.get(key)).find(value => value && !usedActivities.has(value))
      || (() => {
        const candidates = activitiesByName.get(rowNameKey(row)) || [];
        return candidates.length === 1 && !usedActivities.has(candidates[0]) ? candidates[0] : null;
      })();
    if (activity) usedActivities.add(activity);
    return activity ? {...activity, ...row} : row;
  });
  activityRows.forEach(row => {
    if (!usedActivities.has(row)) {
      merged.push(row);
    }
  });
  return merged;
}

function boundedCopyJoin(items, format, separator = '\n\n', limit = COPY_TEXT_LIMIT) {
  const chunks = [];
  let used = 0;
  let truncated = false;
  for (let index = 0; index < items.length; index += 1) {
    const value = String(format(items[index], index) ?? '').trim();
    if (!value) continue;
    const prefix = chunks.length ? separator : '';
    const available = Math.max(0, limit - used - prefix.length);
    if (value.length > available) {
      const marker = '\n[内容已截断]';
      const visible = value.slice(0, Math.max(0, available - marker.length));
      chunks.push(`${prefix}${visible}${marker}`.slice(0, Math.max(0, limit - used)));
      truncated = true;
      break;
    }
    chunks.push(`${prefix}${value}`);
    used += prefix.length + value.length;
  }
  return {text: chunks.join(''), truncated};
}

function copyTranscriptItem(item, index) {
  const role = {
    user: '用户',
    assistant: 'Agent',
    assistant_chunk: 'Agent（流式）',
    error: '错误',
    task_summary: '任务过程',
    delivery_summary: '交付摘要',
  }[item?.role] || copyValue(item?.role || '消息', 80);
  const content = copyValue(item?.content, 20_000);
  if (content) return `${index + 1}. ${role}:\n${content}`;
  if (item?.role === 'task_summary') {
    const entries = Array.isArray(item.activities) ? item.activities : [];
    const activityRows = entries.map(entry => Array.isArray(entry) ? entry[1] : entry);
    const traceRows = Array.isArray(item.traceSteps)
      ? item.traceSteps.map(entry => Array.isArray(entry) ? entry[1] : entry).filter(isToolTraceRow)
      : [];
    const rows = toolRowsForContext({toolRows: activityRows, traceRows});
    const process = rows.length
      ? boundedCopyJoin(rows, copyToolRow, '\n', 20_000).text
      : '暂无工具调用记录';
    return `${index + 1}. ${role}:\n${process}`;
  }
  if (item?.role === 'delivery_summary') {
    const artifacts = Array.isArray(item.artifacts) ? item.artifacts : [];
    const verifications = Array.isArray(item.verifications) ? item.verifications : [];
    const details = [
      artifacts.length ? `产物: ${copyValue(artifacts, 12_000)}` : '',
      verifications.length ? `验证: ${copyValue(verifications, 12_000)}` : '',
    ].filter(Boolean).join('\n');
    return details ? `${index + 1}. ${role}:\n${details}` : '';
  }
  return '';
}

export function terminalCopySelection(answer, args = '', context = {}) {
  const parts = String(args ?? '').trim().toLowerCase().split(/\s+/u).filter(Boolean);
  const mode = parts[0] || 'answer';
  if (mode === 'tool') {
    if (parts.length > 2 || (parts[1] && parts[1] !== 'all' && !/^\d+$/u.test(parts[1]))) {
      return {ok: false, message: '用法：/copy tool [序号|all]'};
    }
    const rows = toolRowsForContext(context);
    if (!rows.length) return {ok: false, message: '当前运行还没有可复制的工具输出。'};
    const requested = parts[1] && parts[1] !== 'all' ? Number(parts[1]) : rows.length;
    if (!Number.isInteger(requested) || requested < 1 || requested > rows.length) {
      return {ok: false, message: `当前共有${rows.length}条工具记录，请输入1-${rows.length}或all。`};
    }
    const selected = parts[1] === 'all'
      ? rows
      : [rows[requested - 1]];
    const output = boundedCopyJoin(
      selected,
      (row, index) => copyToolRow(row, parts[1] === 'all' ? index : requested - 1),
    );
    return {
      ok: true,
      label: `${parts[1] === 'all' ? `全部工具输出（${rows.length}项）` : `工具输出${requested}/${rows.length}`}${output.truncated ? '，已截断' : ''}`,
      text: output.text,
    };
  }
  if (mode === 'transcript') {
    if (parts.length > 1) return {ok: false, message: '用法：/copy transcript'};
    const items = Array.isArray(context.transcript) ? context.transcript : [];
    const assistant = copyValue(context.assistant, 20_000);
    const copyItems = [...items];
    if (assistant && !items.some(item => item?.role === 'assistant' && copyValue(item?.content, 20_000) === assistant)) {
      copyItems.push({role: 'assistant', content: assistant});
    }
    const output = boundedCopyJoin(copyItems, copyTranscriptItem);
    if (!output.text) return {ok: false, message: '当前会话还没有可复制的记录。'};
    return {ok: true, label: `当前会话记录${output.truncated ? '（已截断）' : ''}`, text: output.text};
  }
  const source = redact(stripAnsi(String(answer ?? '')).trim(), 100_000);
  if (!source) return {ok: false, message: '还没有可复制的Agent回答。'};
  if (mode === 'answer' && parts.length <= 1) {
    return {ok: true, label: '最近回答', text: source};
  }
  if (mode !== 'code' || parts.length > 2) {
    return {ok: false, message: '用法：/copy、/copy answer、/copy code [序号]、/copy tool [序号|all]或/copy transcript'};
  }
  const blocks = [];
  const pattern = /(?:^|\n)(`{3,}|~{3,})[^\n]*\n([\s\S]*?)\n\1(?=\n|$)/gu;
  for (const match of source.matchAll(pattern)) {
    const value = String(match[2] ?? '').trimEnd();
    if (value) blocks.push(value);
  }
  if (!blocks.length) {
    return {ok: false, message: '最近回答中没有代码块。'};
  }
  const requested = parts[1] ? Number(parts[1]) : blocks.length;
  if (!Number.isInteger(requested) || requested < 1 || requested > blocks.length) {
    return {ok: false, message: `最近回答中共有${blocks.length}个代码块，请输入1-${blocks.length}。`};
  }
  return {
    ok: true,
    label: `代码块${requested}/${blocks.length}`,
    text: blocks[requested - 1],
  };
}

function versionAtLeast(value, minimum) {
  const current = String(value ?? '').match(/\d+/gu)?.map(Number) ?? [];
  const target = String(minimum).match(/\d+/gu)?.map(Number) ?? [];
  for (let index = 0; index < Math.max(current.length, target.length); index += 1) {
    const left = current[index] ?? 0;
    const right = target[index] ?? 0;
    if (left !== right) return left > right;
  }
  return true;
}

export function supportsTerminalProgress(environment = process.env, stdoutIsTTY = true) {
  if (!stdoutIsTTY || environment.WT_SESSION) return false;
  if (environment.ConEmuANSI || environment.ConEmuPID || environment.ConEmuTask) return true;
  const program = String(environment.TERM_PROGRAM ?? '').toLowerCase();
  if (program === 'ghostty') return versionAtLeast(environment.TERM_PROGRAM_VERSION, '1.2.0');
  if (program === 'iterm.app') return versionAtLeast(environment.TERM_PROGRAM_VERSION, '3.6.6');
  return false;
}

export function terminalProgressSequence(state, percentage = 0) {
  const code = {
    clear: 0,
    running: 1,
    error: 2,
    indeterminate: 3,
    paused: 4,
  }[state] ?? 0;
  const progress = Math.max(0, Math.min(100, Math.round(Number(percentage) || 0)));
  return `${OSC}9;4;${code};${progress}${ST}`;
}

export function terminalNotificationSequence({title = 'AgentLens', message = '任务状态已更新'} = {}, environment = process.env) {
  const safeTitle = sanitizeTerminalTitle(title) || 'AgentLens';
  const safeMessage = sanitizeTerminalTitle(message) || '任务状态已更新';
  const program = String(environment.TERM_PROGRAM ?? '').toLowerCase();
  if (program === 'iterm.app') return `${OSC}9;\n\n${safeTitle}:\n${safeMessage}${BEL}`;
  if (program === 'kitty' || environment.KITTY_WINDOW_ID) {
    return `${OSC}99;i=4207:d=0:p=title;${safeTitle}${ST}${OSC}99;i=4207:p=body;${safeMessage}${ST}${OSC}99;i=4207:d=1:a=focus;${ST}`;
  }
  if (program === 'ghostty') return `${OSC}777;notify;${safeTitle};${safeMessage}${BEL}`;
  return BEL;
}

export function shouldNotifyTerminalTransition({
  previousKind,
  nextKind,
  runStatus = '',
  lastInteractionAt = 0,
  now = Date.now(),
  thresholdMs = DEFAULT_NOTIFICATION_DELAY_MS,
} = {}) {
  if (!previousKind || now - Number(lastInteractionAt || 0) < thresholdMs) return false;
  if (nextKind === 'waiting' && previousKind !== 'waiting') return true;
  if (nextKind === 'failed' && previousKind !== 'failed') return true;
  const status = String(runStatus ?? '').trim().toLowerCase();
  return previousKind === 'running'
    && nextKind === 'idle'
    && ['completed', 'success', 'succeeded'].includes(status);
}

function terminalNotificationForTransition(nextKind) {
  if (nextKind === 'waiting') return 'Agent需要你的操作';
  if (nextKind === 'failed') return '任务执行失败';
  return '任务已完成';
}

function terminalFeedbackTitle(kind, contextLabel = '') {
  const context = sanitizeTerminalTitle(contextLabel).slice(0, 36);
  const base = context ? `${context} — AgentLens` : 'AgentLens';
  const suffix = {
    connecting: '正在连接',
    unavailable: '未连接',
    running: '运行中',
    waiting: '等待操作',
    failed: '执行失败',
  }[kind];
  return suffix ? `${base} — ${suffix}` : base;
}

export function terminalFeedbackState({
  ready = true,
  connecting = false,
  running = false,
  waiting = false,
  failed = false,
  progressPercent,
  contextLabel = '',
} = {}) {
  if (waiting) {
    return {kind: 'waiting', title: terminalFeedbackTitle('waiting', contextLabel), progressState: 'paused', progressPercent};
  }
  if (running) {
    const progress = Number(progressPercent);
    return {
      kind: 'running',
      title: terminalFeedbackTitle('running', contextLabel),
      progressState: Number.isFinite(progress) && progress > 0 ? 'running' : 'indeterminate',
      progressPercent: progress,
    };
  }
  if (failed) {
    return {kind: 'failed', title: terminalFeedbackTitle('failed', contextLabel), progressState: 'error', progressPercent: 100};
  }
  if (!ready) {
    const kind = connecting ? 'connecting' : 'unavailable';
    return {
      kind,
      title: terminalFeedbackTitle(kind, contextLabel),
      progressState: connecting ? 'indeterminate' : 'clear',
      progressPercent: 0,
    };
  }
  return {kind: 'idle', title: terminalFeedbackTitle('idle', contextLabel), progressState: 'clear', progressPercent: 0};
}

export function useTerminalFeedback({
  ready,
  connecting,
  running,
  waiting,
  failed,
  progressPercent,
  runStatus,
  lastInteractionAtRef,
  contextLabel,
  notificationsEnabled,
}) {
  const {stdout} = useStdout();
  const previousRef = useRef('');
  const previousKindRef = useRef(null);

  useEffect(() => {
    if (
      !stdout?.isTTY
      || String(process.env.TERM || '').toLowerCase() === 'dumb'
      || envDisabled(process.env.KNOWFLOW_CLI_TERMINAL_FEEDBACK)
    ) return undefined;

    const feedback = terminalFeedbackState({ready, connecting, running, waiting, failed, progressPercent, contextLabel});
    const fingerprint = `${feedback.title}:${feedback.kind}:${Math.round(Number(feedback.progressPercent) || 0)}`;
    if (previousRef.current !== fingerprint) {
      stdout.write(terminalTitleSequence(feedback.title));
      if (supportsTerminalProgress(process.env, stdout.isTTY)) {
        stdout.write(terminalProgressSequence(feedback.progressState, feedback.progressPercent));
      }
      previousRef.current = fingerprint;
    }

    if (
      process.env.NODE_ENV !== 'test'
      && (notificationsEnabled ?? terminalNotificationsEnabled(process.env))
      && shouldNotifyTerminalTransition({
        previousKind: previousKindRef.current,
        nextKind: feedback.kind,
        runStatus,
        lastInteractionAt: lastInteractionAtRef?.current,
      })
    ) {
      stdout.write(terminalNotificationSequence({
        message: terminalNotificationForTransition(feedback.kind),
      }));
    }
    previousKindRef.current = feedback.kind;

    return undefined;
  }, [connecting, contextLabel, failed, lastInteractionAtRef, notificationsEnabled, progressPercent, ready, runStatus, running, stdout, waiting]);

  useEffect(() => () => {
    if (!stdout?.isTTY || String(process.env.TERM || '').toLowerCase() === 'dumb') return;
    if (supportsTerminalProgress(process.env, stdout.isTTY)) {
      stdout.write(terminalProgressSequence('clear'));
    }
    stdout.write(terminalTitleSequence('AgentLens'));
  }, [stdout]);
}
