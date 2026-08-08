import Fuse from 'fuse.js';

export const BUILTIN_COMMANDS = [
  {value: '/help', description: '查看命令与快捷键', source: 'builtin'},
  {value: '/new', description: '开始新会话', source: 'builtin'},
  {value: '/clear', description: '清空终端显示', source: 'builtin'},
  {value: '/model', description: '查看当前模型', source: 'builtin'},
  {value: '/status', description: '查看会话状态', source: 'builtin'},
  {value: '/workspace', description: '查看工作区边界', source: 'builtin'},
  {value: '/add-dir', description: '添加本次会话可访问的目录', source: 'builtin'},
  {value: '/cd', description: '切换工具执行目录', source: 'builtin'},
  {value: '/diff', description: '查看本轮文件改动', source: 'builtin'},
  {value: '/undo', description: '安全撤销最近一次文件操作', source: 'builtin'},
  {value: '/resume', description: '恢复本工作区的历史会话', source: 'builtin'},
  {value: '/continue', description: '从最近失败点继续', source: 'builtin'},
  {value: '/permissions', description: '切换权限模式', source: 'builtin'},
  {value: '/tools', description: '查看本地工具状态', source: 'builtin'},
  {value: '/tools:configure', description: '查看联网搜索配置方法', source: 'builtin'},
  {value: '/mcp', description: '查看MCP连接与工具', source: 'builtin'},
  {value: '/mcp:add', description: '查看添加MCP的方法', source: 'builtin'},
  {value: '/mcp:oauth', description: '查看MCP OAuth授权方法', source: 'builtin'},
  {value: '/skills', description: '查看已发现的Skills', source: 'builtin'},
  {value: '/skills:install', description: '查看安装Skill的方法', source: 'builtin'},
  {value: '/memory', description: '查看Mem0状态', source: 'builtin'},
  {value: '/memory:configure', description: '查看Mem0配置方法', source: 'builtin'},
  {value: '/doctor', description: '检查SRT沙箱依赖', source: 'builtin'},
  {value: '/tasks', description: '查看排队任务', source: 'builtin'},
  {value: '/retry', description: '选择重试工具或整轮任务', source: 'builtin'},
  {value: '/fix', description: '让Agent分析最近的工具错误并继续', source: 'builtin'},
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
      return sourceDelta;
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
