export const WEB_COMPOSER_COMMANDS = Object.freeze([
  {
    value: "/new",
    label: "新建会话",
    description: "开始一个空白任务",
    category: "会话",
    action: "new-chat",
  },
  {
    value: "/model",
    label: "切换模型",
    description: "选择本轮对话使用的模型",
    category: "会话",
    action: "model",
  },
  {
    value: "/permissions",
    label: "权限模式",
    description: "选择询问、自动编辑或完全访问",
    category: "会话",
    action: "permissions",
  },
  {
    value: "/tasks",
    label: "运行详情",
    description: "打开当前任务、工具与恢复操作",
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
  { sending = false, recoveryActions = [], queuePaused = false } = {},
) {
  const normalized = String(query || "").trim().toLocaleLowerCase();
  const recoverable = new Set(Array.isArray(recoveryActions) ? recoveryActions : []);
  return WEB_COMPOSER_COMMANDS.filter((command) => {
    if (command.when === "sending" && !sending) return false;
    if (command.when === "continue" && !recoverable.has("continue") && !queuePaused) return false;
    if (command.when === "retry" && !recoverable.has("retry")) return false;
    if (!normalized) return true;
    return [command.value.slice(1), command.label, command.description, command.category]
      .some((value) => String(value).toLocaleLowerCase().includes(normalized));
  });
}

export function resolveComposerCommand(value) {
  const normalized = String(value || "").trim().toLocaleLowerCase();
  return WEB_COMPOSER_COMMANDS.find((command) => command.value === normalized) || null;
}
