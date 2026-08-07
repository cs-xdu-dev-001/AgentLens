import {EventEmitter} from 'node:events';
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {render} from 'ink-testing-library';
import {App} from '../src/app.jsx';

const tick = () => new Promise(resolve => setTimeout(resolve, 30));

class FakeClient extends EventEmitter {
  constructor() {
    super();
    this.sent = [];
  }

  start() {
    queueMicrotask(() => this.emit('message', {
      type: 'ready',
      protocolVersion: 1,
      model: 'deepseek-chat',
      commands: [{value: '/tool:read-file', description: '读取文件', source: 'tool'}],
    }));
  }

  send(message) {
    this.sent.push(message);
    return true;
  }

  close() {}
}

test('Ink app renders command suggestions and streamed tool progress', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.9.0" />);
  await tick();
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

test('Ink app rejects unknown slash commands instead of sending them to the model', async () => {
  const client = new FakeClient();
  const view = render(<App client={client} version="0.10.0" />);
  await tick();
  view.stdin.write('/does-not-exist');
  await tick();
  view.stdin.write('\r');
  await tick();
  assert.match(view.lastFrame(), /未知命令/);
  assert.equal(client.sent.some(message => message.type === 'submit'), false);
  view.unmount();
});
