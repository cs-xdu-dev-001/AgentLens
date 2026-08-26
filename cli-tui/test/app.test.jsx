import {EventEmitter} from 'node:events';
import {mkdtemp, mkdir, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {render} from 'ink-testing-library';
import {
  activeTaskAnchorMetrics,
  App,
  buildTuiDeliveryPresentation,
  buildTuiDiagnosticReport,
  changeReviewArtifacts,
  changeReviewKey,
  compactWorkspaceStatus,
  compactSessionHeaderLabel,
  expandPastedTextRefs,
  enqueueWaitingInteraction,
  formatPastedTextRef,
  nextPromptSuggestion,
  pastedTextLineCount,
  permissionRuleBehavior,
  rankModelOptions,
  resolveInteractionFocus,
  removeWaitingInteraction,
  resolveTerminalMode,
  runActivityPresentation,
  retryTurnRequest,
  runtimeStatusFromEvent,
  sanitizeComposerInput,
  sessionTitleFromPrompt,
  shellActivityPreview,
  settleRuntimeRows,
  shouldAnimateRuntimeStatus,
  shouldCollapsePaste,
  streamingPreview,
  taskOutcomeState,
  thinkingStateForPhase,
  transcriptSearchMatches,
  transcriptSearchText,
  turnRequestSnapshot,
  updatePermissionRules,
  workspaceExecutionBlock,
  workspaceGitSummary,
} from '../src/app.jsx';
import {stableMarkdownBoundary} from '../src/markdown.jsx';
import {createRunProjection, projectRunEvent} from '../src/protocol.js';
import {
  editLocalModelConfigText,
  localModelConfigPayload,
  normalizeLocalModelConfig,
} from '../src/localModelConfig.jsx';
import {
  sanitizeTerminalTitle,
  shouldNotifyTerminalTransition,
  supportsTerminalProgress,
  terminalFeedbackState,
  terminalClipboardSequence,
  terminalCopySelection,
  terminalNotificationSequence,
  terminalNotificationsEnabled,
  terminalProgressSequence,
  terminalTitleSequence,
} from '../src/terminalFeedback.js';

const tick = () => new Promise(resolve => setTimeout(resolve, 30));

test('delivery presentation distinguishes complete, partial, and unverified outcomes', () => {
  assert.deepEqual(
    buildTuiDeliveryPresentation({
      artifacts: [{path: 'report.md', addedLines: 4}],
      verifications: [{status: 'passed'}],
      status: '已完成',
    }).state,
    {tone: 'success', label: '验证通过'},
  );
  const failed = buildTuiDeliveryPresentation({
    artifacts: [{path: 'report.md'}],
    status: '执行失败',
  });
  assert.equal(failed.title, '本轮结果');
  assert.equal(failed.state.label, '运行失败');
  assert.equal(failed.actionHint, 'Ctrl+T查看未完成步骤');
  assert.equal(buildTuiDeliveryPresentation({artifacts: [{path: 'report.md'}]}).state.label, '待验证');
});

test('session titles are compact and redact credential-shaped text', () => {
  assert.equal(sessionTitleFromPrompt('  修复\n登录按钮  '), '修复 登录按钮');
  assert.doesNotMatch(
    sessionTitleFromPrompt('使用 sk-abcdefghijklmnopqrstuvwxyz1234567890 调试接口'),
    /sk-[A-Za-z0-9]/,
  );
  assert.ok(sessionTitleFromPrompt('很长的任务说明'.repeat(20)).length <= 64);
  assert.equal(compactSessionHeaderLabel('检查当前工作区并给出修复建议', 120), '检查当前工作区并给出修复建议');
  assert.match(compactSessionHeaderLabel('检查当前工作区并给出一份非常详细的修复建议', 60), /…$/);
});

test('workspace status keeps branch and dirty state visible without exposing the full path', () => {
  assert.equal(compactWorkspaceStatus({branch: 'main', dirty: false}), 'main');
  assert.equal(
    compactWorkspaceStatus({branch: 'feature/task-ui', dirty: true, changedFiles: 3}),
    'feature/task-ui · 3处改动',
  );
  assert.equal(
    compactWorkspaceStatus({cwd: '/srv/agentlens', dirty: true, changedFiles: 1}),
    'agentlens · 1处改动',
  );
  assert.equal(
    compactWorkspaceStatus({
      branch: 'main',
      dirty: false,
      projectInstructions: {sources: [{path: 'AGENTS.md'}]},
    }),
    'main · 1份项目指令',
  );
  assert.deepEqual(
    workspaceGitSummary({
      git: {
        repository: true,
        branch: 'feature/git-awareness',
        upstream: 'origin/feature/git-awareness',
        changedFiles: 4,
        stagedFiles: 1,
        modifiedFiles: 2,
        untrackedFiles: 1,
        conflictedFiles: 0,
        ahead: 2,
        behind: 1,
      },
    }),
    {
      repository: true,
      branch: 'feature/git-awareness',
      changed: 4,
      staged: 1,
      modified: 2,
      untracked: 1,
      conflicted: 0,
      ahead: 2,
      behind: 1,
      label: 'feature/git-awareness · 4处改动 · ↑2 ↓1',
      detail: 'feature/git-awareness · ↑2 ↓1 · 跟踪origin/feature/git-awareness · 1个已暂存 · 2个未暂存 · 1个未跟踪',
    },
  );
  assert.equal(
    workspaceGitSummary({branch: 'main', dirty: true, changedFiles: 2}).detail,
    'main · 未设置上游分支 · 2个文件已修改',
  );
});

test('change review only includes reversible workspace files and keeps stable identities', () => {
  const changes = changeReviewArtifacts([
    {artifactId: 'file:a', path: 'src/a.py', diffAvailable: true},
    {operationId: 'edit-b', path: 'src/b.py'},
    {artifactId: 'reference:web', url: 'https://example.com'},
    {artifactId: 'file:no-diff', path: 'README.md'},
  ]);

  assert.deepEqual(changes.map(change => change.path), ['src/a.py', 'src/b.py']);
  assert.equal(changeReviewKey(changes[0], 0), 'file:a');
  assert.equal(changeReviewKey(changes[1], 1), 'edit-b');
  assert.equal(changeReviewKey({path: 'src/c.py'}, 2), 'src/c.py');
});

test('model catalog keeps the active and recent models first and tolerates fuzzy queries', () => {
  const models = [
    {id: 1, name: 'DeepSeek Chat', modelName: 'deepseek-chat', provider: 'deepseek'},
    {id: 2, name: 'GPT 5.5', modelName: 'gpt-5.5', provider: 'openai', selected: true},
    {id: 3, name: 'Kimi K3', modelName: 'kimi-k3', provider: 'moonshot'},
  ];
  assert.deepEqual(rankModelOptions(models, ['3']).map(item => item.id), [2, 3, 1]);
  assert.equal(rankModelOptions(models, [], 'kimk')[0]?.id, 3);
});

test('local model configuration keeps secrets out of snapshots and edits text at the cursor', () => {
  const snapshot = normalizeLocalModelConfig({
    baseUrl: 'https://api.example.com/v1',
    modelName: 'gpt-test',
    apiMode: 'responses',
    hasApiKey: true,
  });
  assert.equal(snapshot.apiKey, '');
  assert.equal(snapshot.hasApiKey, true);
  assert.deepEqual(
    editLocalModelConfigText('gpt-test', 3, {character: 'X', key: {}}),
    {value: 'gptX-test', cursor: 4},
  );
  assert.deepEqual(localModelConfigPayload({...snapshot, apiKey: ''}), {
    provider: 'custom',
    baseUrl: 'https://api.example.com/v1',
    modelName: 'gpt-test',
    apiMode: 'responses',
  });
});

test('completed runs keep child tool failures as warnings instead of failing the whole turn', () => {
  const completed = taskOutcomeState({
    failure: {message: '旧的工具错误'},
    phase: '工具执行失败',
    rows: [
      {status: 'success'},
      {status: 'failed', repeatCount: 2},
      {status: 'waiting'},
    ],
    runSummary: {status: 'completed'},
    running: false,
  });
  assert.deepEqual(completed, {
    childFailureCount: 2,
    completedWithWarnings: true,
    failed: false,
    runStatus: 'completed',
    waiting: false,
  });

  const failed = taskOutcomeState({
    rows: [{status: 'failed'}],
    running: false,
  });
  assert.equal(failed.failed, true);
  assert.equal(failed.completedWithWarnings, false);
});

test('active task anchor reports live duration, token usage, and protocol progress', () => {
  assert.equal(activeTaskAnchorMetrics({
    elapsedMs: 4_200,
    runProjection: {
      runSummary: {completedSteps: 1, totalSteps: 3, totalTokens: 637},
    },
  }), '4s · ~637 tokens · 1/3');
  assert.equal(activeTaskAnchorMetrics({elapsedMs: 0}), '0ms');
});

test('quiet runs distinguish slow progress from an actual failure', () => {
  const base = Date.parse('2026-08-26T00:00:00Z');
  assert.equal(runActivityPresentation({
    running: true,
    lastActivityAt: new Date(base).toISOString(),
    now: base + 10_000,
  }), null);
  assert.deepEqual(runActivityPresentation({
    running: true,
    lastActivityAt: new Date(base).toISOString(),
    now: base + 20_000,
  }), {
    color: '#d97757',
    detail: '仍在运行，等待下一条进展',
    label: '仍在运行',
  });
  assert.deepEqual(runActivityPresentation({
    running: true,
    lastActivityAt: new Date(base).toISOString(),
    now: base + 50_000,
  }), {
    color: '#d9a441',
    detail: '暂未收到新进展，任务仍在运行',
    label: '等待响应',
  });
});

test('home workspaces block execution while preserving remote and project workspaces', () => {
  assert.match(
    workspaceExecutionBlock({workspaceKind: 'home'}),
    /\/workspace <项目目录>/,
  );
  assert.equal(workspaceExecutionBlock({workspaceKind: 'project'}), '');
  assert.equal(workspaceExecutionBlock({remote: true, workspaceKind: 'home'}), '');
});

test('tool permission rules move tools between Allow, Ask, and Deny with safe precedence', () => {
  let rules = {allow: [], ask: [], deny: []};
  rules = updatePermissionRules(rules, 'allow', 'run_sandbox_command');
  assert.equal(permissionRuleBehavior('RUN_SANDBOX_COMMAND', rules), 'allow');
  rules = updatePermissionRules(rules, 'ask', 'run_sandbox_command');
  assert.deepEqual(rules.allow, []);
  assert.equal(permissionRuleBehavior('run_sandbox_command', rules), 'ask');
  rules = updatePermissionRules(rules, 'deny', '*');
  assert.equal(permissionRuleBehavior('write_workspace_file', rules), 'deny');
  rules = updatePermissionRules(rules, 'deny', '*', true);
  assert.equal(permissionRuleBehavior('write_workspace_file', rules), '');
  assert.equal(updatePermissionRules(rules, 'allow', 'invalid tool name'), rules);
});

test('next prompt suggestions only appear for actionable completed or failed runs', () => {
  assert.equal(nextPromptSuggestion({runSummary: {status: 'running'}}), '');
  assert.equal(nextPromptSuggestion({
    runSummary: {status: 'completed'},
    artifacts: [{path: 'src/app.jsx'}],
  }), '检查本次改动并运行相关验证');
  assert.equal(nextPromptSuggestion({
    runSummary: {status: 'completed'},
    references: [{url: 'https://example.com'}],
  }), '核对这些来源并总结关键结论');
  assert.equal(nextPromptSuggestion({
    error: {code: 'tool_failed'},
    recoveryActions: ['retry', 'fix'],
  }), '分析这个错误并继续完成任务');
});

test('Tab accepts the next prompt suggestion without submitting it immediately', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.42.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('修改首页');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'agent_event',
    event: {
      eventName: 'artifact.created',
      artifactId: 'file:src/app.jsx',
      artifactType: 'file',
      path: 'src/app.jsx',
      operation: 'write',
    },
  });
  client.emit('message', {type: 'turn_completed', runId: 'run-follow-up', answer: '修改完成'});
  await waitForFrame(view, /下一步\s+检查本次改动并运行相关验证/);
  assert.match(view.lastFrame(), /Tab采纳 · Esc忽略/);

  view.stdin.write('\t');
  await waitForFrame(view, /已采纳建议，可继续编辑后发送/);
  assert.equal(client.sent.filter(message => message.type === 'submit').length, 1);
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.filter(message => message.type === 'submit').at(-1)?.text, '检查本次改动并运行相关验证');
});

test('terminal feedback mirrors idle, running, waiting, and failed Agent states', () => {
  assert.deepEqual(terminalFeedbackState(), {
    kind: 'idle', title: 'AgentLens', progressState: 'clear', progressPercent: 0,
  });
  assert.equal(terminalFeedbackState({running: true}).progressState, 'indeterminate');
  assert.deepEqual(terminalFeedbackState({running: true, progressPercent: 40}), {
    kind: 'running', title: 'AgentLens — 运行中', progressState: 'running', progressPercent: 40,
  });
  assert.deepEqual(terminalFeedbackState({ready: false, connecting: true, contextLabel: 'AgentLens-demo'}), {
    kind: 'connecting',
    title: 'AgentLens-demo — AgentLens — 正在连接',
    progressState: 'indeterminate',
    progressPercent: 0,
  });
  assert.deepEqual(terminalFeedbackState({ready: false}), {
    kind: 'unavailable',
    title: 'AgentLens — 未连接',
    progressState: 'clear',
    progressPercent: 0,
  });
  assert.equal(
    terminalFeedbackState({running: true, contextLabel: '\u001b[31mprivate-project\u0007'}).title,
    'private-project — AgentLens — 运行中',
  );
  assert.equal(terminalFeedbackState({running: true, waiting: true}).kind, 'waiting');
  assert.equal(terminalFeedbackState({failed: true}).progressState, 'error');
  assert.equal(sanitizeTerminalTitle('\u001b[31mAgentLens\u0007'), 'AgentLens');
  assert.equal(terminalTitleSequence('AgentLens'), '\u001b]0;AgentLens\u001b\\');
  assert.equal(
    terminalClipboardSequence('diagnostic'),
    '\u001b]52;c;ZGlhZ25vc3RpYw==\u001b\\',
  );
  assert.equal(terminalProgressSequence('running', 140), '\u001b]9;4;1;100\u001b\\');
  assert.equal(supportsTerminalProgress({WT_SESSION: '1'}), false);
  assert.equal(supportsTerminalProgress({ConEmuANSI: 'ON'}), true);
  assert.equal(supportsTerminalProgress({TERM_PROGRAM: 'ghostty', TERM_PROGRAM_VERSION: '1.2.0'}), true);
  assert.equal(supportsTerminalProgress({TERM_PROGRAM: 'iTerm.app', TERM_PROGRAM_VERSION: '3.6.5'}), false);
  assert.equal(terminalNotificationSequence({}, {}).charCodeAt(0), 7);
  assert.equal(terminalNotificationsEnabled({}), true);
  assert.equal(terminalNotificationsEnabled({KNOWFLOW_CLI_TERMINAL_NOTIFICATIONS: '0'}), false);
  assert.equal(terminalNotificationsEnabled({KNOWFLOW_CLI_TERMINAL_NOTIFICATIONS: '0', AGENTLENS_CLI_TERMINAL_NOTIFICATIONS: '1'}), true);
  assert.equal(shouldNotifyTerminalTransition({
    previousKind: 'running', nextKind: 'idle', runStatus: 'completed', lastInteractionAt: 1000, now: 8000,
  }), true);
  assert.equal(shouldNotifyTerminalTransition({
    previousKind: 'running', nextKind: 'idle', runStatus: 'cancelled', lastInteractionAt: 1000, now: 8000,
  }), false);
  assert.equal(shouldNotifyTerminalTransition({
    previousKind: 'running', nextKind: 'waiting', lastInteractionAt: 5000, now: 8000,
  }), false);
});

test('copy selection returns the latest answer or a requested Markdown code block', () => {
  const answer = [
    '先执行检查。',
    '',
    '```bash',
    'npm test',
    '```',
    '',
    '```js',
    'console.log("ok");',
    '```',
  ].join('\n');
  assert.deepEqual(terminalCopySelection(answer), {
    ok: true,
    label: '最近回答',
    text: answer,
  });
  assert.deepEqual(terminalCopySelection(answer, 'answer'), {
    ok: true,
    label: '最近回答',
    text: answer,
  });
  assert.deepEqual(terminalCopySelection(answer, 'code 1'), {
    ok: true,
    label: '代码块1/2',
    text: 'npm test',
  });
  assert.deepEqual(terminalCopySelection(answer, 'code'), {
    ok: true,
    label: '代码块2/2',
    text: 'console.log("ok");',
  });
  assert.match(terminalCopySelection('没有代码', 'code').message, /没有代码块/);
  assert.match(terminalCopySelection(answer, 'code 3').message, /共有2个代码块/);
});

test('retry request snapshots preserve mode, display text, and reasoning effort', () => {
  const snapshot = turnRequestSnapshot(
    '检查完整工作区',
    '[粘贴内容 #1 +20行]',
    {mode: 'prompt', reasoningEffort: 'high', permissionMode: 'plan', attachmentPaths: ['README.md']},
  );
  assert.deepEqual(retryTurnRequest('检查完整工作区', snapshot, 'low'), snapshot);
  assert.deepEqual(retryTurnRequest('!echo ok', snapshot, 'medium'), {
    text: 'echo ok',
    displayText: 'echo ok',
    mode: 'shell',
    reasoningEffort: 'medium',
    permissionMode: 'ask',
    attachmentPaths: [],
  });
});

test('run projection preserves the failed step and advertised recovery actions', () => {
  const projection = projectRunEvent(createRunProjection(), {
    eventName: 'step.failed',
    stepId: 'step-read',
    title: '读取配置',
    attemptCount: 2,
    error: {code: 'workspace_read_failed', message: '无法读取配置', retryable: true},
    recoveryActions: ['continue', 'retry', 'fix'],
  });
  assert.deepEqual(projection.failedStep, {
    id: 'step-read',
    title: '读取配置',
    attemptCount: 2,
  });
  assert.deepEqual(projection.recoveryActions, ['continue', 'retry', 'fix']);
  assert.equal(projection.error.code, 'workspace_read_failed');
});

test('diagnostic report exposes support metadata without prompts, paths, or secrets', () => {
  const report = buildTuiDiagnosticReport({
    version: '0.22.0',
    model: 'gpt-5.5',
    apiMode: 'Responses协议',
    workspace: {
      cwd: '/home/alice/private-project',
      branch: 'main',
      dirty: true,
      changedFiles: 2,
    },
    permissionMode: 'ask',
    runId: 'run-safe',
    runProjection: {
      runSummary: {status: 'failed', completedSteps: 2, totalSteps: 3, toolCalls: 4},
      error: {code: 'upstream_error', message: 'api_key=sk-do-not-copy'},
    },
    now: 0,
  });
  assert.match(report, /项目指令:/);
  assert.match(report, /AgentLens脱敏诊断/);
  assert.match(report, /工作区: private-project · main · 未设置上游分支 · 2个文件已修改/);
  assert.match(report, /进度: 2\/3/);
  assert.match(report, /错误码: upstream_error/);
  assert.doesNotMatch(report, /\/home\/alice|sk-do-not-copy|api_key/);
  const unsafeIdentifiers = buildTuiDiagnosticReport({
    runId: '/home/alice/private/run-1',
    runProjection: {error: {code: String.raw`C:\Users\alice\secret.txt`}},
    now: 0,
  });
  assert.doesNotMatch(unsafeIdentifiers, /\/home\/alice|C:\\Users|secret\.txt/);
});

test('interaction focus resolves to one highest-priority input owner', () => {
  assert.equal(resolveInteractionFocus({suggestionsLength: 2}), 'commands');
  assert.equal(resolveInteractionFocus({modelPicker: true, permissionPicker: true}), 'models');
  assert.equal(resolveInteractionFocus({toolDetailOpen: true, taskNavigationOpen: true}), 'toolDetail');
  assert.equal(resolveInteractionFocus({approval: {}, modelPicker: true}), 'approval');
  assert.equal(resolveInteractionFocus({question: {}, approval: {}}), 'question');
  assert.equal(resolveInteractionFocus({recoveryOpen: true, toolDetailOpen: true}), 'recovery');
  assert.equal(resolveInteractionFocus({transcriptSearchOpen: true, historySearchOpen: true}), 'transcriptSearch');
});

test('transcript search indexes visible conversation text without hidden runtime data', () => {
  const items = [
    {id: 'user-1', role: 'user', content: '检查AgentLens发布状态'},
    {id: 'assistant-1', role: 'assistant', content: '发布检查已经完成'},
    {
      id: 'task-1',
      role: 'task_summary',
      goal: '验证发布',
      phase: '已完成',
      activities: [['tool-1', {label: '运行测试', toolName: 'run_tests', input: 'SECRET'}]],
    },
    {id: 'internal-1', role: 'system', content: '不可见内部提示发布'},
  ];
  assert.equal(transcriptSearchText(items[2]).includes('运行测试'), true);
  assert.equal(transcriptSearchMatches(items, '发布').length, 3);
  assert.equal(transcriptSearchMatches(items, 'SECRET').length, 0);
  assert.equal(transcriptSearchMatches(items, '内部提示').length, 0);
  assert.match(transcriptSearchMatches(items, 'AgentLens')[0].snippet, /AgentLens/);
});

test('Ctrl+F opens searchable visible transcript results without sending another model request', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.32.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查发布状态');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'turn_completed', answer: '发布检查完成，服务健康'});
  await tick();
  const submitCount = client.sent.filter(item => item.type === 'submit').length;

  view.stdin.write('\x06');
  view.stdin.write('发布');
  await tick();
  assert.match(view.lastFrame(), /搜索对话/);
  assert.match(view.lastFrame(), /1\/2/);
  assert.match(view.lastFrame(), /检查发布状态/);
  assert.equal(client.sent.filter(item => item.type === 'submit').length, submitCount);

  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /2\/2/);
  assert.match(view.lastFrame(), /发布检查完成/);
  view.stdin.write('\u001b');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /搜索对话/);
});

test('runtime spinner stops once useful progress is visible', () => {
  assert.equal(shouldAnimateRuntimeStatus({running: true}), true);
  assert.equal(shouldAnimateRuntimeStatus({running: true, hasVisibleStream: true}), false);
  assert.equal(shouldAnimateRuntimeStatus({running: true, hasVisibleWork: true}), false);
  assert.equal(shouldAnimateRuntimeStatus({running: true, blocked: true}), false);
  assert.equal(shouldAnimateRuntimeStatus({running: true, cancelPending: true}), false);
  assert.equal(shouldAnimateRuntimeStatus({running: false}), false);
});

test('shell progress keeps a redacted five-line live preview and classifies failures', () => {
  const preview = shellActivityPreview({
    name: 'run_sandbox_command',
    status: 'running',
    stdout: 'one\ntwo\nthree\nfour\nfive\nsix\napi_key=secret-value',
  });
  assert.deepEqual(preview.lines, ['three', 'four', 'five', 'six', 'api_key=[已隐藏]']);
  assert.equal(preview.hiddenLines, 2);
  assert.equal(preview.label, '实时输出');

  const timeout = shellActivityPreview({
    name: 'run_sandbox_command',
    status: 'failed',
    errorCode: 'tool_timeout',
  });
  assert.equal(timeout.label, '命令超时');
  assert.equal(timeout.timedOut, true);
});

test('unified event names settle tool and step status even without legacy status fields', () => {
  assert.equal(runtimeStatusFromEvent({eventName: 'tool.completed'}), 'completed');
  assert.equal(runtimeStatusFromEvent({eventName: 'tool.failed'}), 'failed');
  assert.equal(runtimeStatusFromEvent({eventName: 'step.cancelled'}), 'cancelled');
  assert.equal(runtimeStatusFromEvent({type: 'tool_result', status: 'failed'}), 'failed');
});

test('terminal turns settle only unfinished runtime rows', () => {
  const rows = new Map([
    ['running', {status: 'running', title: '执行命令'}],
    ['waiting', {status: 'waiting', title: '等待确认'}],
    ['done', {status: 'completed', title: '已完成'}],
  ]);
  const settled = settleRuntimeRows(rows, 'failed');
  assert.notEqual(settled, rows);
  assert.equal(settled.get('running').status, 'failed');
  assert.equal(settled.get('waiting').status, 'failed');
  assert.equal(settled.get('done').status, 'completed');
});

test('waiting interactions keep arrival order, deduplicate, and resolve by identity', () => {
  const approval = {kind: 'approval', event: {runId: 'run-1', approvalId: 'approval-1'}};
  const question = {kind: 'question', event: {runId: 'run-1', questionId: 'question-1'}};
  const queued = enqueueWaitingInteraction(enqueueWaitingInteraction([], approval), question);
  assert.deepEqual(enqueueWaitingInteraction(queued, approval), queued);
  assert.deepEqual(removeWaitingInteraction(queued, 'approval', approval.event), [question]);
});

test('task queue manager changes priority and retrieves a task for editing', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('先执行任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('稍后检查日志');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /接下来 1/);

  view.stdin.write('\u0014');
  await tick();
  assert.match(view.lastFrame(), /任务队列/);
  assert.match(view.lastFrame(), /\[接下来\] 稍后检查日志/);

  view.stdin.write('\u001b[D');
  await tick();
  assert.match(view.lastFrame(), /\[稍后\] 稍后检查日志/);

  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /已取回任务，可修改后重新提交/);
  assert.match(view.lastFrame(), /稍后检查日志/);
  assert.doesNotMatch(view.lastFrame(), /接下来 1/);
});

test('TUI update command delegates to Python and requires a restart after success', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.35.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/update');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'cli_update'});
  assert.match(view.lastFrame(), /正在准备CLI更新|更新中/);

  client.emit('message', {type: 'cli_update_started', currentVersion: '0.35.0'});
  await tick();
  assert.match(view.lastFrame(), /正在更新AgentLens v0\.35\.0/);

  client.emit('message', {type: 'cli_update_completed', nextVersion: '0.36.0', restartRequired: true});
  await tick();
  assert.match(view.lastFrame(), /已更新到v0\.36\.0/);
  assert.match(view.lastFrame(), /重启生效/);

  const sentCount = client.sent.length;
  view.stdin.write('/update');
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.length, sentCount);
  assert.match(view.lastFrame(), /更新已完成，请重启AgentLens/);
});

test('TUI update command recovers when the runtime request cannot be sent', async t => {
  const client = new FakeClient();
  client.send = () => false;
  const view = render(<App client={client} version="0.35.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/update');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /更新请求未发送/);
  assert.doesNotMatch(view.lastFrame(), /更新中/);
});

test('empty Escape retrieves the most recently queued prompt', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  for (const task of ['正在执行', '排队任务B', '排队任务C']) {
    view.stdin.write(task);
    view.stdin.write('\r');
    await tick();
  }
  assert.match(view.lastFrame(), /接下来 2/);

  view.stdin.write('\u001b');
  await tick();
  assert.match(view.lastFrame(), /已取回最近排队任务/);
  assert.match(view.lastFrame(), /排队任务C/);
  assert.match(view.lastFrame(), /接下来 1/);
  assert.equal(client.sent.filter(item => item.type === 'submit').length, 1);
});

test('double Escape opens the rewind picker from an empty composer', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.54.1" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('\u001b');
  await tick();
  assert.match(view.lastFrame(), /再按一次Esc回到历史消息/);
  assert.equal(client.sent.some(item => item.type === 'rewind_points'), false);

  view.stdin.write('\u001b');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'rewind_points'});
  assert.match(view.lastFrame(), /回到历史消息/);
});

test('now priority interrupts the active request and ignores its late terminal event', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('当前任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('立即任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('\u0014');
  await tick();
  view.stdin.write('\u001b[C');
  await tick();

  assert.deepEqual(client.sent.at(-1), {type: 'cancel'});
  assert.match(view.lastFrame(), /\[现在\] 立即任务/);
  assert.match(view.lastFrame(), /正在切换到立即任务/);

  client.emit('message', {type: 'cancel_requested', requestId: 'turn-1', runId: 'run-A', accepted: true});
  client.emit('message', {type: 'turn_completed', requestId: 'turn-1', runId: 'run-A', cancelled: true, answer: ''});
  await tick();
  await tick();
  const submits = client.sent.filter(item => item.type === 'submit');
  assert.equal(submits.length, 2);
  assert.equal(submits[1].text, '立即任务');
  assert.equal(submits[1].requestId, 'turn-2');

  client.emit('message', {type: 'turn_failed', requestId: 'turn-1', runId: 'run-A', message: '迟到错误'});
  await tick();
  assert.doesNotMatch(view.lastFrame(), /迟到错误|队列已暂停/);
});

test('thinking animation follows the active Agent phase and defaults to solving', () => {
  assert.equal(thinkingStateForPhase('模型正在分析'), 'solving');
  assert.equal(thinkingStateForPhase('正在联网搜索'), 'searching');
  assert.equal(thinkingStateForPhase('连接MCP服务'), 'connecting');
  assert.equal(thinkingStateForPhase('整理长期记忆'), 'listening');
  assert.equal(thinkingStateForPhase('正在激活Skill'), 'weaving');
  assert.equal(thinkingStateForPhase('读取工作区文件'), 'working');
});

test('large paste references preserve the original text', () => {
  const original = '第一行\n第二行\n第三行';
  const reference = formatPastedTextRef(7, pastedTextLineCount(original));
  assert.equal(reference, '[粘贴内容 #7 +3行]');
  assert.equal(shouldCollapsePaste(original), true);
  assert.equal(expandPastedTextRefs(`检查：${reference}`, {7: original}), `检查：${original}`);
});

async function waitForFrame(view, pattern, timeoutMs = 1500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const frame = view.lastFrame() ?? '';
    pattern.lastIndex = 0;
    if (pattern.test(frame)) return frame;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.match(view.lastFrame() ?? '', pattern);
  return view.lastFrame() ?? '';
}

async function waitForCondition(predicate, message, timeoutMs = 1500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  assert.ok(predicate(), message);
}

class FakeClient extends EventEmitter {
  constructor({readyDelay = 0} = {}) {
    super();
    this.sent = [];
    this.readyDelay = readyDelay;
  }

  start() {
    const emitReady = () => this.emit('message', {
      type: 'ready',
      protocolVersion: 14,
      agentEventSchemaVersion: 1,
      model: 'deepseek-chat',
      commands: [{value: '/tool:read-file', description: '读取文件', source: 'tool'}],
      workspace: {
        projectRoot: '/workspace',
        cwd: '/workspace',
        allowedDirectories: ['/workspace'],
        protectedPatterns: ['.git', '.env*'],
        branch: 'main',
        dirty: false,
        changedFiles: 0,
      },
      sessions: [],
      history: [],
      models: [
        {id: 1, name: 'deepseek-chat', modelName: 'deepseek-chat', provider: 'deepseek', apiMode: 'chat_completions', selected: true, switchable: true},
        {id: 2, name: 'GPT 5.5', modelName: 'gpt-5.5', provider: 'openai', apiMode: 'responses', selected: false, switchable: true},
      ],
    });
    if (this.readyDelay > 0) setTimeout(emitReady, this.readyDelay);
    else queueMicrotask(emitReady);
  }

  send(message) {
    this.sent.push(message);
    return true;
  }

  close() {}
}

class ClosingClient extends FakeClient {
  constructor(options) {
    super(options);
    this.closed = 0;
  }

  close() {
    this.closed += 1;
  }
}

test('bang mode runs explicit shell commands without asking the model', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.20.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('!');
  await tick();
  assert.match(view.lastFrame(), /Shell模式/);
  assert.match(view.lastFrame(), /SRT沙箱/);

  view.stdin.write('echo sandbox-ok');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'shell',
    requestId: 'turn-1',
    command: 'echo sandbox-ok',
  });

  client.emit('message', {
    type: 'agent_event',
    requestId: 'turn-1',
    event: {
      type: 'tool_result',
      runId: 'shell-run',
      toolCallId: 'shell-call',
      toolName: 'run_sandbox_command',
      status: 'success',
      output: {stdout: 'sandbox-ok\n', exitCode: 0},
    },
  });
  client.emit('message', {
    type: 'turn_completed',
    requestId: 'turn-1',
    runId: 'shell-run',
    answer: 'sandbox-ok\n',
  });
  await waitForFrame(view, /sandbox-ok/);

  view.stdin.write('\u001b');
  await tick();
  assert.match(view.lastFrame(), /已返回问答模式/);
});

test('queued bang commands preserve shell mode and execution order', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.20.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('先执行Agent任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('!echo queued-shell');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /接下来 1/);
  assert.equal(client.sent.filter(item => item.type === 'shell').length, 0);

  client.emit('message', {
    type: 'turn_completed',
    requestId: 'turn-1',
    runId: 'run-agent',
    answer: 'Agent任务完成',
  });
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline && client.sent.filter(item => item.type === 'shell').length === 0) await tick();
  assert.deepEqual(client.sent.filter(item => item.type === 'shell')[0], {
    type: 'shell',
    requestId: 'turn-2',
    command: 'echo queued-shell',
  });
});

test('Ink app renders command suggestions and streamed tool progress', async () => {
  const client = new FakeClient({readyDelay: 80});
  const view = render(<App client={client} version="0.9.0" />);
  await waitForFrame(view, /deepseek-chat/);
  assert.match(view.lastFrame(), /AgentLens/);
  assert.match(view.lastFrame(), /deepseek-chat/);

  view.stdin.write('/');
  await tick();
  assert.match(view.lastFrame(), /查看命令与快捷键/);
  view.stdin.write('\u001b');
  view.stdin.write('\u007f');
  await tick();
  view.stdin.write('检查服务器');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'submit');
  assert.equal(client.sent.at(-1).text, '检查服务器');

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_started',
      toolCallId: 'call-shell',
      toolName: 'run_sandbox_command',
      status: 'running',
      arguments: {command: 'uptime'},
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_progress',
      toolCallId: 'call-shell',
      toolName: 'run_sandbox_command',
      status: 'running',
      output: 'up 3 days',
      elapsedSeconds: 0.4,
      totalLines: 1,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /正在运行/);
  assert.doesNotMatch(view.lastFrame(), /run_sandbox_command/);
  assert.match(view.lastFrame(), /0\.4s/);
  assert.match(view.lastFrame(), /实时输出/);
  assert.match(view.lastFrame(), /up 3 days/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'approval_required',
      toolName: 'write_workspace_file',
      risk: 'write',
      destructive: false,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /需要确认/);
  view.stdin.write('y');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'allow_once'});

  view.unmount();
});

test('command completion reveals the selected command argument contract', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/mo');
  await tick();
  assert.match(view.lastFrame(), /\/model/);
  view.stdin.write('\t');
  await tick();
  assert.match(view.lastFrame(), /list \| use <ID> \| config/);
  assert.equal(client.sent.filter(item => item.type === 'submit').length, 0);

  view.stdin.write('use 2');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /list \| use <ID> \| config/);
  view.unmount();
});

test('at mentions fuzzy-complete workspace files without exposing sensitive paths', async t => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), 'knowflow-at-'));
  await mkdir(join(workspaceRoot, 'src'));
  await writeFile(join(workspaceRoot, 'src', 'app.jsx'), 'export default {};\n');
  await writeFile(join(workspaceRoot, '.env'), 'SECRET=hidden\n');
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" workspaceRoot={workspaceRoot} />);
  t.after(async () => {
    view.unmount();
    await rm(workspaceRoot, {recursive: true, force: true});
  });
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查 @app');
  await waitForFrame(view, /@src\/app\.jsx/);
  assert.doesNotMatch(view.lastFrame(), /\.env/);
  view.stdin.write('\t');
  await tick();
  assert.match(view.lastFrame(), /检查 @src\/app\.jsx/);
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.find(item => item.type === 'submit')?.text, '检查 @src/app.jsx');
});

test('workspace context attachments stay visible and travel with submit, queue, and detach', async t => {
  const workspaceRoot = await mkdtemp(join(tmpdir(), 'knowflow-attach-'));
  await mkdir(join(workspaceRoot, 'src'));
  await writeFile(join(workspaceRoot, 'src', 'app.jsx'), 'export default {};\n');
  const client = new FakeClient();
  const view = render(<App client={client} version="0.37.0" workspaceRoot={workspaceRoot} />);
  t.after(async () => {
    view.unmount();
    await rm(workspaceRoot, {recursive: true, force: true});
  });
  await waitForFrame(view, /deepseek-chat/);
  await new Promise(resolve => setTimeout(resolve, 120));

  view.stdin.write('/attach src/app.jsx');
  view.stdin.write('\r');
  await waitForFrame(view, /上下文\s+src\/app\.jsx/);
  assert.match(view.lastFrame(), /\/detach移除/);

  view.stdin.write('检查这个组件');
  view.stdin.write('\r');
  await tick();
  const submitted = client.sent.find(item => item.type === 'submit');
  assert.deepEqual(submitted, {
    type: 'submit',
    requestId: 'turn-1',
    text: '检查这个组件',
    reasoningEffort: 'default',
    executionMode: 'auto',
    attachmentPaths: ['src/app.jsx'],
  });
  assert.match(view.lastFrame(), /上下文：src\/app\.jsx/);
  assert.doesNotMatch(view.lastFrame(), /\/detach移除/);

  view.stdin.write('/attach src/app.jsx');
  view.stdin.write('\r');
  await waitForFrame(view, /\/detach移除/);
  view.stdin.write('排队检查组件');
  view.stdin.write('\r');
  await waitForFrame(view, /接下来 1/);
  client.emit('message', {type: 'turn_completed', answer: '完成'});
  await waitForFrame(view, /完成/);
  await waitForCondition(
    () => client.sent.some(item => item.type === 'submit' && item.text === '排队检查组件'),
    'queued attachment prompt was not submitted',
  );
  assert.deepEqual(
    client.sent.find(item => item.type === 'submit' && item.text === '排队检查组件')?.attachmentPaths,
    ['src/app.jsx'],
  );
  client.emit('message', {type: 'turn_completed', answer: '排队完成'});
  await waitForFrame(view, /排队完成/);
  view.stdin.write('/attach src/app.jsx');
  view.stdin.write('\r');
  await waitForFrame(view, /\/detach移除/);
  view.stdin.write('/detach all');
  view.stdin.write('\r');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /\/detach移除/);
});

test('Enter executes the highlighted slash command while Tab only completes it', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/he');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /命令浏览/);
  assert.match(view.lastFrame(), /快捷键 \d+/);
  assert.equal(client.sent.filter(item => item.type === 'submit').length, 0);

  view.stdin.write('\u001b');
  await tick();

  view.stdin.write('/mo');
  await tick();
  view.stdin.write('\t');
  await tick();
  assert.match(view.lastFrame(), /参数\s+\[list \| use <ID> \| config\]/);
  assert.equal(client.sent.filter(item => item.type === 'models').length, 0);
});

test('/help browses builtin and dynamic commands, searches, and returns a command to the composer', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/help');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /命令浏览/);
  assert.match(view.lastFrame(), /扩展命令 1/);

  view.stdin.write('\t');
  view.stdin.write('\t');
  view.stdin.write('read');
  await tick();
  assert.match(view.lastFrame(), /搜索：read/);
  assert.match(view.lastFrame(), /\/tool:read-file/);

  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /已取用命令，可补充参数后执行/);
  assert.match(view.lastFrame(), /\/tool:read-file/);
  assert.doesNotMatch(view.lastFrame(), /命令浏览\s+搜索/);
  assert.equal(client.sent.filter(item => item.type === 'submit').length, 0);
});

test('running cancellation gives immediate feedback and ignores repeated Ctrl+C', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('长任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('\x03');
  await tick();
  assert.match(view.lastFrame(), /正在请求取消/);
  assert.match(view.lastFrame(), /取消中/);
  assert.equal(client.sent.filter(item => item.type === 'cancel').length, 1);

  view.stdin.write('\x03');
  await tick();
  assert.equal(client.sent.filter(item => item.type === 'cancel').length, 1);

  client.emit('message', {type: 'cancel_requested', accepted: true});
  await tick();
  assert.match(view.lastFrame(), /正在取消/);
  client.emit('message', {type: 'turn_completed', cancelled: true, answer: ''});
  await tick();
  assert.match(view.lastFrame(), /已取消/);
  assert.doesNotMatch(view.lastFrame(), /取消中/);
});

test('the active overlay exclusively owns rendering and command navigation', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('当前任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('排队任务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('/he');
  await tick();
  assert.match(view.lastFrame(), /查看命令与快捷键/);

  view.stdin.write('\u0014');
  await tick();
  assert.match(view.lastFrame(), /任务队列/);
  assert.doesNotMatch(view.lastFrame(), /查看命令与快捷键/);
  assert.match(view.lastFrame(), /任务队列 · ↑↓选择/);
});

test('Ink app answers a structured Agent question and resumes the same run', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'user_question_required',
      questionId: 'question-1',
      runId: 'run-1',
      header: '选择部署方式',
      question: '这次要部署到哪个环境？',
      options: [
        {label: '测试环境', value: 'staging', description: '先做安全验收'},
        {label: '生产环境', value: 'production', description: '直接上线'},
      ],
      allowCustom: true,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /选择部署方式/);
  assert.match(view.lastFrame(), /测试环境/);
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'answer_question',
    questionId: 'question-1',
    answer: 'staging',
    selectedOptions: ['staging'],
  });
  view.unmount();
});

test('Ink app searches and switches models from the composer', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/model');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'models', action: 'list'});

  client.emit('message', {
    type: 'model_list',
    model: 'deepseek-chat',
    models: [
      {id: 1, name: 'deepseek-chat', modelName: 'deepseek-chat', provider: 'deepseek', apiMode: 'chat_completions', selected: true, switchable: true},
      {id: 2, name: 'GPT 5.5', modelName: 'gpt-5.5', provider: 'openai', apiMode: 'responses', selected: false, switchable: true},
    ],
  });
  await tick();
  assert.match(view.lastFrame(), /选择模型/);
  view.stdin.write('gpt');
  await tick();
  assert.match(view.lastFrame(), /搜索：gpt/);
  assert.match(view.lastFrame(), /GPT 5\.5/);
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'models', action: 'use', modelId: 2});

  client.emit('message', {
    type: 'model_changed',
    model: 'GPT 5.5',
    selected: {id: 2, name: 'GPT 5.5'},
  });
  await tick();
  assert.match(view.lastFrame(), /已切换到GPT 5\.5/);
  view.unmount();
});

test('Ink app configures the local model in place without exposing the API key', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.58.0" localMode />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'startup_failed',
    message: 'Responses API connection failed: HTTP 403',
  });
  await tick();
  assert.match(view.lastFrame(), /输入\/configure可在当前TUI内重新配置模型/);

  view.stdin.write('/configure');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'local_model_config', action: 'get'});

  client.emit('message', {
    type: 'local_model_config',
    config: {
      provider: 'custom',
      baseUrl: 'https://api.example.com/v1',
      modelName: 'gpt-5.6-sol',
      apiMode: 'responses',
      hasApiKey: false,
      overriddenFields: {},
    },
  });
  await tick();
  assert.match(view.lastFrame(), /配置本地模型/);
  view.stdin.write('\u001b[B');
  await tick();
  view.stdin.write('\u001b[B');
  await tick();
  view.stdin.write('\u001b[B');
  await tick();
  view.stdin.write('sk-test-secret-123456789');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /sk-test-secret/);
  assert.match(view.lastFrame(), /••••/);
  view.stdin.write('\u001b[B');
  await tick();
  view.stdin.write('\r');
  await tick();
  const request = client.sent.at(-1);
  assert.equal(request.type, 'local_model_config');
  assert.equal(request.action, 'test_and_save');
  assert.equal(request.config.apiKey, 'sk-test-secret-123456789');

  client.emit('message', {
    type: 'local_model_config_failed',
    action: 'test_and_save',
    message: '上游拒绝访问（HTTP 403）。请检查Key分组权限。',
  });
  await tick();
  assert.match(view.lastFrame(), /上游拒绝访问（HTTP 403）/);
  assert.match(view.lastFrame(), /配置本地模型/);

  client.emit('message', {
    type: 'local_model_config_recommended',
    message: 'Responses API连接失败。',
    recommendation: {apiMode: 'chat_completions', label: 'Chat Completions'},
  });
  await tick();
  assert.match(view.lastFrame(), /检测到Chat Completions可用/);
  assert.match(view.lastFrame(), /R应用并保存/);
  view.stdin.write('r');
  await tick();
  assert.equal(client.sent.at(-1).action, 'test_and_save');
  assert.equal(client.sent.at(-1).config.apiMode, 'chat_completions');
  assert.equal(client.sent.at(-1).config.apiKey, 'sk-test-secret-123456789');

  client.emit('message', {
    type: 'local_model_config_saved',
    model: 'gpt-5.6-sol',
    detail: '连接可用',
    config: {},
    models: [{id: 'local', name: 'gpt-5.6-sol', selected: true, switchable: false}],
  });
  await tick();
  assert.match(view.lastFrame(), /已保存gpt-5\.6-sol/);
  assert.doesNotMatch(view.lastFrame(), /配置本地模型/);
});

test('local model status explains protocol and provider-controlled sampling', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.2" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'model_list',
    model: 'kimi-k3',
    models: [{
      id: 'local',
      name: 'kimi-k3',
      modelName: 'kimi-k3',
      provider: 'custom',
      apiMode: 'chat_completions',
      selected: true,
      switchable: false,
    }],
  });
  await tick();
  assert.match(view.lastFrame(), /Chat Completions协议/);
  assert.match(view.lastFrame(), /采样参数由模型服务决定/);

  view.stdin.write('\u001b');
  await tick();
  view.stdin.write('/status');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'context', action: 'status'});
  assert.match(view.lastFrame(), /kimi-k3 · Chat Completions协议/);
  assert.match(view.lastFrame(), /上下文待统计/);
  assert.match(view.lastFrame(), /不发送temperature、top_p或max_tokens/);
});

test('Alt+P opens the model picker without entering composer text', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.18.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('\u001bp');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'models', action: 'list'});
  assert.doesNotMatch(view.lastFrame(), /❯ p/);
  view.unmount();
});

test('reasoning picker changes the session effort and forwards it with submissions', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.7" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/reasoning high');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /推理强度：深入/);

  view.stdin.write('检查复杂问题');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'submit',
    requestId: 'turn-1',
    text: '检查复杂问题',
    reasoningEffort: 'high',
    executionMode: 'auto',
  });
});

test('plan command switches the session to read-only planning and forwards execution mode', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.38.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/plan 先检查当前工作区再给出改造步骤');
  view.stdin.write('\r');
  await tick();

  assert.deepEqual(client.sent.at(-1), {
    type: 'submit',
    requestId: 'turn-1',
    text: '先检查当前工作区再给出改造步骤',
    reasoningEffort: 'default',
    executionMode: 'plan_only',
  });
  assert.match(view.lastFrame(), /计划 · Shift\+Tab切换/);
});

test('opening a new picker replaces the previous keyboard owner', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/permissions');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /权限模式/);

  client.emit('message', {
    type: 'model_list',
    model: 'deepseek-chat',
    models: [
      {id: 1, name: 'deepseek-chat', modelName: 'deepseek-chat', provider: 'deepseek', apiMode: 'chat_completions', selected: true, switchable: true},
      {id: 2, name: 'GPT 5.5', modelName: 'gpt-5.5', provider: 'openai', apiMode: 'responses', selected: false, switchable: true},
    ],
  });
  await tick();
  assert.match(view.lastFrame(), /选择模型 · ↑↓选择 · Enter切换 · Esc关闭/);
  assert.doesNotMatch(view.lastFrame(), /选择权限模式/);

  view.stdin.write('\u001b');
  await tick();
  assert.match(view.lastFrame(), /输入任务，\/查看命令/);
});

test('approval takes keyboard focus and closes transient pickers', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'model_list',
    model: 'deepseek-chat',
    models: [{id: 1, name: 'deepseek-chat', selected: true, switchable: true}],
  });
  await tick();
  assert.match(view.lastFrame(), /选择模型/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'approval_required',
      toolName: 'write_workspace_file',
      risk: 'write',
      destructive: true,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /权限确认 · ←→选择 · Enter确认 · Esc拒绝/);
  assert.doesNotMatch(view.lastFrame(), /选择模型/);

  view.stdin.write('\u001b');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'deny'});
});

test('session approval reuses the exact tool grant and resets on a new session', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.24.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  const approval = approvalId => ({
    type: 'agent_event',
    event: {
      type: 'approval_required',
      approvalId,
      serverName: 'workspace',
      toolName: 'write_workspace_file',
      risk: 'write',
      destructive: true,
    },
  });

  client.emit('message', approval('approval-session-1'));
  await tick();
  view.stdin.write('s');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'allow_once'});

  const sentBeforeReuse = client.sent.length;
  client.emit('message', approval('approval-session-2'));
  await tick();
  assert.equal(client.sent.length, sentBeforeReuse + 1);
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'allow_once'});
  assert.doesNotMatch(view.lastFrame(), /需要确认：write_workspace_file/);

  client.emit('message', {type: 'session_reset'});
  await tick();
  client.emit('message', approval('approval-session-3'));
  await tick();
  assert.match(view.lastFrame(), /需要确认：write_workspace_file/);
});

test('permission rule editor auto-allows matching tools and keeps rule editing keyboard-first', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.45.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/permissions rules');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /工具权限规则/);
  assert.match(view.lastFrame(), /Allow 0/);

  view.stdin.write('a');
  await tick();
  view.stdin.write('run_sandbox_command');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /run_sandbox_command/);
  assert.match(view.lastFrame(), /Allow 1/);

  const sentBeforeApproval = client.sent.length;
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'approval_required',
      approvalId: 'permission-rule-allow',
      serverName: 'workspace',
      toolName: 'run_sandbox_command',
      risk: 'execute',
      destructive: true,
    },
  });
  await tick();
  assert.equal(client.sent.length, sentBeforeApproval + 1);
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'allow_once'});
  assert.doesNotMatch(view.lastFrame(), /需要确认：run_sandbox_command/);

  client.emit('message', {type: 'session_reset'});
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'approval_required',
      approvalId: 'permission-rule-after-reset',
      serverName: 'workspace',
      toolName: 'run_sandbox_command',
      risk: 'execute',
      destructive: true,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /需要确认：run_sandbox_command/);
});

test('approval and structured questions wait in arrival order without being overwritten', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'approval_required',
      runId: 'run-queue',
      approvalId: 'approval-queue',
      toolName: 'write_workspace_file',
      risk: 'write',
      destructive: true,
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'user_question_required',
      runId: 'run-queue',
      questionId: 'question-queue',
      header: '确认范围',
      question: '继续处理哪些文件？',
      options: [{label: '当前文件', value: 'current'}],
      allowCustom: false,
    },
  });
  await tick();

  assert.match(view.lastFrame(), /需要确认：write_workspace_file/);
  assert.match(view.lastFrame(), /待处理 1\/2/);
  assert.doesNotMatch(view.lastFrame(), /继续处理哪些文件/);

  view.stdin.write('y');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'approve', decision: 'allow_once'});
  assert.match(view.lastFrame(), /继续处理哪些文件/);
  assert.match(view.lastFrame(), /回答问题 · ↑↓选择 · Enter确认/);

  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'answer_question',
    questionId: 'question-queue',
    answer: 'current',
    selectedOptions: ['current'],
  });
  assert.doesNotMatch(view.lastFrame(), /待处理 1\/2/);
});

test('Ink app searches prompt history, stashes drafts, and restores killed text', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查应用日志');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'turn_completed', answer: '日志正常'});
  await tick();
  view.stdin.write('核对发布版本');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'turn_completed', answer: '版本正常'});
  await tick();

  view.stdin.write('日志');
  view.stdin.write('\x12');
  await tick();
  assert.match(view.lastFrame(), /搜索历史/);
  assert.match(view.lastFrame(), /检查应用日志/);
  view.stdin.write('\r');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /搜索历史/);
  assert.match(view.lastFrame(), /检查应用日志/);

  view.stdin.write('\x13');
  await tick();
  assert.match(view.lastFrame(), /草稿已暂存/);
  view.stdin.write('\x13');
  await tick();
  assert.match(view.lastFrame(), /草稿已恢复/);
  assert.match(view.lastFrame(), /检查应用日志/);

  view.stdin.write('\x15');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /❯ 检查应用日志/);
  view.stdin.write('\x19');
  await tick();
  assert.match(view.lastFrame(), /检查应用日志/);
  view.unmount();
});

test('Ink app auto-restores a stashed prompt after another task is submitted', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.42.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('稍后继续完善发布说明');
  view.stdin.write('\x13');
  await waitForFrame(view, /草稿已暂存，发送当前输入后自动恢复/);

  view.stdin.write('先检查当前构建');
  view.stdin.write('\r');
  await tick();

  assert.equal(client.sent.at(-1)?.type, 'submit');
  assert.equal(client.sent.at(-1)?.text, '先检查当前构建');
  assert.match(view.lastFrame(), /草稿已自动恢复/);
  assert.match(view.lastFrame(), /稍后继续完善发布说明/);
  assert.doesNotMatch(view.lastFrame(), /草稿已暂存，发送当前输入后自动恢复 · Ctrl\+S立即恢复/);
});

test('Ink app collapses multiline paste but submits the full content', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  const pasted = '错误一\n错误二\n错误三';
  view.stdin.write(`\x1b[200~${pasted}\x1b[201~`);
  await tick();
  assert.match(view.lastFrame(), /粘贴内容 #1 \+3行/);
  assert.match(view.lastFrame(), /提交时自动展开/);
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'submit');
  assert.equal(client.sent.at(-1).text, pasted);
  view.unmount();
});

test('collapsed paste survives stash restore and queued execution', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('先执行当前任务');
  view.stdin.write('\r');
  await tick();

  const pasted = '日志一\n日志二\n日志三\n日志四';
  view.stdin.write(`\x1b[200~${pasted}\x1b[201~`);
  await tick();
  view.stdin.write('\x13');
  await tick();
  assert.match(view.lastFrame(), /草稿已暂存/);
  view.stdin.write('\x13');
  await tick();
  assert.match(view.lastFrame(), /粘贴内容 #1 \+4行/);
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /接下来 1/);
  assert.match(view.lastFrame(), /粘贴内容 #1 \+4行/);

  client.emit('message', {type: 'turn_completed', answer: '第一轮完成'});
  await waitForFrame(view, /第一轮完成/);
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline && client.sent.at(-1)?.text !== pasted) await tick();
  assert.equal(client.sent.at(-1).type, 'submit');
  assert.equal(client.sent.at(-1).text, pasted);
  view.unmount();
});

test('Ink app loads workspace history and clears it through the runtime', async () => {
  const client = new FakeClient();
  client.start = () => queueMicrotask(() => client.emit('message', {
    type: 'ready',
    protocolVersion: 14,
    agentEventSchemaVersion: 1,
    model: 'deepseek-chat',
    commands: [],
    workspace: {projectRoot: '/workspace', cwd: '/workspace'},
    sessions: [],
    history: ['上次检查发布状态', '上次查看服务日志'],
  }));
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('\x12');
  await tick();
  assert.match(view.lastFrame(), /上次查看服务日志/);
  view.stdin.write('\x1b');
  await tick();
  view.stdin.write('/history clear');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'history', action: 'clear'});
  client.emit('message', {
    type: 'history_result',
    action: 'clear',
    history: [],
    message: '本工作区的输入历史已清空。',
  });
  await tick();
  assert.match(view.lastFrame(), /输入历史已清空/);
  view.stdin.write('\x12');
  await tick();
  assert.match(view.lastFrame(), /还没有可搜索的历史输入/);
  view.unmount();
});

test('Ink app exposes queued follow-ups and lets users clear them', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('先检查服务');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('再检查日志');
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /接下来 1/);
  assert.match(view.lastFrame(), /再检查日志/);

  view.stdin.write('/tasks clear');
  view.stdin.write('\r');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /接下来 1/);
  assert.match(view.lastFrame(), /待发送任务已清空/);
  view.unmount();
});

test('Ink app restores a durable runtime queue paused and claims it before execution', async t => {
  const client = new FakeClient();
  const restored = {
    id: 'queue-restored',
    text: '恢复后继续检查',
    displayText: '恢复后继续检查',
    priority: 'next',
    sequence: 4,
    mode: 'prompt',
    reasoningEffort: 'high',
    permissionMode: 'ask',
    attachmentPaths: [],
  };
  client.start = () => queueMicrotask(() => client.emit('message', {
    type: 'ready',
    protocolVersion: 14,
    agentEventSchemaVersion: 1,
    model: 'deepseek-chat',
    commands: [],
    workspace: {projectRoot: '/workspace', cwd: '/workspace'},
    sessions: [],
    history: [],
    queue: [restored],
    queuePaused: true,
    queueRecovered: 1,
    models: [],
  }));
  const view = render(<App client={client} version="0.64.4" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /已恢复1个异常中断的任务/);
  assert.match(view.lastFrame(), /恢复后继续检查/);
  assert.match(view.lastFrame(), /已保存/);

  view.stdin.write('/continue');
  view.stdin.write('\r');
  await waitForCondition(
    () => client.sent.some(message => message.type === 'submit' && message.text === restored.text),
    'restored prompt was not submitted',
  );
  const claim = client.sent.find(message => message.type === 'queue' && message.action === 'claim');
  assert.equal(claim.itemId, restored.id);
  assert.equal(claim.item.id, restored.id);
  assert.ok(client.sent.indexOf(claim) < client.sent.findIndex(message => message.type === 'submit'));
});

test('queued follow-ups honor now, next and later priorities', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('当前任务');
  view.stdin.write('\r');
  await tick();

  for (const command of [
    '/tasks add later 稍后任务',
    '/tasks add next 普通任务',
    '/tasks add now 优先任务',
  ]) {
    view.stdin.write(command);
    view.stdin.write('\r');
    await tick();
  }
  view.stdin.write('/tasks list');
  view.stdin.write('\r');
  await tick();
  const frame = view.lastFrame();
  assert.ok(frame.lastIndexOf('优先任务') < frame.lastIndexOf('普通任务'), frame);
  assert.ok(frame.lastIndexOf('普通任务') < frame.lastIndexOf('稍后任务'), frame);

  client.emit('message', {type: 'turn_completed', answer: '当前任务完成'});
  const expected = ['优先任务', '普通任务', '稍后任务'];
  for (const task of expected) {
    const deadline = Date.now() + 1000;
    while (
      Date.now() < deadline
      && client.sent.filter(message => message.type === 'submit').at(-1)?.text !== task
    ) await tick();
    assert.equal(client.sent.filter(message => message.type === 'submit').at(-1)?.text, task);
    client.emit('message', {type: 'turn_completed', answer: `${task}完成`});
  }
});

test('runtime send failures pause and preserve the prompt for retry', async t => {
  const client = new FakeClient();
  const send = client.send.bind(client);
  let failNextSubmit = true;
  client.send = message => {
    if (message.type === 'submit' && failNextSubmit) {
      failNextSubmit = false;
      return false;
    }
    return send(message);
  };
  const view = render(<App client={client} version="0.17.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('不能丢失的任务');
  view.stdin.write('\r');
  await waitForFrame(view, /队列已暂停/);
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  assert.match(view.lastFrame(), /不能丢失的任务/);

  view.stdin.write('/continue');
  view.stdin.write('\r');
  const deadline = Date.now() + 1000;
  while (
    Date.now() < deadline
    && client.sent.filter(message => message.type === 'submit').at(-1)?.text !== '不能丢失的任务'
  ) await tick();
  assert.equal(client.sent.filter(message => message.type === 'submit').at(-1)?.text, '不能丢失的任务');
});

test('failed runs keep new follow-ups paused and resume them in FIFO order', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('任务A');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('任务B');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => message.text),
    ['任务A'],
  );

  client.emit('message', {
    type: 'turn_failed',
    runId: 'run-A',
    message: '任务A失败',
  });
  await waitForFrame(view, /待发送已暂停/);

  view.stdin.write('任务C');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => message.text),
    ['任务A'],
  );
  assert.match(view.lastFrame(), /待发送已暂停/);
  assert.match(view.lastFrame(), /任务B/);
  assert.match(view.lastFrame(), /任务C/);

  view.stdin.write('/continue');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'resume_session',
    requestId: 'resume-2',
    runId: 'run-A',
  });

  client.emit('message', {type: 'turn_completed', runId: 'run-A', answer: '任务A恢复完成'});
  const firstDeadline = Date.now() + 1000;
  while (
    Date.now() < firstDeadline
    && client.sent.filter(message => message.type === 'submit').at(-1)?.text !== '任务B'
  ) await tick();
  assert.equal(client.sent.filter(message => message.type === 'submit').at(-1)?.text, '任务B');

  client.emit('message', {type: 'turn_completed', answer: '任务B完成'});
  const secondDeadline = Date.now() + 1000;
  while (
    Date.now() < secondDeadline
    && client.sent.filter(message => message.type === 'submit').at(-1)?.text !== '任务C'
  ) await tick();
  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => message.text),
    ['任务A', '任务B', '任务C'],
  );
  view.unmount();
});

test('retry turn bypasses a paused failure queue instead of enqueueing itself', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查失败任务');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_failed',
    runId: 'run-retry',
    message: '上游暂时不可用',
  });
  await waitForFrame(view, /队列已暂停/);

  view.stdin.write('/retry turn');
  view.stdin.write('\r');
  const deadline = Date.now() + 1000;
  while (
    Date.now() < deadline
    && client.sent.filter(message => message.type === 'submit').length < 2
  ) await tick();
  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => message.text),
    ['检查失败任务', '检查失败任务'],
  );
  assert.doesNotMatch(view.lastFrame(), /接下来1/);
  view.unmount();
});

test('retry turn preserves the failed task reasoning effort after session settings change', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.23.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/reasoning high');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('检查复杂故障');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_failed',
    runId: 'run-retry-reasoning',
    message: '上游暂时不可用',
  });
  await waitForFrame(view, /队列已暂停/);

  view.stdin.write('/reasoning low');
  view.stdin.write('\r');
  await tick();
  view.stdin.write('/retry turn');
  view.stdin.write('\r');
  const deadline = Date.now() + 1000;
  while (
    Date.now() < deadline
    && client.sent.filter(message => message.type === 'submit').length < 2
  ) await tick();

  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => ({
      text: message.text,
      reasoningEffort: message.reasoningEffort,
    })),
    [
      {text: '检查复杂故障', reasoningEffort: 'high'},
      {text: '检查复杂故障', reasoningEffort: 'high'},
    ],
  );
});

test('retry turn preserves shell mode instead of sending the command to the model', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.23.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('!');
  await tick();
  view.stdin.write('echo retry-shell');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_failed',
    runId: 'shell-retry',
    message: '沙箱暂时不可用',
  });
  await waitForFrame(view, /队列已暂停/);
  view.stdin.write('/retry turn');
  view.stdin.write('\r');
  const deadline = Date.now() + 1000;
  while (
    Date.now() < deadline
    && client.sent.filter(message => message.type === 'shell').length < 2
  ) await tick();

  assert.deepEqual(
    client.sent.filter(message => message.type === 'shell').map(message => message.command),
    ['echo retry-shell', 'echo retry-shell'],
  );
  assert.equal(client.sent.filter(message => message.type === 'submit').length, 0);
});

test('new sessions clear the previous retry target', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.23.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('旧会话任务');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'turn_completed', answer: '已完成'});
  await waitForFrame(view, /已完成/);
  view.stdin.write('/new');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'session_reset'});
  await waitForFrame(view, /新会话/);
  view.stdin.write('/retry turn');
  view.stdin.write('\r');
  await tick();

  assert.equal(client.sent.filter(message => message.type === 'submit').length, 1);
  assert.match(view.lastFrame(), /没有可重试的问题/);
});

test('edit restores the previous task to the composer before resubmitting', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.19.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查工作区状态');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'turn_completed', answer: '检查完成'});
  await waitForFrame(view, /检查完成/);

  view.stdin.write('/edit');
  view.stdin.write('\r');
  await waitForFrame(view, /已恢复上一条任务/);
  view.stdin.write('并给出风险');
  view.stdin.write('\r');
  await tick();

  assert.deepEqual(
    client.sent.filter(message => message.type === 'submit').map(message => message.text),
    ['检查工作区状态', '检查工作区状态并给出风险'],
  );
  view.unmount();
});

test('Ink app renders a live task summary and collapses it after completion', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.16.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('检查服务状态');
  view.stdin.write('\r');
  await tick();

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'agent_step',
      runId: 'run-live-summary',
      stepId: 'step-model',
      kind: 'model',
      name: 'model_completion',
      title: '模型正在分析',
      status: 'running',
      inputSummary: JSON.stringify({estimatedTokenCount: 637}),
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'agent_step',
      runId: 'run-live-summary',
      stepId: 'step-tool',
      kind: 'tool',
      name: 'web_fetch',
      title: '正在读取网页',
      status: 'running',
    },
  });
  await tick();
  assert.match(view.lastFrame(), /检查服务状态/);
  assert.match(view.lastFrame(), /~637 tokens/);
  assert.match(view.lastFrame(), /0\/2/);
  assert.match(view.lastFrame(), /模型正在分析/);
  assert.match(view.lastFrame(), /正在读取网页/);
  assert.match(view.lastFrame(), /[├└]/);
  assert.doesNotMatch(view.lastFrame(), /Ctrl\+G文件变更/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      eventName: 'artifact.created',
      artifactId: 'file:reports/report.md',
      artifactType: 'file',
      title: 'reports/report.md',
      path: 'reports/report.md',
      operation: 'write',
      writtenBytes: 512,
      addedLines: 12,
      removedLines: 2,
      operationId: 'edit_report',
      diffAvailable: true,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /1个产物/);
  assert.match(view.lastFrame(), /reports\/report\.md/);
  assert.match(view.lastFrame(), /\+12 · -2 · 512B/);
  assert.match(view.lastFrame(), /Ctrl\+G文件变更/);
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'reference',
      eventId: 'reference-report',
      artifactType: 'reference',
      url: 'https://example.com/report?token=SECRET#private',
      score: 0.91,
    },
  });
  await tick();
  assert.match(view.lastFrame(), /1个来源/);
  assert.match(view.lastFrame(), /example\.com\/report/);
  assert.doesNotMatch(view.lastFrame(), /SECRET|private/);
  view.stdin.write('\u0005');
  await waitForFrame(view, /引用来源[\s\S]*匹配度 91%/);
  assert.doesNotMatch(view.lastFrame(), /SECRET|private/);
  view.stdin.write('\u001b');
  await tick();
  view.stdin.write('\u0007');
  await waitForFrame(view, /文件变更[\s\S]*已查看 1\/1/);
  assert.match(view.lastFrame(), /正在读取差异/);
  assert.deepEqual(client.sent.at(-1), {
    type: 'workspace',
    action: 'diff',
    path: 'reports/report.md',
    requestId: 'change-diff-1',
  });
  client.emit('message', {
    type: 'workspace_result',
    action: 'diff',
    result: {patch: '+new line', files: [{path: 'reports/report.md', added: 1, removed: 0}]},
  });
  await tick();
  assert.match(view.lastFrame(), /\+new line/);
  view.stdin.write('\u0007');
  await tick();

  // 撤销结果必须更新统一运行投影；即使结果返回时变更面板已关闭，
  // 再次打开仍应显示最终的已撤销状态。
  client.emit('message', {
    type: 'workspace_result',
    action: 'undo',
    result: {
      operationId: 'edit_report',
      path: 'reports/report.md',
      reverted: true,
    },
  });
  await tick();
  view.stdin.write('\u0007');
  await tick();
  assert.match(view.lastFrame(), /reports\/report\.md/);
  assert.match(view.lastFrame(), /已撤销/);
  view.stdin.write('\u0007');
  await tick();

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'text_delta',
      text: '回答第一段。\n\n回答第二段。\n\n',
    },
  });
  await new Promise(resolve => setTimeout(resolve, 180));
  const runningFrame = view.lastFrame();
  assert.ok(runningFrame.indexOf('检查服务状态') < runningFrame.indexOf('回答第一段。'));

  for (const [stepId, title] of [['step-model', '模型分析完成'], ['step-tool', '网页读取完成']]) {
    client.emit('message', {
      type: 'agent_event',
      event: {
        type: 'agent_step',
        runId: 'run-live-summary',
        stepId,
        kind: stepId === 'step-model' ? 'model' : 'tool',
        name: stepId === 'step-model' ? 'model_completion' : 'web_fetch',
        title,
        status: 'success',
        inputSummary: stepId === 'step-model'
          ? JSON.stringify({estimatedTokenCount: 637})
          : undefined,
        verification: stepId === 'step-tool'
          ? {
            id: 'verification:step-tool',
            kind: 'check',
            tool: 'git_diff_check',
            status: 'passed',
            exitCode: 0,
            durationMs: 120,
          }
          : undefined,
        durationMs: 500,
      },
    });
  }
  client.emit('message', {
    type: 'turn_completed',
    runId: 'run-live-summary',
    answer: '检查完成。',
    changes: [{path: 'reports/report.md', added: 12, removed: 2}],
  });
  await tick();
  const completedFrame = view.lastFrame();
  assert.match(completedFrame, /1\/1/);
  assert.match(completedFrame, /已完成/);
  assert.match(completedFrame, /✓ 检查服务状态/);
  assert.match(completedFrame, /验证1\/1/);
  assert.doesNotMatch(completedFrame, /已完成并保存1个产物/);
  assert.match(completedFrame, /本轮交付/);
  assert.match(completedFrame, /验证通过/);
  assert.match(completedFrame, /1个文件已更改/);
  assert.match(completedFrame, /已撤销\s+reports\/report\.md\s+\+12 · -2 · 512B/);
  assert.doesNotMatch(completedFrame, /本轮修改/);
  assert.ok(completedFrame.indexOf('回答第一段。') < completedFrame.indexOf('本轮交付'));
  assert.ok(completedFrame.indexOf('检查服务状态') < completedFrame.indexOf('回答第一段。'));
  assert.doesNotMatch(completedFrame, /模型分析完成/);

  view.stdin.write('\u000f');
  await tick();
  view.stdin.write('\u0014');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /模型分析完成/);
  assert.match(view.lastFrame(), /已读取网页/);
  view.unmount();
});

test('final-only workspace changes render the same delivery card as artifact events', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.42.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('生成报告');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_completed',
    runId: 'run-final-changes',
    answer: '报告已生成。',
    changes: [{
      path: 'reports/final.md',
      added: 8,
      removed: 1,
      operation: 'write',
      operationId: 'change-final',
      diffAvailable: true,
    }],
  });

  await waitForFrame(view, /本轮交付/);
  const frame = view.lastFrame();
  assert.match(frame, /1个文件已更改/);
  assert.match(frame, /已写入\s+reports\/final\.md\s+\+8 · -1/);
  assert.doesNotMatch(frame, /本轮修改/);
});

test('/diff and /undo reuse the interactive change panel before mutating files', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.50.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('更新报告');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_completed',
    runId: 'run-command-changes',
    answer: '报告已更新。',
    changes: [{
      path: 'reports/final.md',
      added: 8,
      removed: 1,
      operation: 'edit',
      operationId: 'change-final',
      diffAvailable: true,
    }],
  });
  await waitForFrame(view, /本轮交付/);

  view.stdin.write('/diff');
  view.stdin.write('\r');
  await waitForFrame(view, /文件变更/);
  assert.deepEqual(client.sent.at(-1), {
    type: 'workspace',
    action: 'diff',
    path: 'reports/final.md',
    requestId: 'change-diff-1',
  });
  client.emit('message', {
    type: 'workspace_result',
    action: 'diff',
    result: {patch: Array.from({length: 30}, (_, index) => `+updated report ${index + 1}`).join('\n')},
  });
  await waitForFrame(view, /\+updated report 1/);
  assert.match(view.lastFrame(), /差异行 1-14\/30/);
  assert.doesNotMatch(view.lastFrame(), /\+updated report 20/);
  view.stdin.write('\u001b[6~');
  await waitForFrame(view, /\+updated report 20/);
  assert.match(view.lastFrame(), /差异行 15-28\/30/);
  assert.doesNotMatch(view.lastFrame(), /\+updated report 1(?:\D|$)/);
  view.stdin.write('\u001b');
  await tick();

  const undoCount = () => client.sent.filter(message => (
    message.type === 'workspace' && message.action === 'undo'
  )).length;
  view.stdin.write('/undo');
  view.stdin.write('\r');
  await waitForFrame(view, /D撤销此文件/);
  assert.equal(undoCount(), 0);
  view.stdin.write('d');
  await waitForFrame(view, /再次按D确认安全撤销/);
  assert.equal(undoCount(), 0);
  view.stdin.write('d');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'workspace',
    action: 'undo',
    operationId: 'change-final',
    runId: 'run-command-changes',
  });
});

test('Ink app counts down model rate-limit recovery and clears it on output', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.1" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查模型重试');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'agent_event',
    event: {
      eventName: 'model.retrying',
      retryAttempt: 1,
      maxRetries: 3,
      retryInMs: 2000,
      statusCode: 429,
      errorType: 'rate_limit',
    },
  });
  await tick();
  assert.match(view.lastFrame(), /等待重试/);
  assert.match(view.lastFrame(), /模型限流，2秒后重试（1\/3）/);

  await new Promise(resolve => setTimeout(resolve, 1100));
  assert.match(view.lastFrame(), /模型限流，1秒后重试（1\/3）/);

  client.emit('message', {
    type: 'agent_event',
    event: {eventName: 'message.delta', text: '已恢复'},
  });
  await tick();
  assert.doesNotMatch(view.lastFrame(), /等待重试|秒后重试/);
  assert.match(view.lastFrame(), /模型已恢复/);
});

test('Ink app hides upstream rate-limit account details after retries are exhausted', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.1" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('触发限流');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_failed',
    message: 'HTTP 429: rate_limit_reached_error: Your account org-8242d004acb748ada9255f6d42f4dc23<ak-fbzbf9goi431l1d8rrx1> reached organization max RPM: 3',
  });
  await waitForFrame(view, /上游模型请求过于频繁（HTTP 429），自动重试后仍未恢复/);

  assert.match(view.lastFrame(), /上游模型请求过于频繁（HTTP 429），自动重试后仍未恢复/);
  assert.match(view.lastFrame(), /失败/);
  assert.doesNotMatch(view.lastFrame(), /8242d004acb748ada9255f6d42f4dc23|fbzbf9goi431l1d8rrx1|max RPM/);

  view.stdin.write('\u0005');
  await waitForFrame(view, /运行详情/);
  assert.match(view.lastFrame(), /重试本轮/);
  assert.match(view.lastFrame(), /分析错误并继续/);
  assert.doesNotMatch(view.lastFrame(), /8242d004acb748ada9255f6d42f4dc23|fbzbf9goi431l1d8rrx1|max RPM/);

  view.stdin.write('\u001b[C');
  await waitForFrame(view, /❯ 分析错误并继续/);
  view.stdin.write('\r');
  await waitForCondition(
    () => client.sent.at(-1)?.type === 'submit'
      && /非可信诊断数据/.test(client.sent.at(-1)?.text || ''),
    'failed-run analysis task should be submitted',
  );
  assert.equal(client.sent.at(-1).type, 'submit');
  assert.match(client.sent.at(-1).text, /非可信诊断数据/);
});

test('Ctrl+T turns the task summary into a navigable view and opens the selected tool', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('检查网页');
  view.stdin.write('\r');
  await tick();

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_started',
      toolCallId: 'call-web-fetch',
      toolName: 'web_fetch',
      status: 'running',
      arguments: {url: 'https://example.com'},
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'agent_step',
      stepId: 'step-web-fetch',
      toolCallId: 'call-web-fetch',
      kind: 'tool',
      name: 'web_fetch',
      title: '正在读取 example.com',
      status: 'running',
    },
  });
  await tick();

  view.stdin.write('\u0014');
  await tick();
  assert.match(view.lastFrame(), /任务步骤/);
  assert.match(view.lastFrame(), /↑↓选择 · Enter查看 · Esc返回/);
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /工具详情/);
  assert.match(view.lastFrame(), /web_fetch/);
  assert.match(view.lastFrame(), /example\.com/);
  view.stdin.write('\u001b');
  await tick();
  assert.match(view.lastFrame(), /任务步骤/);
  view.stdin.write('\u001b');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /任务步骤\s+1\/1/);
  view.unmount();
});

test('Ctrl+T exposes failed verification and opens its matching tool details', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('构建项目');
  view.stdin.write('\r');
  await tick();

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_started',
      toolCallId: 'call-build',
      toolName: 'run_sandbox_command',
      status: 'running',
      arguments: {command: 'npm run build'},
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'agent_step',
      stepId: 'step-build',
      toolCallId: 'call-build',
      kind: 'sandbox',
      name: 'run_sandbox_command',
      title: '构建项目',
      status: 'failed',
      errorCode: 'build_failed',
      verification: {
        id: 'verification:call-build',
        kind: 'build',
        tool: 'npm_build',
        status: 'failed',
        exitCode: 2,
        durationMs: 900,
      },
    },
  });
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_result',
      toolCallId: 'call-build',
      toolName: 'run_sandbox_command',
      status: 'failed',
      errorCode: 'build_failed',
      errorMessage: 'build failed',
    },
  });
  await tick();

  view.stdin.write('\u0014');
  await tick();
  assert.match(view.lastFrame(), /任务步骤/);
  assert.match(view.lastFrame(), /构建 · 失败/);
  view.stdin.write('\u001b[B');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /工具详情/);
  assert.match(view.lastFrame(), /run_sandbox_command/);
  assert.match(view.lastFrame(), /build failed/);
});

test('Ink app preserves a failed run summary before partial output', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.16.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('执行一个会失败的任务');
  view.stdin.write('\r');
  await tick();

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'agent_step',
      runId: 'run-failed-summary',
      stepId: 'step-model',
      kind: 'model',
      name: 'model_completion',
      title: '模型正在分析',
      status: 'success',
    },
  });
  client.emit('message', {type: 'agent_event', event: {type: 'text_delta', text: '部分输出。'}});
  await new Promise(resolve => setTimeout(resolve, 180));
  client.emit('message', {
    type: 'turn_failed',
    runId: 'run-failed-summary',
    message: '工具调用失败',
  });
  await waitForFrame(view, /执行失败|队列已暂停/);

  view.stdin.write('\u000f');
  const frame = await waitForFrame(view, /对话记录/);
  assert.match(frame, /执行一个会失败的任务/);
  assert.match(frame, /失败/);
  assert.ok(frame.indexOf('执行一个会失败的任务') < frame.indexOf('部分输出。'));
  assert.match(frame, /R重试本轮|F分析错误|C继续执行/);
  view.unmount();
});

test('Ink app rejects unknown slash commands instead of sending them to the model', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.10.1" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/does-not-exist');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /未知命令/);
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  view.unmount();
});

test('/bug copies a redacted local diagnostic without sending a model request', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.22.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/bug');
  await tick();
  view.stdin.write('\r');
  const frame = await waitForFrame(view, /AgentLens脱敏诊断/);
  assert.match(frame, /客户端: CLI 0.22.0/);
  assert.match(frame, /隐私: 已排除对话正文、工具输入输出、完整路径和凭据/);
  assert.match(frame, /已发送终端剪贴板请求|当前终端不支持自动复制/);
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  view.unmount();
});

test('/notifications controls terminal attention feedback without sending a model request', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.64.5" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/notifications off');
  view.stdin.write('\r');
  await waitForFrame(view, /终端任务提醒已关闭（仅本次会话）/);
  view.stdin.write('/notifications status');
  view.stdin.write('\r');
  await waitForFrame(view, /终端任务提醒：已关闭/);
  view.stdin.write('/notifications on');
  view.stdin.write('\r');
  await waitForFrame(view, /终端任务提醒已开启（仅本次会话）/);
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  view.unmount();
});

test('/copy targets the completed Agent answer without sending another model request', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.22.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('生成示例');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'turn_completed',
    answer: '结果\n\n```bash\nnpm test\n```',
  });
  await tick();
  view.stdin.write('/copy code');
  view.stdin.write('\r');
  const frame = await waitForFrame(view, /当前终端不支持自动复制/);
  assert.doesNotMatch(frame, /还没有可复制/);
  assert.equal(client.sent.filter(message => message.type === 'submit').length, 1);
  view.unmount();
});

test('capability commands request and render real runtime status', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.11.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/tools');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'capabilities', section: 'tools'});
  client.emit('message', {
    type: 'capability_status',
    section: 'tools',
    status: {
      tools: {
        count: 2,
        enabled: true,
        items: [
          {name: 'read_workspace_file'},
          {name: 'run_sandbox_command'},
        ],
      },
      webSearch: {configured: true, enabled: true},
    },
  });
  await waitForFrame(view, /工具\s+2个可用/);
  assert.match(view.lastFrame(), /read_workspace_file/);
  await waitForFrame(view, /web_search\s+已启用/);
  view.unmount();
});

test('memory capability renders recent local memories', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.20.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/memory');
  await tick();
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'capability_status',
    section: 'memory',
    status: {
      memory: {
        configured: true,
        enabled: true,
        items: [{memory: '用户偏好中文回答'}],
      },
    },
  });
  await waitForFrame(view, /用户偏好中文回答/);
  view.unmount();
});

test('context commands inspect usage and compact with optional instructions', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.15.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('/context');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'context', action: 'status'});
  client.emit('message', {
    type: 'context_status',
    status: {
      usedTokens: 1200,
      maxTokens: 96000,
      usagePercent: 1.2,
      autoCompactAtPercent: 75,
      messageCount: 4,
      transcriptMessageCount: 6,
      roleTokens: {system: 100, user: 400, assistant: 700},
    },
  });
  await waitForFrame(view, /1200\/96000 tokens/);
  await waitForFrame(view, /上下文1%/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'context_usage_updated',
      usedTokens: 78000,
      maxTokens: 96000,
      remainingTokens: 18000,
      usagePercent: 81.2,
      warningAtPercent: 75,
      shouldWarn: true,
    },
  });
  await waitForFrame(view, /上下文81%/);

  view.stdin.write('/compact 保留工作区边界');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'context',
    action: 'compact',
    instructions: '保留工作区边界',
  });
  client.emit('message', {
    type: 'context_compacted',
    compacted: true,
    metadata: {reason: 'manual', originalTokens: 1200, compactedTokens: 500},
    status: {usedTokens: 500, maxTokens: 96000, usagePercent: 0.5},
    transcriptMessageCount: 6,
  });
  await waitForFrame(view, /上下文压缩完成/);
  assert.match(view.lastFrame(), /完整对话记录仍保留/);
  view.unmount();
});

test('workspace commands and resume picker use the runtime as source of truth', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.13.0" />);
  await waitForFrame(view, /deepseek-chat/);
  assert.match(view.lastFrame(), /\/workspace · main/);

  view.stdin.write('/workspace');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'workspace', action: 'status'});
  client.emit('message', {
    type: 'workspace_result',
    action: 'status',
    result: {
      projectRoot: '/workspace',
      cwd: '/workspace/src',
      allowedDirectories: ['/workspace'],
      protectedPatterns: ['.git', '.env*'],
      branch: 'main',
      dirty: true,
      changedFiles: 2,
    },
  });
  await waitForFrame(view, /2个文件已修改/);

  view.stdin.write('/resume');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'sessions');
  client.emit('message', {
    type: 'session_list',
    sessions: [{runId: 'run_restore', title: '恢复测试', status: 'failed'}],
  });
  await waitForFrame(view, /恢复测试[\s\S]*失败，可继续/);
  assert.match(view.lastFrame(), /P置顶\/取消/);
  view.stdin.write('p');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'session_pin',
    runId: 'run_restore',
    pinned: true,
  });
  client.emit('message', {
    type: 'session_pinned',
    result: {runId: 'run_restore', pinned: true},
  });
  await waitForFrame(view, /◆ 恢复测试/);
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'resume_session');
  assert.equal(client.sent.at(-1).runId, 'run_restore');
  await waitForFrame(view, /会话 恢复测试/);
  view.unmount();
});

test('startup resume opens the picker and continue restores the latest workspace session', async t => {
  const pickerClient = new FakeClient();
  const picker = render(<App client={pickerClient} version="0.54.1" startupAction="resume" />);
  t.after(() => picker.unmount());
  await waitForCondition(
    () => pickerClient.sent.some(message => message.type === 'sessions' && message.limit === 100),
    'startup resume did not request the workspace session list',
  );
  assert.match(picker.lastFrame(), /正在读取当前工作区的会话/);

  const continueClient = new FakeClient();
  continueClient.start = () => queueMicrotask(() => continueClient.emit('message', {
    type: 'ready',
    protocolVersion: 14,
    agentEventSchemaVersion: 1,
    model: 'deepseek-chat',
    commands: [],
    workspace: {projectRoot: '/workspace', cwd: '/workspace', branch: 'main'},
    sessions: [
      {runId: 'run_latest', title: '最近会话', status: 'completed', updatedAt: Date.now() / 1000},
      {runId: 'run_older', title: '更早会话', status: 'completed', updatedAt: Date.now() / 1000 - 60},
    ],
    history: [],
    models: [],
  }));
  const continued = render(<App client={continueClient} version="0.54.1" startupAction="continue" />);
  t.after(() => continued.unmount());
  await waitForCondition(
    () => continueClient.sent.some(message => message.type === 'resume_session'),
    'startup continue did not restore the latest workspace session',
  );
  const request = continueClient.sent.find(message => message.type === 'resume_session');
  assert.equal(request.runId, 'run_latest');
  assert.match(continued.lastFrame(), /会话 最近会话/);
});

test('home workspace keeps the draft and prevents failed task cards', async t => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.42.0" />);
  t.after(() => view.unmount());
  await waitForFrame(view, /deepseek-chat/);

  client.emit('message', {
    type: 'workspace_result',
    action: 'status',
    result: {
      projectRoot: '/home/tester',
      cwd: '/home/tester',
      allowedDirectories: ['/home/tester'],
      protectedPatterns: ['.git', '.env*'],
      workspaceKind: 'home',
      warnings: ['当前工作区是HOME目录。'],
    },
  });
  await waitForFrame(view, /未进入项目/);

  view.stdin.write('检查当前服务器');
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  assert.match(view.lastFrame(), /检查当前服务器/);
  assert.match(view.lastFrame(), /先指定项目目录/);

  view.stdin.write('\u0015');
  view.stdin.write('/workspace /workspace/project');
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'workspace',
    action: 'switch',
    path: '/workspace/project',
  });
  client.emit('message', {type: 'session_reset'});
  client.emit('message', {
    type: 'workspace_result',
    action: 'switch',
    history: ['新工作区历史'],
    sessions: [{runId: 'run_project', title: '项目会话', status: 'completed'}],
    result: {
      projectRoot: '/workspace/project',
      cwd: '/workspace/project',
      allowedDirectories: ['/workspace/project'],
      protectedPatterns: ['.git', '.env*'],
      workspaceKind: 'project',
      message: '已切换工作区：/workspace/project',
    },
  });
  await waitForFrame(view, /已切换工作区/);
  assert.doesNotMatch(view.lastFrame(), /未进入项目/);
});

test('session rename, branch and export commands stay inside the runtime protocol', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.28.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/rename 发布复盘');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'rename_session', title: '发布复盘'});
  client.emit('message', {
    type: 'session_renamed',
    result: {runId: 'run_current', title: '发布复盘'},
  });
  await waitForFrame(view, /当前会话已重命名为“发布复盘”/);
  assert.match(view.lastFrame(), /会话 发布复盘/);

  view.stdin.write('/branch 方案B');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'branch_session', title: '方案B'});
  client.emit('message', {
    type: 'session_branched',
    result: {
      runId: 'run_branch',
      title: '方案B',
      messageCount: 2,
      messages: [
        {role: 'user', content: '旧问题'},
        {role: 'assistant', content: '旧回答'},
      ],
    },
  });
  await waitForFrame(view, /已创建会话分支“方案B”/);
  assert.match(view.lastFrame(), /会话 方案B/);

  view.stdin.write('/export review.md');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'export_session', filename: 'review.md'});
  client.emit('message', {
    type: 'session_exported',
    result: {path: '/workspace/review.md', filename: 'review.md', messageCount: 2},
  });
  await waitForFrame(view, /已导出2条消息：.*review\.md/);
  view.unmount();
});

test('/rewind forks before a selected user message and restores its prompt', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.42.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/rewind');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {type: 'rewind_points'});
  client.emit('message', {
    type: 'rewind_points',
    points: [
      {messageId: null, messageIndex: 0, preview: '最早的问题'},
      {messageId: null, messageIndex: 2, preview: '需要重新处理的问题'},
    ],
  });
  await waitForFrame(view, /回到历史消息.*1\/2/);
  assert.match(view.lastFrame(), /需要重新处理的问题/);

  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'branch_session',
    title: '',
    messageId: null,
    messageIndex: 2,
  });
  client.emit('message', {
    type: 'session_branched',
    result: {
      runId: 'run_rewound',
      title: '测试会话（分支）',
      messageCount: 2,
      messages: [
        {role: 'user', content: '最早的问题'},
        {role: 'assistant', content: '最早的回答'},
      ],
      restoredQuestion: '需要重新处理的问题',
    },
  });
  await waitForFrame(view, /已回到历史消息/);
  assert.match(view.lastFrame(), /需要重新处理的问题/);
  assert.match(view.lastFrame(), /原会话/);
  view.unmount();
});

test('resume picker filters sessions, previews context and retries loading in place', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('/resume');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).limit, 100);
  assert.match(view.lastFrame(), /正在读取当前工作区的会话/);

  client.emit('message', {
    type: 'session_list',
    sessions: [
      {runId: 'run_alpha', title: '修复登录', status: 'completed', updatedAt: Date.now() / 1000 - 120, answer: '登录流程已修复'},
      {runId: 'run_beta', title: '检查部署', status: 'failed', updatedAt: Date.now() / 1000 - 7200, answer: '部署门禁失败'},
    ],
  });
  await tick();
  view.stdin.write('部署');
  await tick();
  assert.match(view.lastFrame(), /搜索：部署/);
  assert.match(view.lastFrame(), /检查部署/);
  assert.doesNotMatch(view.lastFrame(), /修复登录/);
  assert.match(view.lastFrame(), /部署门禁失败/);

  view.stdin.write('\u001b');
  await tick();
  view.stdin.write('/resume');
  await tick();
  view.stdin.write('\r');
  await tick();
  client.emit('message', {type: 'sessions_failed', message: '会话目录暂不可读'});
  await waitForFrame(view, /会话目录暂不可读/);
  view.stdin.write('r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'sessions');
  view.unmount();
});

test('long markdown replies stay inside the terminal viewport without raw markers', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.10.1" fullscreenEnabled />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('生成长报告');
  await tick();
  view.stdin.write('\r');
  await tick();
  const answer = `\u001b]8;;https://example.com\u0007**状态正常**\u001b]8;;\u0007\n\n${Array.from({length: 80}, (_, index) => `- 检查项${index + 1}`).join('\n')}`;
  client.emit('message', {type: 'agent_event', event: {type: 'text_delta', text: answer}});
  client.emit('message', {type: 'turn_completed', answer});
  await tick();
  await tick();
  const frame = view.lastFrame();
  assert.ok(frame.split('\n').length <= 24, `frame overflowed viewport:\n${frame}`);
  assert.doesNotMatch(frame, /\*\*状态正常\*\*/);
  assert.doesNotMatch(frame, /example\.com/);
  assert.match(frame, /检查项80/);
  assert.match(frame, /输入任务/);
  assert.match(frame, /询问/);

  view.stdin.write('\u001b[<64;5;5M');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /\[<64;5;5M/);

  view.stdin.write('\u000f');
  await tick();
  assert.match(view.lastFrame(), /对话记录/);
  assert.doesNotMatch(view.lastFrame(), /输入任务/);
  view.stdin.write('\u000f');
  await tick();
  assert.match(view.lastFrame(), /输入任务/);
  view.unmount();
});

test('fullscreen mode pins the active task above output until the turn settles', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.52.0" fullscreenEnabled />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('检查当前项目并修复问题');
  view.stdin.write('\r');
  const activeFrame = await waitForFrame(view, /任务\s+检查当前项目并修复问题.*运行中/);
  assert.match(activeFrame, /任务\s+检查当前项目并修复问题.*\d+(?:ms|s).*运行中/);

  client.emit('message', {type: 'turn_completed', answer: '检查完成'});
  await waitForFrame(view, /检查完成/);
  assert.doesNotMatch(view.lastFrame(), /任务\s+检查当前项目并修复问题.*运行中/);
  view.unmount();
});

test('terminal mode defaults to native scrollback and gates mouse capture behind fullscreen', () => {
  assert.deepEqual(resolveTerminalMode({}), {
    fullscreenEnabled: false,
    mouseEnabled: false,
  });
  assert.deepEqual(resolveTerminalMode({KNOWFLOW_CLI_MOUSE: '1'}), {
    fullscreenEnabled: false,
    mouseEnabled: false,
  });
  assert.deepEqual(resolveTerminalMode({KNOWFLOW_CLI_FULLSCREEN: '1'}), {
    fullscreenEnabled: true,
    mouseEnabled: false,
  });
  assert.deepEqual(resolveTerminalMode({
    KNOWFLOW_CLI_FULLSCREEN: '1',
    KNOWFLOW_CLI_MOUSE: '1',
  }), {
    fullscreenEnabled: true,
    mouseEnabled: true,
  });
});

test('native scrollback stays selectable while Ctrl+O opens a frozen keyboard-scrolling viewer', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.10.5" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('输出长报告');
  view.stdin.write('\r');
  await tick();
  const answer = Array.from({length: 40}, (_, index) => `记录行${index + 1}`).join('\n');
  client.emit('message', {type: 'turn_completed', answer});
  const frame = await waitForFrame(view, /记录行40/);
  assert.ok(frame.split('\n').length > 24, `native scrollback was still viewport-clamped:\n${frame}`);
  assert.match(frame, /记录行1/);
  assert.match(frame, /记录行40/);
  assert.match(frame, /终端滚轮选择复制/);

  view.stdin.write('\u000f');
  await tick();
  const viewerFrame = view.lastFrame();
  const visibleViewer = viewerFrame.split('\n').slice(-24).join('\n');
  assert.ok(visibleViewer.split('\n').length <= 24, `transcript viewer overflowed viewport:\n${visibleViewer}`);
  assert.match(visibleViewer, /对话记录/);
  assert.match(visibleViewer, /↑↓滚动/);

  client.emit('message', {type: 'turn_completed', answer: '进入浏览器后到达的新消息'});
  await tick();
  assert.doesNotMatch(view.lastFrame(), /进入浏览器后到达的新消息/);
  view.stdin.write('\u000f');
  await waitForFrame(view, /进入浏览器后到达的新消息/);
  view.unmount();
});

test('failed tool details expose recovery actions that really retry or ask the agent to fix', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.13.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('读取缺失文件并继续');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'tool_result',
      toolCallId: 'call-missing',
      toolName: '\u001b]0;forged-title\u0007read_workspace_file',
      status: 'failed',
      arguments: {path: 'missing.txt'},
      errorCode: 'not_found',
      errorMessage: 'missing path --password hunter2',
      stderr: 'No such file',
    },
  });
  client.emit('message', {type: 'turn_failed', runId: 'run-missing', message: '读取失败'});
  await waitForFrame(view, /队列已暂停/);
  assert.match(view.lastFrame(), /Ctrl\+E查看错误与恢复操作/);

  view.stdin.write('\u0005');
  await tick();
  assert.match(view.lastFrame(), /工具详情/);
  assert.match(view.lastFrame(), /missing path/);
  assert.match(view.lastFrame(), /--password=\[已隐藏\]/);
  assert.doesNotMatch(view.lastFrame(), /hunter2|forged-title/);
  assert.match(view.lastFrame(), /恢复\s+❯ 重试本轮\s+分析错误并继续/);
  assert.match(view.lastFrame(), /←→选择 · Enter执行/);

  view.stdin.write('f');
  await tick();
  const recovery = client.sent.at(-1);
  assert.equal(recovery.type, 'submit');
  assert.match(recovery.text, /工具read_workspace_file执行失败/);
  assert.match(recovery.text, /避免重复同一无效调用/);
  assert.match(recovery.text, /读取缺失文件并继续/);
  view.unmount();
});

test('task failure opens a first-class recovery panel and continues from checkpoint', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.25.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('检查失败恢复');
  view.stdin.write('\r');
  await tick();
  client.emit('message', {
    type: 'agent_event',
    event: {
      eventName: 'step.failed',
      stepId: 'step-check',
      title: '执行项目检查',
      attemptCount: 2,
      error: {code: 'project_check_failed', message: '检查命令失败', retryable: true},
      recoveryActions: ['continue', 'retry', 'fix'],
    },
  });
  client.emit('message', {
    type: 'turn_failed',
    runId: 'run-recover',
    message: '检查命令失败',
    errorCode: 'project_check_failed',
    recoveryActions: ['continue', 'retry', 'fix'],
  });
  const frame = await waitForFrame(view, /恢复任务/);
  assert.match(frame, /步骤 执行项目检查 · 已尝试2次/);
  assert.match(frame, /从checkpoint继续/);
  assert.match(frame, /重试本轮/);
  assert.match(frame, /分析错误并继续/);
  view.stdin.write('\r');
  await tick();
  assert.deepEqual(client.sent.at(-1), {
    type: 'resume_session',
    requestId: 'resume-2',
    runId: 'run-recover',
  });
  view.unmount();
});

test('terminal control reports never become composer text', () => {
  assert.equal(sanitizeComposerInput('\u001b[<64;12;8Mhello\u001b[<65;12;8M'), 'hello');
  assert.equal(sanitizeComposerInput('\u001b[M`!!world'), 'world');
  assert.equal(sanitizeComposerInput('\u001b]0;forged-title\u0007hello\u001b[2J'), 'hello');
  assert.equal(sanitizeComposerInput('a\u0000b\u001fc\r\nd'), 'abc\nd');
});

test('streaming keeps one Markdown block live and bounds the repainting tail', () => {
  const source = '第一段已经完成。\n\n第二段仍在生成';
  const boundary = stableMarkdownBoundary(source);
  assert.ok(boundary > 0 && boundary < source.length);
  assert.match(source.slice(0, boundary), /第一段已经完成/);
  assert.match(source.slice(boundary), /第二段仍在生成/);

  const preview = streamingPreview('长'.repeat(5000), 80, 24);
  assert.ok(preview.length < 1600, `streaming preview was not bounded: ${preview.length}`);
  assert.match(preview, /Ctrl\+O查看/);
});

test('streaming batches model deltas instead of repainting the whole conversation', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.15.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('生成流式报告');
  view.stdin.write('\r');
  await tick();
  const baseline = view.frames.length;
  const answer = Array.from({length: 80}, (_, index) => `第${index + 1}段完成。\n\n`).join('');
  for (let index = 0; index < 80; index += 1) {
    client.emit('message', {
      type: 'agent_event',
      event: {type: 'text_delta', text: `第${index + 1}段完成。\n\n`},
    });
    await new Promise(resolve => setTimeout(resolve, 2));
  }
  await new Promise(resolve => setTimeout(resolve, 120));
  const streamingFrames = view.frames.length - baseline;
  assert.ok(streamingFrames < 35, `streaming caused ${streamingFrames} redraws for 80 deltas`);

  client.emit('message', {type: 'turn_completed', answer});
  await tick();
  assert.match(view.lastFrame(), /第1段完成/);
  assert.match(view.lastFrame(), /第80段完成/);
  view.unmount();
});

test('composer owns editing keys without leaking global shortcuts into text', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.10.2" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('ab');
  view.stdin.write('\u001b[D');
  view.stdin.write('X');
  view.stdin.write('\u000f');
  await tick();
  assert.match(view.lastFrame(), /对话记录/);
  view.stdin.write('\u000f');
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).text, 'aXb');
  view.unmount();
});

test('composer undo restores edits, command completion and collapsed paste', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('检查日志');
  view.stdin.write('\x15');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /❯ 检查日志/);
  view.stdin.write('\x1a');
  await tick();
  assert.match(view.lastFrame(), /检查日志/);

  view.stdin.write('\x03');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /❯ 检查日志/);
  view.stdin.write('\x1a');
  await tick();
  assert.match(view.lastFrame(), /检查日志/);

  view.stdin.write('\x15');
  view.stdin.write('/he');
  await tick();
  view.stdin.write('\t');
  await tick();
  assert.match(view.lastFrame(), /❯ \/help/);
  view.stdin.write('\x1a');
  await tick();
  assert.match(view.lastFrame(), /❯ \/he/);

  view.stdin.write('\x15');
  const pasted = '堆栈一\n堆栈二\n堆栈三';
  view.stdin.write(`\x1b[200~${pasted}\x1b[201~`);
  await tick();
  assert.match(view.lastFrame(), /粘贴内容 #1 \+3行/);
  view.stdin.write('\x1a');
  await tick();
  assert.doesNotMatch(view.lastFrame(), /粘贴内容 #1 \+3行/);
  view.unmount();
});

test('composer supports multiline prompts and line-aware cursor movement', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);

  view.stdin.write('abc');
  view.stdin.write('\x1b[13;2u');
  view.stdin.write('xy');
  await tick();
  assert.match(view.lastFrame(), /abc/);
  assert.match(view.lastFrame(), /xy/);

  view.stdin.write('\x1b[A');
  view.stdin.write('X');
  view.stdin.write('\x1b[F');
  view.stdin.write('<');
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).text, 'abXc<\nxy');
  view.unmount();
});

test('empty Ctrl+C requires confirmation before exiting', async () => {
  const client = new ClosingClient();
  const view = render(<App client={client} version="0.17.0" />);
  await waitForFrame(view, /deepseek-chat/);
  view.stdin.write('\x03');
  await tick();
  assert.match(view.lastFrame(), /再按一次Ctrl\+C退出/);
  assert.equal(client.closed, 0);
  view.stdin.write('\x03');
  await tick();
  assert.equal(client.closed, 1);
});
