const kindLabels = {
  model: "MODEL",
  tool: "TOOL",
  mcp: "MCP",
  skill: "SKILL",
  agent: "AGENT",
  system: "SYS",
  approval: "APPROVAL",
  memory: "MEMORY",
};

const nameLabels = {
  agent_run: "Agent",
  model_completion: "模型",
  web_search: "联网搜索",
  memory_recall: "记忆召回",
  memory_write: "记忆整理",
};

const statusLabels = {
  waiting: "等待中",
  running: "运行中",
  success: "已完成",
  completed: "已完成",
  failed: "失败",
  error: "失败",
  cancelled: "已取消",
};

const skillSourceLabels = {
  builtin: "内置",
  personal: "个人",
  github: "个人",
  upload: "个人",
};

export function safeText(value, fallback = "") {
  if (
    typeof value === "string"
    || typeof value === "number"
    || typeof value === "boolean"
  ) {
    return String(value);
  }
  return fallback;
}

function mappedLabel(labels, value) {
  const key = safeText(value);
  return Object.prototype.hasOwnProperty.call(labels, key)
    ? safeText(labels[key])
    : "";
}

function skillDisplayName(step) {
  const value = step?.details?.displayName;
  return typeof value === "string" && value.trim()
    ? value.trim()
    : "Skill";
}

function safeDependencyNames(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function skillDetailsForDisplay(step) {
  const details = (
    step?.details
    && typeof step.details === "object"
    && !Array.isArray(step.details)
  )
    ? step.details
    : {};
  const version = (
    typeof details.version === "string"
    && details.version.trim()
  )
    ? details.version.trim()
    : "无";
  const sourceKind = mappedLabel(
    skillSourceLabels,
    details.sourceKind,
  );
  return {
    displayName: skillDisplayName(step),
    version,
    sourceKind: sourceKind || "个人",
    requiredTools: safeDependencyNames(details.requiredTools),
    requiredMcp: safeDependencyNames(details.requiredMcp),
  };
}

export function normalizeTraceStatus(status) {
  const value = safeText(status);
  if (value === "completed") return "success";
  if (value === "error") return "failed";
  return value;
}

export function traceStatusClass(status) {
  return normalizeTraceStatus(status);
}

export function displayName(step) {
  const name = safeText(step?.name);
  const kind = safeText(step?.kind);
  return (
    mappedLabel(nameLabels, name)
    || (name || kind || "步骤").replaceAll("_", " ")
  );
}

export function traceKindLabel(kind) {
  const value = safeText(kind);
  return mappedLabel(kindLabels, value) || value || "STEP";
}

export function traceStatusLabel(status) {
  const value = safeText(status);
  return mappedLabel(statusLabels, value) || value;
}

export function traceDurationLabel(durationMs) {
  const value = Number(durationMs);
  if (!Number.isFinite(value) || value < 0) return "…";
  if (value < 1000) return `${Math.round(value)}ms`;
  return `${(value / 1000).toFixed(2)}s`;
}

export function traceStepTitle(step) {
  if (!step) return "";
  if (step.title === "连接中断") return step.title;
  const kind = safeText(step.kind);
  const name = safeText(step.name);
  const status = normalizeTraceStatus(step.status);
  if (kind === "skill") {
    if (status === "running") {
      return `正在激活 ${skillDisplayName(step)}`;
    }
    if (status === "success") {
      return `已激活 ${skillDisplayName(step)}`;
    }
    return "Skill 激活失败";
  }
  if (kind === "approval") {
    if (status === "waiting" || status === "running") {
      return "等待工具确认";
    }
    if (status === "success") return "已允许工具执行";
    if (status === "cancelled") return "工具确认已取消";
    return safeText(step.outputSummary?.decision) === "timeout"
      ? "工具确认已超时"
      : "已拒绝工具执行";
  }
  if (name === "agent_run") {
    if (status === "running") return "Agent正在处理";
    if (status === "success") return "Agent处理完成";
    return "Agent处理失败";
  }
  if (name === "model_completion") {
    if (status === "running") return "模型正在分析";
    if (status === "success") return "模型步骤完成";
    return "模型调用失败";
  }
  if (name === "web_search") {
    if (status === "running") return "正在联网搜索";
    if (status === "success") return "联网搜索完成";
    return "联网搜索失败";
  }
  if (name === "memory_recall") {
    if (status === "running") return "正在召回长期记忆";
    if (status === "success") return "长期记忆召回完成";
    return "长期记忆召回失败";
  }
  if (name === "memory_write") {
    if (status === "waiting" || status === "running") {
      return "正在整理长期记忆";
    }
    if (status === "success") return "长期记忆整理完成";
    return "长期记忆写入失败";
  }
  return `${displayName(step)}${traceStatusLabel(step.status)}`;
}

export function traceMemoryItems(step) {
  const items = Array.isArray(step?.details?.items)
    ? step.details.items
    : [];
  return items
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      action: safeText(item.action),
      content: safeText(item.content),
    }))
    .filter((item) => item.content);
}

function summaryText(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "string") return value.trim() || fallback;
  return safeText(value, fallback);
}

function traceDetailsForDisplay(step) {
  if (step?.kind === "skill") {
    return {
      skillDetails: skillDetailsForDisplay(step),
      inputSummary: null,
      outputSummary: null,
      errorCode: null,
    };
  }
  return {
    skillDetails: null,
    inputSummary: summaryText(step?.inputSummary, "无"),
    outputSummary: summaryText(
      step?.outputSummary,
      normalizeTraceStatus(step?.status) === "running"
        ? "执行中"
        : "无",
    ),
    errorCode: safeText(step?.errorCode, null) || null,
  };
}

function mcpServerName(step) {
  const serverName = (
    safeText(step?.details?.serverName)
    || safeText(step?.serverName)
  );
  if (serverName) return serverName;
  const parts = safeText(step?.name).split("__");
  return parts.length >= 3 && parts[0] === "mcp"
    ? parts[1]
    : "MCP";
}

function traceContextForDisplay(step) {
  return {
    serverName: mcpServerName(step),
    toolName: safeText(step?.details?.toolName) || displayName(step),
    risk: safeText(step?.details?.risk, null) || null,
    decision: safeText(step?.outputSummary?.decision, null) || null,
  };
}

function parseSummary(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value;
  }
  if (typeof value !== "string" || !value.trim().startsWith("{")) {
    return null;
  }
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed
      : null;
  } catch {
    return null;
  }
}

function compactValue(value) {
  if (value == null || value === "") return "";
  if (Array.isArray(value)) {
    return value
      .map((item) => safeText(item))
      .filter(Boolean)
      .join("、");
  }
  if (typeof value === "object") return "";
  return safeText(value);
}

function addField(fields, label, value) {
  const text = compactValue(value);
  if (
    text
    && !fields.some((field) => field.label === label)
  ) {
    fields.push({ label, value: text });
  }
}

const summaryFieldLabels = {
  action: "操作",
  database_id: "数据库",
  messageCount: "上下文消息",
  operation: "操作",
  page_id: "页面",
  toolCount: "可用工具",
  toolCallCount: "选择工具",
  query: "搜索词",
  top_k: "计划结果",
  resultCount: "返回结果",
};

function addSummaryFields(fields, summary, prefix = "") {
  if (!summary || typeof summary !== "object") return;
  Object.entries(summary).forEach(([key, value]) => {
    if (
      !Object.prototype.hasOwnProperty.call(
        summaryFieldLabels,
        key,
      )
    ) {
      return;
    }
    if (value && typeof value === "object") return;
    addField(
      fields,
      summaryFieldLabels[key] || `${prefix}${key}`,
      value,
    );
  });
}

export function traceStepReason(step) {
  const name = safeText(step?.name);
  const kind = safeText(step?.kind);
  if (name === "agent_run") {
    return "接收问题并协调本轮模型、工具与后台任务。";
  }
  if (name === "model_completion") {
    return "结合当前上下文生成回答，或选择下一步需要调用的工具。";
  }
  if (name === "web_search") {
    return "问题需要外部或实时信息，因此执行联网搜索。";
  }
  if (name === "memory_recall") {
    return "回答前读取与你相关的稳定偏好和长期信息。";
  }
  if (name === "memory_write") {
    return "回答完成后检查是否有值得长期保留的新信息。";
  }
  if (kind === "skill") {
    return "当前任务匹配该Skill，加载其公开能力和依赖。";
  }
  if (kind === "mcp") {
    return "通过已连接的MCP服务器完成外部系统操作。";
  }
  if (kind === "approval") {
    return "该操作可能产生外部影响，需要你确认后才能继续。";
  }
  if (kind === "tool") {
    return "模型选择该工具补充完成任务所需的信息或能力。";
  }
  return "记录Agent在本轮任务中的执行状态。";
}

export function traceStepFields(step) {
  const fields = [];
  const details = (
    step?.details
    && typeof step.details === "object"
    && !Array.isArray(step.details)
  )
    ? step.details
    : {};
  const input = parseSummary(step?.inputSummary);
  const output = parseSummary(step?.outputSummary);
  const kind = safeText(step?.kind);
  const name = safeText(step?.name);

  if (kind === "model") {
    addField(fields, "模型", details.modelName);
    addField(
      fields,
      "协议",
      details.apiMode === "responses"
        ? "Responses API"
        : details.apiMode === "chat_completions"
          ? "Chat Completions"
          : details.apiMode,
    );
    addField(fields, "上下文消息", input?.messageCount);
    addField(fields, "可用工具", input?.toolCount);
    addField(fields, "选择工具", output?.toolCallCount);
  } else if (name === "web_search") {
    addField(fields, "搜索词", input?.query);
    addField(fields, "计划结果", input?.top_k);
    addField(
      fields,
      "返回结果",
      Array.isArray(output?.results)
        ? output.results.length
        : output?.resultCount,
    );
  } else if (kind === "mcp" || kind === "approval") {
    const context = traceContextForDisplay(step);
    addField(fields, "服务器", context.serverName);
    addField(fields, "工具", context.toolName);
    addField(fields, "风险", context.risk);
    addField(fields, "决定", context.decision);
  } else if (kind === "skill") {
    const skill = skillDetailsForDisplay(step);
    addField(fields, "Skill", skill.displayName);
    addField(fields, "版本", skill.version);
    addField(fields, "来源", skill.sourceKind);
    addField(fields, "所需工具", skill.requiredTools);
    addField(fields, "所需MCP", skill.requiredMcp);
  } else if (kind === "memory") {
    addField(fields, "处理条目", traceMemoryItems(step).length);
    addField(fields, "尝试次数", details.attemptCount);
  }
  addSummaryFields(fields, input, "输入·");
  addSummaryFields(fields, output, "结果·");

  const isolated = traceDetailsForDisplay(step);
  if (
    isolated.inputSummary
    && isolated.inputSummary !== "无"
    && !input
  ) {
    addField(fields, "输入概览", isolated.inputSummary);
  }
  if (
    isolated.outputSummary
    && !["无", "执行中"].includes(isolated.outputSummary)
    && !output
  ) {
    addField(fields, "结果摘要", isolated.outputSummary);
  }
  if (isolated.errorCode) {
    addField(fields, "错误码", isolated.errorCode);
  }
  return fields;
}

export function traceCopyText(step) {
  const lines = [
    traceStepTitle(step),
    `${traceKindLabel(step?.kind)} · ${traceStatusLabel(step?.status)}`,
    `耗时：${traceDurationLabel(step?.durationMs)}`,
    `为什么执行：${traceStepReason(step)}`,
  ];
  traceStepFields(step).forEach((field) => {
    lines.push(`${field.label}：${field.value}`);
  });
  traceMemoryItems(step).forEach((item) => {
    lines.push(`记忆${item.action || "记录"}：${item.content}`);
  });
  return lines.filter(Boolean).join("\n");
}

export function traceStepTarget(step) {
  if (step?.kind === "memory") return "memory";
  if (step?.kind === "skill") return "skills";
  if (step?.kind === "mcp" || step?.kind === "tool") return "tools";
  return "";
}

export {
  skillDetailsForDisplay,
  traceContextForDisplay,
  traceDetailsForDisplay,
};
