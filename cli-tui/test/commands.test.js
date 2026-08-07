import test from 'node:test';
import assert from 'node:assert/strict';
import {
  commandSuggestions,
  dynamicCommandTask,
  mergeCommands,
  resolveCommand,
} from '../src/commands.js';

test('commands merge dynamic entries and prefer exact or prefix matches', () => {
  const commands = mergeCommands([
    {value: '/tool:read-file', description: '读取文件', source: 'tool'},
  ]);
  assert.equal(commands[0].value, '/tool:read-file');
  assert.equal(commandSuggestions('/perm', commands)[0].value, '/permissions');
  assert.equal(commandSuggestions('/read', commands)[0].value, '/tool:read-file');
});

test('aliases resolve to canonical commands', () => {
  const commands = mergeCommands();
  assert.equal(resolveCommand('/quit', commands).command.value, '/exit');
});

test('dynamic commands become bounded natural-language tasks', () => {
  assert.equal(
    dynamicCommandTask('/tool:read-file', '读取README'),
    '使用工具read-file完成任务：读取README',
  );
});
