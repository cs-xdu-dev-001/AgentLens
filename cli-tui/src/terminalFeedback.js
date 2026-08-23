import {useEffect, useRef} from 'react';
import stripAnsi from 'strip-ansi';
import {useStdout} from 'ink';

const OSC = '\u001b]';
const ST = '\u001b\\';
const BEL = '\u0007';
const DEFAULT_NOTIFICATION_DELAY_MS = 6000;

function envDisabled(value) {
  return ['0', 'false', 'no', 'off'].includes(String(value ?? '').trim().toLowerCase());
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
  const safeValue = stripAnsi(String(value ?? ''))
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/gu, '')
    .trim()
    .slice(0, 100_000);
  if (!safeValue) return '';
  return `${OSC}52;c;${Buffer.from(safeValue, 'utf8').toString('base64')}${ST}`;
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

export function terminalFeedbackState({running = false, waiting = false, failed = false, progressPercent} = {}) {
  if (waiting) {
    return {kind: 'waiting', title: 'AgentLens — 等待操作', progressState: 'paused', progressPercent};
  }
  if (running) {
    const progress = Number(progressPercent);
    return {
      kind: 'running',
      title: 'AgentLens — 运行中',
      progressState: Number.isFinite(progress) && progress > 0 ? 'running' : 'indeterminate',
      progressPercent: progress,
    };
  }
  if (failed) {
    return {kind: 'failed', title: 'AgentLens — 执行失败', progressState: 'error', progressPercent: 100};
  }
  return {kind: 'idle', title: 'AgentLens', progressState: 'clear', progressPercent: 0};
}

export function useTerminalFeedback({
  running,
  waiting,
  failed,
  progressPercent,
  runStatus,
  lastInteractionAtRef,
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

    const feedback = terminalFeedbackState({running, waiting, failed, progressPercent});
    const fingerprint = `${feedback.kind}:${Math.round(Number(feedback.progressPercent) || 0)}`;
    if (previousRef.current !== fingerprint) {
      stdout.write(terminalTitleSequence(feedback.title));
      if (supportsTerminalProgress(process.env, stdout.isTTY)) {
        stdout.write(terminalProgressSequence(feedback.progressState, feedback.progressPercent));
      }
      previousRef.current = fingerprint;
    }

    if (
      process.env.NODE_ENV !== 'test'
      && !envDisabled(process.env.KNOWFLOW_CLI_TERMINAL_NOTIFICATIONS)
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
  }, [failed, lastInteractionAtRef, progressPercent, runStatus, running, stdout, waiting]);

  useEffect(() => () => {
    if (!stdout?.isTTY || String(process.env.TERM || '').toLowerCase() === 'dumb') return;
    if (supportsTerminalProgress(process.env, stdout.isTTY)) {
      stdout.write(terminalProgressSequence('clear'));
    }
    stdout.write(terminalTitleSequence('AgentLens'));
  }, [stdout]);
}
