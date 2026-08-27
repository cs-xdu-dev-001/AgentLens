import { traceCopyText } from "../components/agentTracePresentation.js";

export const COPY_TEXT_LIMIT = 100_000;

const REDACTION_PATTERNS = [
  [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, "[已隐藏私钥]"],
  [/\b(?:sk|ak)-[A-Za-z0-9_-]{12,}\b/g, "[已隐藏]"],
  [/\b((?:org|proj)-)[A-Za-z0-9_-]{8,}\b/g, "$1[已隐藏]"],
  [/\bBearer\s+[A-Za-z0-9._~-]{8,}\b/gi, "Bearer [已隐藏]"],
  [/(api[_-]?key|token|password|secret|cookie|authorization|private[_-]?key)(\s*[:=]\s*)(["']?)[^\s,"'}]+/gi, "$1$2[已隐藏]"],
  [/([?&](?:api[_-]?key|token|password|secret|cookie|authorization)=)[^&#\s]+/gi, "$1[已隐藏]"],
  [/([a-z][a-z0-9+.-]*:\/\/[^:\s/]+:)[^@\s/]+@/gi, "$1[已隐藏]@"],
];

export function redactCopyText(value, maxLength = COPY_TEXT_LIMIT) {
  let text = String(value ?? "");
  for (const [pattern, replacement] of REDACTION_PATTERNS) {
    text = text.replace(pattern, replacement);
  }
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(0, maxLength - 1))}…`;
}

function copyValue(value, limit = 12_000) {
  if (value === undefined || value === null || value === "") return "";
  let text;
  if (typeof value === "string") {
    text = value;
  } else {
    try {
      text = JSON.stringify(value, null, 2);
    } catch {
      text = String(value);
    }
  }
  return redactCopyText(text, limit).trim();
}

export function boundedCopyJoin(items, format, separator = "\n\n", limit = COPY_TEXT_LIMIT) {
  const chunks = [];
  let used = 0;
  for (let index = 0; index < items.length; index += 1) {
    const value = String(format(items[index], index) ?? "").trim();
    if (!value) continue;
    const prefix = chunks.length ? separator : "";
    const available = Math.max(0, limit - used - prefix.length);
    if (value.length > available) {
      const marker = "\n[内容已截断]";
      const visible = value.slice(0, Math.max(0, available - marker.length));
      chunks.push(`${prefix}${visible}${marker}`.slice(0, Math.max(0, limit - used)));
      return { text: chunks.join(""), truncated: true };
    }
    chunks.push(`${prefix}${value}`);
    used += prefix.length + value.length;
  }
  return { text: chunks.join(""), truncated: false };
}

function copyToolCall(call, index = 0) {
  const name = copyValue(
    call?.toolName || call?.tool_name || call?.name || "工具调用",
    160,
  ) || "工具调用";
  const status = copyValue(call?.status || call?.normalizedStatus || "running", 80) || "running";
  const lines = [`[${status}] ${name}`];
  const fields = [
    ["输入", call?.arguments || call?.inputJson || call?.input_json || call?.input],
    ["输出", call?.output || call?.outputText || call?.output_text || call?.content],
    ["标准输出", call?.stdout],
    ["错误输出", call?.stderr],
    ["错误", call?.errorMessage || call?.error_message || call?.error?.message || call?.errorCode],
  ];
  for (const [label, value] of fields) {
    const text = copyValue(value);
    if (text) lines.push(`${label}:\n${text}`);
  }
  const duration = call?.durationMs ?? call?.latencyMs ?? call?.latency_ms;
  if (duration !== undefined && duration !== null) {
    lines.push(`耗时: ${copyValue(duration, 40)}ms`);
  }
  return `${index + 1}. ${lines.join("\n")}`;
}

function copyTrace(trace) {
  const rows = Array.isArray(trace) ? trace.filter(Boolean) : [];
  return boundedCopyJoin(rows, (step, index) => (
    `${index + 1}. ${redactCopyText(traceCopyText(step), 20_000)}`
  ), "\n", 30_000).text;
}

function copyTranscriptItem(message, index) {
  const role = message?.role === "user" ? "用户" : "Agent";
  const content = copyValue(message?.rawContent || message?.content, 20_000);
  const sections = content ? [`${role}:\n${content}`] : [];
  if (message?.role !== "user") {
    const trace = copyTrace(message?.trace);
    if (trace) sections.push(`任务过程:\n${trace}`);
    const tools = Array.isArray(message?.toolCalls) ? message.toolCalls.filter(Boolean) : [];
    if (tools.length) {
      sections.push(`工具输出:\n${boundedCopyJoin(tools, copyToolCall, "\n", 30_000).text}`);
    }
  }
  return sections.length ? `${index + 1}. ${sections.join("\n")}` : "";
}

function codeBlocks(value) {
  const blocks = [];
  const pattern = /(?:^|\n)(`{3,}|~{3,})[^\n]*\n([\s\S]*?)\n\1(?=\n|$)/gu;
  let match;
  while ((match = pattern.exec(String(value ?? "")))) blocks.push(match[2]);
  return blocks;
}

export function copySelection({ assistant = "", assistantMessage = null, messages = [], args = "" } = {}) {
  const parts = String(args || "").trim().toLowerCase().split(/\s+/u).filter(Boolean);
  const mode = parts[0] || "answer";
  const answer = redactCopyText(String(assistant || assistantMessage?.rawContent || "").trim());

  if (mode === "answer" && parts.length <= 1) {
    return answer
      ? { ok: true, label: "最近回答", text: answer }
      : { ok: false, message: "还没有可复制的Agent回答。" };
  }
  if (mode === "code") {
    if (parts.length > 2) return { ok: false, message: "用法：/copy code [序号]" };
    const blocks = codeBlocks(answer);
    if (!blocks.length) return { ok: false, message: "最近回答中没有Markdown代码块。" };
    const requested = parts[1] ? Number(parts[1]) : 1;
    if (!Number.isInteger(requested) || requested < 1 || requested > blocks.length) {
      return { ok: false, message: `最近回答共有${blocks.length}个代码块，请输入1-${blocks.length}。` };
    }
    return { ok: true, label: `代码块${requested}/${blocks.length}`, text: redactCopyText(blocks[requested - 1]) };
  }
  if (mode === "tool") {
    if (parts.length > 2 || (parts[1] && parts[1] !== "all" && !/^\d+$/u.test(parts[1]))) {
      return { ok: false, message: "用法：/copy tool [序号|all]" };
    }
    const rows = Array.isArray(assistantMessage?.toolCalls)
      ? assistantMessage.toolCalls.filter(Boolean)
      : [];
    if (!rows.length) return { ok: false, message: "当前运行还没有可复制的工具输出。" };
    const requested = parts[1] && parts[1] !== "all" ? Number(parts[1]) : rows.length;
    if (!Number.isInteger(requested) || requested < 1 || requested > rows.length) {
      return { ok: false, message: `当前共有${rows.length}条工具记录，请输入1-${rows.length}或all。` };
    }
    const selected = parts[1] === "all" ? rows : [rows[requested - 1]];
    const output = boundedCopyJoin(
      selected,
      (row, index) => copyToolCall(row, parts[1] === "all" ? index : requested - 1),
    );
    return {
      ok: true,
      label: `${parts[1] === "all" ? `全部工具输出（${rows.length}项）` : `工具输出${requested}/${rows.length}`}${output.truncated ? "，已截断" : ""}`,
      text: output.text,
    };
  }
  if (mode === "transcript") {
    if (parts.length > 1) return { ok: false, message: "用法：/copy transcript" };
    const source = Array.isArray(messages) ? messages.filter((item) => !item?.thinking) : [];
    const output = boundedCopyJoin(source, copyTranscriptItem);
    if (!output.text) return { ok: false, message: "当前会话还没有可复制的记录。" };
    return { ok: true, label: `当前会话记录${output.truncated ? "（已截断）" : ""}`, text: output.text };
  }
  return { ok: false, message: "用法：/copy、/copy answer、/copy code [序号]、/copy tool [序号|all]或/copy transcript" };
}
