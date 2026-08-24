import Fuse from 'fuse.js';

export const BUILTIN_COMMANDS = [
  {value: '/help', description: '查看命令与快捷键', source: 'builtin', category: '会话', aliases: ['/?']},
  {value: '/new', description: '开始新会话', source: 'builtin', category: '会话'},
  {value: '/clear', description: '清空终端显示', source: 'builtin', category: '会话'},
  {value: '/model', description: '选择本轮对话使用的模型', source: 'builtin', category: '会话', argumentHint: '[list | use <ID> | config]'},
  {value: '/reasoning', description: '选择本次会话的推理强度', source: 'builtin', category: '会话', argumentHint: '[auto | low | medium | high | xhigh]'},
  {value: '/status', description: '查看会话状态', source: 'builtin', category: '会话'},
  {value: '/context', description: '查看模型上下文占用', source: 'builtin', category: '会话'},
  {value: '/compact', description: '压缩早期会话并保留结构化摘要', source: 'builtin', category: '会话', argumentHint: '[补充要求]'},
  {value: '/workspace', description: '查看工作区边界', source: 'builtin', category: '工作区'},
  {value: '/attach', description: '附加下一轮任务的工作区上下文', source: 'builtin', category: '工作区', argumentHint: '<文件或目录>'},
  {value: '/detach', description: '移除待发送的工作区上下文', source: 'builtin', category: '工作区', argumentHint: '[序号 | all]'},
  {value: '/add-dir', description: '添加本次会话可访问的目录', source: 'builtin', category: '工作区'},
  {value: '/cd', description: '切换工具执行目录', source: 'builtin', category: '工作区'},
  {value: '/diff', description: '查看本轮文件改动', source: 'builtin', category: '工作区'},
  {value: '/undo', description: '安全撤销最近一次文件操作', source: 'builtin', category: '工作区'},
  {value: '/resume', description: '恢复本工作区的历史会话', source: 'builtin', category: '会话'},
  {value: '/rename', description: '重命名当前会话', source: 'builtin', category: '会话', argumentHint: '<新名称>'},
  {value: '/branch', description: '从当前会话创建独立分支', source: 'builtin', category: '会话', aliases: ['/fork'], argumentHint: '[名称]'},
  {value: '/rewind', description: '回到历史问题并从那里继续', source: 'builtin', category: '会话', aliases: ['/checkpoint']},
  {value: '/export', description: '把当前会话导出为Markdown', source: 'builtin', category: '会话', argumentHint: '[文件名]'},
  {value: '/search', description: '搜索当前对话中实际显示的内容', source: 'builtin', category: '会话', aliases: ['/find'], argumentHint: '[关键词]'},
  {value: '/history', description: '搜索或清空本工作区的输入历史', source: 'builtin', category: '会话', argumentHint: '[关键词 | clear]'},
  {value: '/edit', description: '取回上一条任务继续修改', source: 'builtin', category: '会话'},
  {value: '/copy', description: '复制最近回答或其中的代码块', source: 'builtin', category: '会话', argumentHint: '[answer | code [序号]]'},
  {value: '/continue', description: '从最近失败点继续', source: 'builtin', category: '恢复'},
  {value: '/plan', description: '切换计划模式，或只为指定任务制定计划', source: 'builtin', category: '安全', argumentHint: '[任务]'},
  {value: '/permissions', description: '切换权限模式或管理工具规则', source: 'builtin', category: '安全', aliases: ['/allowed-tools'], argumentHint: '[rules | allow|ask|deny <工具名>]'},
  {value: '/tools', description: '查看本地工具状态', source: 'builtin', category: '扩展'},
  {value: '/tools:configure', description: '查看联网搜索配置方法', source: 'builtin', category: '扩展'},
  {value: '/mcp', description: '查看MCP连接与工具', source: 'builtin', category: '扩展'},
  {value: '/mcp:add', description: '查看添加MCP的方法', source: 'builtin', category: '扩展'},
  {value: '/mcp:oauth', description: '查看MCP OAuth授权方法', source: 'builtin', category: '扩展'},
  {value: '/skills', description: '查看已发现的Skills', source: 'builtin', category: '扩展'},
  {value: '/skills:install', description: '查看安装Skill的方法', source: 'builtin', category: '扩展'},
  {value: '/memory', description: '查看Mem0状态', source: 'builtin', category: '扩展'},
  {value: '/memory:configure', description: '查看Mem0配置方法', source: 'builtin', category: '扩展'},
  {value: '/doctor', description: '检查SRT沙箱依赖', source: 'builtin', category: '安全'},
  {value: '/feedback', description: '复制不含对话和凭据的诊断摘要', source: 'builtin', category: '帮助', aliases: ['/bug']},
  {value: '/update', description: '在TUI内更新AgentLens CLI', source: 'builtin', category: '帮助'},
  {value: '/version', description: '查看CLI与运行协议版本', source: 'builtin', category: '帮助'},
  {value: '/tasks', description: '查看和调整排队任务', source: 'builtin', category: '运行', argumentHint: '[list | add <now|next|later> <任务> | remove <序号> | priority <序号> <级别> | clear]'},
  {value: '/retry', description: '选择重试工具或整轮任务', source: 'builtin', category: '恢复'},
  {value: '/fix', description: '让Agent分析最近的工具错误并继续', source: 'builtin', category: '恢复'},
  {value: '/exit', description: '退出AgentLens', source: 'builtin', category: '会话', aliases: ['/quit']},
];

export function commandCategoryLabel(command) {
  if (command?.category) return command.category;
  return {tool: '工具', skill: 'Skill', mcp: 'MCP'}[command?.source] || '自定义';
}

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

export function commandArgumentHint(input, commands) {
  const value = String(input ?? '');
  if (!value.endsWith(' ')) return '';
  const resolved = resolveCommand(value, commands);
  if (!resolved || resolved.args) return '';
  return String(resolved.command.argumentHint ?? '').trim();
}

export function dynamicCommandTask(value, args) {
  const [source, name] = value.slice(1).split(':', 2);
  const labels = {tool: '工具', skill: 'Skill', mcp: 'MCP服务'};
  return `使用${labels[source] ?? source}${name}完成任务：${args || '先说明它能做什么，并等待我的具体要求。'}`;
}
