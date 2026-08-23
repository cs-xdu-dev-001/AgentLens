import {useEffect, useRef} from 'react';
import stripAnsi from 'strip-ansi';
import {useStdout} from 'ink';

const OSC = '\u001b]';
const ST = '\u001b\\';

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

export function useTerminalFeedback({running, waiting, failed, progressPercent}) {
  const {stdout} = useStdout();
  const previousRef = useRef('');

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
      stdout.write(terminalProgressSequence(feedback.progressState, feedback.progressPercent));
      previousRef.current = fingerprint;
    }

    return undefined;
  }, [failed, progressPercent, running, stdout, waiting]);

  useEffect(() => () => {
    if (!stdout?.isTTY || String(process.env.TERM || '').toLowerCase() === 'dumb') return;
    stdout.write(terminalProgressSequence('clear'));
    stdout.write(terminalTitleSequence('AgentLens'));
  }, [stdout]);
}
