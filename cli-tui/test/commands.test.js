import test from 'node:test';
import assert from 'node:assert/strict';
import {
  commandArgumentHint,
  commandCategoryLabel,
  commandSuggestions,
  dynamicCommandTask,
  mergeCommands,
  resolveCommand,
} from '../src/commands.js';
import {
  agentEventName,
  buildDiffPresentation,
  compactTaskRows,
  createRunProjection,
  defaultTaskNavigationIndex,
  projectRunEvent,
  redact,
  referenceDisplayLabel,
  taskOperationRow,
  userFacingErrorMessage,
  verificationToolCallId,
  verificationRows,
} from '../src/protocol.js';
import {
  applyFileMention,
  fileMentionAtCursor,
  longestSuggestionPrefix,
  resolveWorkspaceAttachment,
  workspaceFileSuggestions,
} from '../src/fileSuggestions.js';

test('file mentions follow Claude Code style fuzzy completion and quoting', () => {
  const input = '检查 @app';
  const mention = fileMentionAtCursor(input, input.length);
  assert.deepEqual(mention, {start: 3, end: 7, token: '@app', query: 'app', quoted: false});
  const suggestions = workspaceFileSuggestions(
    ['src/', 'src/app.jsx', 'src/app test.jsx', '.env', 'node_modules/pkg/index.js'],
    mention,
  );
  assert.equal(suggestions[0].path, 'src/app.jsx');
  assert.doesNotMatch(suggestions.map(item => item.path).join('\n'), /\.env/);
  const applied = applyFileMention(input, mention, 'src/app test.jsx');
  assert.deepEqual(applied, {value: '检查 @"src/app test.jsx" ', cursor: 23});
  assert.equal(longestSuggestionPrefix([
    {path: 'src/app.jsx'},
    {path: 'src/app.test.jsx'},
  ]), 'src/app.');
});

test('workspace attachments resolve only indexed non-sensitive relative paths', () => {
  const paths = ['src/', 'src/app.jsx', 'docs/product brief.md', '.env'];
  assert.equal(resolveWorkspaceAttachment(paths, '@src\\app.jsx'), 'src/app.jsx');
  assert.equal(resolveWorkspaceAttachment(paths, '@"docs/product brief.md"'), 'docs/product brief.md');
  assert.equal(resolveWorkspaceAttachment(paths, '../secret.txt'), '');
  assert.equal(resolveWorkspaceAttachment(paths, '/etc/passwd'), '');
  assert.equal(resolveWorkspaceAttachment(paths, '.env'), '');
});

test('public errors hide upstream account identifiers and alternate key prefixes', () => {
  const source = 'Your account org-8242d004acb748ada9255f6d42f4dc23<ak-fbzbf9goi431l1d8rrx1> reached max RPM';
  const value = redact(source);
  assert.doesNotMatch(value, /8242d004acb748ada9255f6d42f4dc23|fbzbf9goi431l1d8rrx1/);
  assert.match(value, /org-\[已隐藏\]/);
});

test('rate-limit failures use a concise public recovery message', () => {
  const value = userFacingErrorMessage(
    'HTTP 429: rate_limit_reached_error: Your account org-secret<ak-secret> reached organization max RPM: 3',
  );
  assert.equal(value, '上游模型请求过于频繁（HTTP 429），自动重试后仍未恢复。');
  assert.doesNotMatch(value, /org-secret|ak-secret|max RPM/);
});

test('completed runs focus delivery while active and failed runs focus execution', () => {
  const items = [
    {key: 'step:inspect', type: 'step', row: {status: 'completed'}},
    {key: 'verification:test', type: 'verification', row: {status: 'passed'}},
    {key: 'artifact:report', type: 'artifact', row: {path: 'report.md'}},
    {key: 'reference:source', type: 'reference', row: {url: 'https://example.com'}},
  ];
  assert.equal(defaultTaskNavigationIndex(items, {running: false}), 2);
  assert.equal(defaultTaskNavigationIndex(items, {running: true}), 0);
  assert.equal(defaultTaskNavigationIndex([
    {key: 'step:failed', type: 'step', row: {status: 'failed'}},
    ...items,
  ], {running: false}), 0);
  assert.equal(defaultTaskNavigationIndex([
    {key: 'reference:source', type: 'reference', row: {url: 'https://example.com'}},
  ], {running: false}), 0);
});

test('commands merge dynamic entries and prefer exact or prefix matches', () => {
  const commands = mergeCommands([
    {value: '/tool:read-file', description: '读取文件', source: 'tool'},
  ]);
  assert.equal(commands[0].value, '/tool:read-file');
  assert.equal(commandSuggestions('/perm', commands)[0].value, '/permissions');
  assert.equal(commandSuggestions('/pla', commands)[0].value, '/plan');
  assert.equal(commandSuggestions('/read', commands)[0].value, '/tool:read-file');
  assert.equal(commandCategoryLabel(commandSuggestions('/perm', commands)[0]), '安全');
  assert.equal(commandCategoryLabel(commands[0]), '工具');
});

test('aliases resolve to canonical commands', () => {
  const commands = mergeCommands();
  assert.equal(resolveCommand('/quit', commands).command.value, '/exit');
  assert.equal(resolveCommand('/edit', commands).command.description, '取回上一条任务继续修改');
  assert.equal(resolveCommand('/copy code 2', commands).command.value, '/copy');
  assert.equal(resolveCommand('/fork 方案B', commands).command.value, '/branch');
  assert.equal(resolveCommand('/checkpoint', commands).command.value, '/rewind');
  assert.equal(resolveCommand('/find 失败', commands).command.value, '/search');
  assert.equal(resolveCommand('/update', commands).command.description, '在TUI内更新AgentLens CLI');
  assert.equal(resolveCommand('/attach README.md', commands).command.category, '工作区');
  assert.equal(resolveCommand('/detach all', commands).command.value, '/detach');
  assert.equal(resolveCommand('/version', commands).command.category, '帮助');
});

test('commands expose argument guidance only after selecting the command', () => {
  const commands = mergeCommands();
  assert.equal(commandArgumentHint('/model', commands), '');
  assert.equal(commandArgumentHint('/model ', commands), '[list | use <ID> | config]');
  assert.equal(commandArgumentHint('/model use', commands), '');
  assert.equal(commandArgumentHint('/copy ', commands), '[answer | code [序号]]');
  assert.equal(commandArgumentHint('/rename ', commands), '<新名称>');
  assert.equal(commandArgumentHint('/branch ', commands), '[名称]');
  assert.equal(commandArgumentHint('/export ', commands), '[文件名]');
  assert.equal(commandArgumentHint('/search ', commands), '[关键词]');
  assert.equal(commandArgumentHint('/attach ', commands), '<文件或目录>');
  assert.equal(commandArgumentHint('/detach ', commands), '[序号 | all]');
  assert.equal(commandArgumentHint('/help ', commands), '');
});

test('dynamic commands become bounded natural-language tasks', () => {
  assert.equal(
    dynamicCommandTask('/tool:read-file', '读取README'),
    '使用工具read-file完成任务：读取README',
  );
});

test('agent events prefer the unified name and retain legacy fallbacks', () => {
  assert.equal(agentEventName({eventName: 'tool.failed', type: 'tool_result'}), 'tool.failed');
  assert.equal(agentEventName({type: 'tool_result', status: 'failed'}), 'tool.failed');
  assert.equal(agentEventName({type: 'agent_step', status: 'success'}), 'step.completed');
});

test('run summaries keep progress, usage and status identical across clients', () => {
  const projection = projectRunEvent(createRunProjection(), {
    eventName: 'run.updated',
    runId: 'run_summary',
    runSummary: {
      runId: 'run_summary',
      status: 'running',
      headline: '统一摘要 token=SECRET_VALUE',
      completedSteps: 2,
      totalSteps: 5,
      progressPercent: 40,
      toolCalls: 3,
      totalTokens: 1200,
    },
  });
  assert.equal(projection.runSummary.runId, 'run_summary');
  assert.equal(projection.runSummary.completedSteps, 2);
  assert.equal(projection.runSummary.totalSteps, 5);
  assert.equal(projection.runSummary.progressPercent, 40);
  assert.equal(projection.runSummary.toolCalls, 3);
  assert.equal(projection.runSummary.totalTokens, 1200);
  assert.doesNotMatch(projection.runSummary.headline, /SECRET_VALUE/);
});

test('model retry projection exposes a live deadline and clears on progress', () => {
  const startedAt = Date.now();
  const retrying = projectRunEvent(createRunProjection(), {
    eventName: 'model.retrying',
    retryAttempt: 2,
    maxRetries: 3,
    retryInMs: 10_000,
    statusCode: 429,
  });
  assert.equal(retrying.modelRetry.reason, '模型限流');
  assert.equal(retrying.modelRetry.attempt, 2);
  assert.equal(retrying.modelRetry.maxRetries, 3);
  assert.ok(retrying.modelRetry.retryAt >= startedAt + 10_000);
  assert.ok(retrying.modelRetry.retryAt <= Date.now() + 10_000);
  const resumed = projectRunEvent(retrying, {eventName: 'message.delta', content: '继续'});
  assert.equal(resumed.modelRetry, null);
});

test('reference artifacts stay out of file delivery and hide sensitive URL parameters', () => {
  const projection = projectRunEvent(createRunProjection(), {
    type: 'reference',
    eventId: 'ref-1',
    artifactType: 'reference',
    url: 'https://example.com/report?q=private&token=SECRET#section',
    score: 0.87,
  });
  assert.equal(projection.artifacts.length, 0);
  assert.equal(projection.references.length, 1);
  assert.equal(projection.references[0].url, 'https://example.com/report');
  assert.equal(projection.references[0].displayLabel, 'example.com/report');
  assert.equal(projection.references[0].sourceType, 'web');
  assert.equal(referenceDisplayLabel(projection.references[0]), 'example.com/report');
  assert.doesNotMatch(JSON.stringify(projection.references), /private|SECRET|section/);
});

test('knowledge references use protocol labels and bounded redacted excerpts', () => {
  const projection = projectRunEvent(createRunProjection(), {
    type: 'reference',
    documentId: 7,
    chunkId: 'chunk-9',
    filename: '安全报告.pdf',
    score: 0.87,
    content: `第一行\n第二行 token=SECRET_VALUE ${'x'.repeat(800)}`,
  });
  assert.equal(projection.references.length, 1);
  assert.equal(projection.references[0].displayLabel, '安全报告.pdf');
  assert.equal(projection.references[0].sourceType, 'knowledge');
  assert.equal(projection.references[0].documentId, '7');
  assert.equal(projection.references[0].content, undefined);
  assert.match(projection.references[0].excerpt, /^第一行 第二行 token=\[已隐藏\]/);
  assert.ok(projection.references[0].excerpt.length <= 600);
});

test('external delivery artifacts also hide sensitive URL parameters', () => {
  const projection = projectRunEvent(createRunProjection(), {
    eventName: 'artifact.created',
    eventId: 'artifact-1',
    artifactType: 'link',
    url: 'https://example.com/export?signature=SECRET#download',
    title: '导出结果',
  });
  assert.equal(projection.artifacts.length, 1);
  assert.equal(projection.artifacts[0].url, 'https://example.com/export');
  assert.doesNotMatch(JSON.stringify(projection.artifacts), /SECRET|signature|download/);
});

test('task presentation compacts repeated low-level tool steps without losing counts', () => {
  const rows = compactTaskRows([
    {id: 'model', kind: 'model', name: 'model_completion', title: '模型步骤完成', status: 'success'},
    {id: 'search-1', kind: 'tool', name: 'web_search', title: '联网搜索完成', status: 'success', durationMs: 100},
    {id: 'search-2', kind: 'tool', name: 'web_search', title: '联网搜索完成', status: 'success', durationMs: 200},
    {id: 'search-3', kind: 'tool', name: 'web_search', title: '联网搜索完成', status: 'success', durationMs: 300},
  ]);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[1], {
    id: 'search-1',
    kind: 'tool',
    name: 'web_search',
    title: '联网搜索完成',
    status: 'success',
    durationMs: 600,
    repeatCount: 3,
  });
});

test('task operations use user-facing targets and never merge different files', () => {
  const operations = [
    {id: 'write-a', kind: 'workspace', name: 'write_workspace_file', status: 'success', inputSummary: {path: 'src/a.py'}, outputSummary: {writtenBytes: 12}},
    {id: 'write-b', kind: 'workspace', name: 'write_workspace_file', status: 'success', inputSummary: {path: 'src/b.py'}, outputSummary: {writtenBytes: 20}},
    {id: 'fetch', kind: 'tool', name: 'web_fetch', status: 'running', inputSummary: {url: 'https://example.com/news?token=SECRET'}},
    {id: 'model', kind: 'model', name: 'model_completion', status: 'success'},
  ].map(taskOperationRow).filter(Boolean);
  const compacted = compactTaskRows(operations);
  assert.equal(compacted.length, 3);
  assert.equal(compacted[0].title, '已更新 src/a.py');
  assert.equal(compacted[0].outcome, '12B');
  assert.equal(compacted[1].title, '已更新 src/b.py');
  assert.equal(compacted[2].title, '正在读取网页 example.com/news');
  assert.doesNotMatch(JSON.stringify(compacted), /SECRET/);
});

test('verification rows only expose real terminal checks and hide raw commands', () => {
  const rows = verificationRows([
    {
      stepId: 'test-ok',
      kind: 'sandbox',
      name: 'run_sandbox_command',
      status: 'success',
      durationMs: 1200,
      inputSummary: {command: 'npm test -- --token SECRET'},
      outputSummary: {exit_code: 0},
    },
    {
      stepId: 'build-failed',
      kind: 'sandbox',
      name: 'run_sandbox_command',
      status: 'failed',
      inputSummary: {command: 'npm run build'},
      outputSummary: {exit_code: 2},
    },
    {
      stepId: 'not-a-check',
      kind: 'sandbox',
      name: 'run_sandbox_command',
      status: 'success',
      inputSummary: {command: 'cat README.md'},
    },
  ]);
  assert.deepEqual(rows, [
    {id: 'test-ok', durationMs: 1200, exitCode: 0, label: '测试', status: 'passed', statusLabel: '通过', tool: 'npm test'},
    {id: 'build-failed', durationMs: null, exitCode: 2, label: '构建', status: 'failed', statusLabel: '失败', tool: 'npm run build'},
  ]);
  assert.doesNotMatch(JSON.stringify(rows), /SECRET|token/);

  const protocolRows = verificationRows(
    [{stepId: 'legacy', name: 'run_sandbox_command', status: 'success', inputSummary: {command: 'npm test -- --token SECRET'}}],
    [{
      id: 'verification:protocol',
      kind: 'check',
      tool: 'git_diff_check',
      status: 'passed',
      exitCode: 0,
      durationMs: 90,
      command: 'git diff --check --token SECRET',
    }],
  );
  assert.deepEqual(protocolRows, [
    {id: 'verification:protocol', durationMs: 90, exitCode: 0, label: '差异检查', status: 'passed', statusLabel: '通过', tool: 'git diff --check'},
  ]);
  assert.doesNotMatch(JSON.stringify(protocolRows), /SECRET|token|command/);
  assert.equal(verificationToolCallId(protocolRows[0]), 'protocol');
  assert.equal(verificationToolCallId({id: 'call-build'}), 'call-build');
});

test('unified diff presentation preserves hunk line numbers and semantic rows', () => {
  const rows = buildDiffPresentation([
    'diff --git a/src/app.js b/src/app.js',
    '--- a/src/app.js',
    '+++ b/src/app.js',
    '@@ -3,2 +3,3 @@',
    ' keep',
    '-old value',
    '+new value',
    '+extra line',
  ].join('\n'));
  assert.deepEqual(rows.map(row => ({
    kind: row.kind,
    oldLine: row.oldLine,
    newLine: row.newLine,
    text: row.text,
  })), [
    {kind: 'meta', oldLine: null, newLine: null, text: 'diff --git a/src/app.js b/src/app.js'},
    {kind: 'meta', oldLine: null, newLine: null, text: '--- a/src/app.js'},
    {kind: 'meta', oldLine: null, newLine: null, text: '+++ b/src/app.js'},
    {kind: 'hunk', oldLine: null, newLine: null, text: '@@ -3,2 +3,3 @@'},
    {kind: 'context', oldLine: 3, newLine: 3, text: ' keep'},
    {kind: 'remove', oldLine: 4, newLine: null, text: '-old value'},
    {kind: 'add', oldLine: null, newLine: 4, text: '+new value'},
    {kind: 'add', oldLine: null, newLine: 5, text: '+extra line'},
  ]);
});
