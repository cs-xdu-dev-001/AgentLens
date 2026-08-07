import Fuse from 'fuse.js';

export const BUILTIN_COMMANDS = [
  {value: '/help', description: '查看命令与快捷键', source: 'builtin'},
  {value: '/new', description: '开始新会话', source: 'builtin'},
  {value: '/clear', description: '清空终端显示', source: 'builtin'},
  {value: '/model', description: '查看当前模型', source: 'builtin'},
  {value: '/status', description: '查看会话状态', source: 'builtin'},
  {value: '/permissions', description: '切换权限模式', source: 'builtin'},
  {value: '/doctor', description: '检查SRT沙箱依赖', source: 'builtin'},
  {value: '/tasks', description: '查看排队任务', source: 'builtin'},
  {value: '/retry', description: '重试上一个问题', source: 'builtin'},
  {value: '/exit', description: '退出KnowFlow', source: 'builtin', aliases: ['/quit']},
];

export function mergeCommands(dynamicCommands = []) {
  const seen = new Set();
  return [...dynamicCommands, ...BUILTIN_COMMANDS].filter(command => {
    const value = String(command?.value ?? '').trim().toLowerCase();
    if (!value.startsWith('/') || seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function commandParts(command) {
  return command.value.slice(1).split(/[:_-]/g).filter(Boolean).join(' ');
}

export function commandSuggestions(input, commands, usage = {}) {
  const query = String(input ?? '').trimStart().toLowerCase();
  if (!query.startsWith('/') || /\s/.test(query)) return [];
  if (query === '/') {
    return [...commands].sort((left, right) => {
      const usageDelta = (usage[right.value] ?? 0) - (usage[left.value] ?? 0);
      if (usageDelta) return usageDelta;
      const sourceDelta = Number(left.source !== 'builtin') - Number(right.source !== 'builtin');
      return sourceDelta || left.value.localeCompare(right.value);
    });
  }
  const exact = command => command.value === query || command.aliases?.includes(query);
  const prefix = command => command.value.startsWith(query)
    || command.aliases?.some(alias => alias.startsWith(query));
  const direct = commands.filter(exact);
  const prefixed = commands
    .filter(command => !exact(command) && prefix(command))
    .sort((left, right) => left.value.length - right.value.length || left.value.localeCompare(right.value));
  const remaining = commands.filter(command => !direct.includes(command) && !prefixed.includes(command));
  const fuse = new Fuse(remaining.map(command => ({
    ...command,
    commandName: command.value.slice(1),
    partKey: commandParts(command),
    aliasKey: (command.aliases ?? []).join(' '),
  })), {
    threshold: 0.3,
    location: 0,
    distance: 100,
    includeScore: true,
    keys: [
      {name: 'commandName', weight: 3},
      {name: 'partKey', weight: 2},
      {name: 'aliasKey', weight: 2},
      {name: 'description', weight: 0.5},
    ],
  });
  return [...direct, ...prefixed, ...fuse.search(query.slice(1)).map(result => result.item)];
}

export function resolveCommand(input, commands) {
  const trimmed = String(input ?? '').trim();
  const [rawName, ...rest] = trimmed.split(/\s+/);
  const normalized = rawName.toLowerCase();
  const command = commands.find(item => item.value === normalized || item.aliases?.includes(normalized));
  return command ? {command, args: rest.join(' ')} : null;
}

export function dynamicCommandTask(value, args) {
  const [source, name] = value.slice(1).split(':', 2);
  const labels = {tool: '工具', skill: 'Skill', mcp: 'MCP服务'};
  return `使用${labels[source] ?? source}${name}完成任务：${args || '先说明它能做什么，并等待我的具体要求。'}`;
}
