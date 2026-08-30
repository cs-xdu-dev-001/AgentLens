import Fuse from "fuse.js";

export const WEB_COMPOSER_COMMANDS = Object.freeze([
  {
    value: "/help",
    aliases: ["/?"],
    label: "命令帮助",
    description: "浏览当前可用命令与Skills",
    category: "会话",
    action: "help",
  },
  {
    value: "/new",
    label: "新建会话",
    description: "开始一个空白任务",
    category: "会话",
    action: "new-chat",
  },
  {
    value: "/resume",
    label: "恢复会话",
    description: "搜索并打开历史任务",
    category: "会话",
    action: "session-resume",
  },
  {
    value: "/rename",
    label: "重命名会话",
    description: "修改当前任务名称，可在命令后直接输入新名称",
    category: "会话",
    action: "session-rename",
  },
  {
    value: "/branch",
    aliases: ["/fork"],
    label: "创建会话分支",
    description: "复制当前上下文并在独立会话中继续",
    category: "会话",
    action: "session-branch",
  },
  {
    value: "/export",
    label: "导出会话",
    description: "下载不含内部trace的Markdown记录",
    category: "会话",
    action: "session-export",
  },
  {
    value: "/search",
    aliases: ["/find"],
    label: "搜索对话",
    description: "查找当前对话中实际显示的内容",
    category: "会话",
    action: "transcript-search",
  },
  {
    value: "/copy",
    label: "复制运行内容",
    description: "复制回答、代码块、工具输出或当前会话记录",
    category: "会话",
    action: "message-copy",
    argumentHint: "[answer | code [序号] | tool [序号|all] | transcript]",
  },
  {
    value: "/edit",
    label: "编辑上一问题",
    description: "把最近一条问题放回输入框",
    category: "会话",
    action: "message-edit",
  },
  {
    value: "/rewind",
    label: "从历史继续",
    description: "从最近一个可回退问题创建会话分支",
    category: "会话",
    action: "message-rewind",
  },
  {
    value: "/model",
    label: "切换模型",
    description: "选择本轮对话使用的模型",
    category: "会话",
    action: "model",
  },
  {
    value: "/reasoning",
    label: "推理强度",
    description: "选择自动、快速、标准、深入或最高",
    category: "会话",
    action: "reasoning",
  },
  {
    value: "/status",
    label: "会话状态",
    description: "查看模型、推理强度与上下文预算",
    category: "会话",
    action: "status",
  },
  {
    value: "/context",
    label: "上下文预算",
    description: "查看本轮已用、剩余和安全裁剪状态",
    category: "会话",
    action: "context",
  },
  {
    value: "/compact",
    label: "压缩上下文",
    description: "摘要早期对话并保留完整聊天记录",
    category: "会话",
    action: "session-compact",
  },
  {
    value: "/plan",
    label: "计划模式",
    description: "只分析并制定计划，不执行修改",
    category: "会话",
    action: "plan",
  },
  {
    value: "/permissions",
    label: "权限模式",
    description: "选择计划、询问、自动编辑或完全访问",
    category: "会话",
    action: "permissions",
  },
  {
    value: "/tasks",
    label: "运行详情",
    description: "打开当前任务、工具与恢复操作，Alt+E直达过程",
    category: "会话",
    action: "tasks",
  },
  {
    value: "/continue",
    label: "继续任务",
    description: "从checkpoint继续失败任务或恢复待发送队列",
    category: "恢复",
    action: "continue",
    when: "continue",
  },
  {
    value: "/retry",
    label: "重新运行本轮",
    description: "从头重新执行失败的本轮任务",
    category: "恢复",
    action: "retry",
    when: "retry",
  },
  {
    value: "/fix",
    label: "分析错误并继续",
    description: "让Agent分析最近的工具错误并继续执行",
    category: "恢复",
    action: "fix",
    when: "fix",
  },
  {
    value: "/knowledge",
    label: "知识库",
    description: "管理文档与检索设置",
    category: "工作区",
    action: "knowledge",
  },
  {
    value: "/workspace",
    label: "工作区",
    description: "查看Agent可访问的项目边界",
    category: "工作区",
    action: "workspace",
  },
  {
    value: "/diff",
    label: "查看文件变更",
    description: "打开最近任务的文件差异，Alt+G直达变更",
    category: "工作区",
    action: "artifacts-diff",
  },
  {
    value: "/undo",
    label: "撤销文件修改",
    description: "打开最近任务并选择要安全撤销的修改",
    category: "工作区",
    action: "artifacts-undo",
  },
  {
    value: "/tools",
    label: "工具",
    description: "配置联网搜索与本地工具",
    category: "扩展",
    action: "tools",
  },
  {
    value: "/mcp",
    label: "MCP",
    description: "管理MCP服务与OAuth连接",
    category: "扩展",
    action: "tools",
  },
  {
    value: "/skills",
    label: "Skills",
    description: "安装和管理个人Skills",
    category: "扩展",
    action: "skills",
  },
  {
    value: "/memory",
    label: "长期记忆",
    description: "查看和管理Mem0记忆",
    category: "扩展",
    action: "memory",
  },
  {
    value: "/settings",
    label: "模型设置",
    description: "管理模型API与默认配置",
    category: "设置",
    action: "settings",
  },
  {
    value: "/feedback",
    aliases: ["/bug"],
    label: "复制诊断",
    description: "复制不含对话、工具参数和凭据的运行摘要",
    category: "帮助",
    action: "feedback",
  },
  {
    value: "/stop",
    label: "停止任务",
    description: "停止当前Agent运行",
    category: "运行中",
    action: "stop",
    when: "sending",
  },
]);

export function composerCommandSuggestions(
  query,
  {
    sending = false,
    recoveryActions = [],
    queuePaused = false,
    usage = {},
  } = {},
) {
  const recoverable = new Set(Array.isArray(recoveryActions) ? recoveryActions : []);
  const available = WEB_COMPOSER_COMMANDS.filter((command) => {
    if (command.when === "sending" && !sending) return false;
    if (command.when === "continue" && !recoverable.has("continue") && !queuePaused) return false;
    if (command.when === "retry" && !recoverable.has("retry")) return false;
    if (command.when === "fix" && !recoverable.has("fix")) return false;
    return true;
  });
  return searchComposerCommands(available, query, usage);
}

// The global palette and slash menu share one catalog and ranking policy.
export function searchComposerCommands(available, query, usage = {}) {
  const normalized = String(query || "").trim().replace(/^\//, "").toLocaleLowerCase();
  if (!normalized) {
    return [...available].sort((left, right) => (
      (Number(usage[right.value]) || 0) - (Number(usage[left.value]) || 0)
    ));
  }

  const names = (command) => [command.value, ...(command.aliases || [])]
    .map((value) => value.slice(1).toLocaleLowerCase());
  const exact = available.filter((command) => names(command).includes(normalized));
  const prefixed = available.filter((command) => (
    !exact.includes(command)
    && names(command).some((value) => value.startsWith(normalized))
  ));
  const remaining = available.filter((command) => (
    !exact.includes(command) && !prefixed.includes(command)
  ));
  const fuse = new Fuse(remaining.map((command) => ({
    ...command,
    commandName: names(command).join(" "),
    aliasesText: (command.aliases || []).join(" "),
  })), {
    threshold: 0.34,
    location: 0,
    distance: 100,
    ignoreLocation: true,
    keys: [
      { name: "commandName", weight: 4 },
      { name: "label", weight: 2 },
      { name: "aliasesText", weight: 2 },
      { name: "description", weight: 1 },
      { name: "category", weight: 0.5 },
    ],
  });
  return [...exact, ...prefixed, ...fuse.search(normalized).map((result) => result.item)];
}

export function resolveComposerCommand(value) {
  return parseComposerCommand(value)?.command || null;
}

export function parseComposerCommand(value) {
  const trimmed = String(value || "").trim();
  if (!trimmed.startsWith("/")) return null;
  const [rawName, ...rest] = trimmed.split(/\s+/);
  const normalized = rawName.toLocaleLowerCase();
  const command = WEB_COMPOSER_COMMANDS.find((item) => (
    item.value === normalized || item.aliases?.includes(normalized)
  ));
  return command ? { command, args: rest.join(" ").trim() } : null;
}
