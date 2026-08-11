import {EventEmitter} from 'node:events';
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {render} from 'ink-testing-library';
import {
  App,
  resolveTerminalMode,
  sanitizeComposerInput,
  streamingPreview,
  thinkingStateForPhase,
} from '../src/app.jsx';
import {stableMarkdownBoundary} from '../src/markdown.jsx';

const tick = () => new Promise(resolve => setTimeout(resolve, 30));

test('thinking animation follows the active Agent phase and defaults to solving', () => {
  assert.equal(thinkingStateForPhase('模型正在分析'), 'solving');
  assert.equal(thinkingStateForPhase('正在联网搜索'), 'searching');
  assert.equal(thinkingStateForPhase('连接MCP服务'), 'connecting');
  assert.equal(thinkingStateForPhase('整理长期记忆'), 'listening');
  assert.equal(thinkingStateForPhase('正在激活Skill'), 'weaving');
  assert.equal(thinkingStateForPhase('读取工作区文件'), 'working');
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

class FakeClient extends EventEmitter {
  constructor({readyDelay = 0} = {}) {
    super();
    this.sent = [];
    this.readyDelay = readyDelay;
  }

  start() {
    const emitReady = () => this.emit('message', {
      type: 'ready',
      protocolVersion: 3,
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

test('Ink app renders command suggestions and streamed tool progress', async () => {
  const client = new FakeClient({readyDelay: 80});
  const view = render(<App client={client} version="0.9.0" />);
  await waitForFrame(view, /deepseek-chat/);
  assert.match(view.lastFrame(), /KnowFlow/);
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
  assert.match(view.lastFrame(), /run_sandbox_command/);
  assert.match(view.lastFrame(), /0\.4s/);

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
  assert.match(view.lastFrame(), /本次运行/);
  assert.match(view.lastFrame(), /~637 tokens/);
  assert.match(view.lastFrame(), /0\/2/);
  assert.match(view.lastFrame(), /模型正在分析/);
  assert.match(view.lastFrame(), /正在读取网页/);
  assert.match(view.lastFrame(), /[├└]/);

  client.emit('message', {
    type: 'agent_event',
    event: {
      type: 'text_delta',
      text: '回答第一段。\n\n回答第二段。\n\n',
    },
  });
  await new Promise(resolve => setTimeout(resolve, 180));
  const runningFrame = view.lastFrame();
  assert.ok(runningFrame.indexOf('本次运行') < runningFrame.indexOf('回答第一段。'));

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
        durationMs: 500,
      },
    });
  }
  client.emit('message', {
    type: 'turn_completed',
    runId: 'run-live-summary',
    answer: '检查完成。',
  });
  await tick();
  const completedFrame = view.lastFrame();
  assert.match(completedFrame, /2\/2/);
  assert.match(completedFrame, /已完成/);
  assert.ok(completedFrame.indexOf('本次运行') < completedFrame.indexOf('回答第一段。'));
  assert.doesNotMatch(completedFrame, /模型分析完成/);

  view.stdin.write('\u000f');
  await tick();
  view.stdin.write('\u0014');
  await tick();
  assert.match(view.lastFrame(), /模型分析完成/);
  assert.match(view.lastFrame(), /网页读取完成/);
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
    status: {webSearch: {configured: true, enabled: true}},
  });
  await tick();
  assert.match(view.lastFrame(), /web_search\s+已启用/);
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
  await tick();
  assert.match(view.lastFrame(), /1200\/96000 tokens/);

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
  await tick();
  assert.match(view.lastFrame(), /上下文压缩完成/);
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
  await tick();
  assert.match(view.lastFrame(), /2个文件已修改/);

  view.stdin.write('/resume');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'sessions');
  client.emit('message', {
    type: 'session_list',
    sessions: [{runId: 'run_restore', title: '恢复测试', status: 'failed'}],
  });
  await tick();
  assert.match(view.lastFrame(), /恢复测试 · 失败，可继续/);
  view.stdin.write('\r');
  await tick();
  assert.equal(client.sent.at(-1).type, 'resume_session');
  assert.equal(client.sent.at(-1).runId, 'run_restore');
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
  await tick();
  const frame = view.lastFrame();
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
  await tick();
  assert.match(view.lastFrame(), /进入浏览器后到达的新消息/);
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
  client.emit('message', {type: 'turn_completed', answer: '读取失败'});
  await tick();
  assert.match(view.lastFrame(), /Ctrl\+E查看错误与恢复操作/);

  view.stdin.write('\u0005');
  await tick();
  assert.match(view.lastFrame(), /工具详情/);
  assert.match(view.lastFrame(), /missing path/);
  assert.match(view.lastFrame(), /--password=\[已隐藏\]/);
  assert.doesNotMatch(view.lastFrame(), /hunter2|forged-title/);
  assert.match(view.lastFrame(), /R重试本轮/);
  assert.match(view.lastFrame(), /F让Agent分析错误并继续/);

  view.stdin.write('f');
  await tick();
  const recovery = client.sent.at(-1);
  assert.equal(recovery.type, 'submit');
  assert.match(recovery.text, /工具read_workspace_file执行失败/);
  assert.match(recovery.text, /避免重复同一无效调用/);
  assert.match(recovery.text, /读取缺失文件并继续/);
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
