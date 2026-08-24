export function appendReactMessage(role, content, options = {}) {
  const raw = String(content ?? "");
  const message = {
    messageId: "",
    streaming: Boolean(options.streaming),
    thinking: Boolean(options.thinking),
    retryable: Boolean(options.retryable ?? (role === "assistant" && options.thinking)),
    sourceMessageId: options.sourceMessageId ?? null,
  };
  const detail = {
    role,
    rawContent: raw,
    thinking: message.thinking,
    streaming: message.streaming,
    retryable: message.retryable,
    trace: Array.isArray(options.trace) ? options.trace : [],
    approvals: Array.isArray(options.approvals) ? options.approvals : [],
    questions: Array.isArray(options.questions) ? options.questions : [],
    toolCalls: Array.isArray(options.toolCalls) ? options.toolCalls : [],
    run: options.run || null,
    memoryActivity: options.memoryActivity || null,
    sourceMessageId: message.sourceMessageId,
  };
  window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail }));
  message.messageId = detail.messageId || "";
  return message.messageId ? message : null;
}

export function updateReactMessageContent(message, role, raw) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    role,
    rawContent: String(raw ?? ""),
    streaming: Boolean(message.streaming),
  };
  window.dispatchEvent(new CustomEvent("knowflow:react-message-content", { detail }));
  const handled = Boolean(detail.handled);
  if (handled) message.thinking = false;
  return handled;
}

export function updateReactMessageThinking(message, enabled) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    enabled,
    streaming: Boolean(message.streaming),
  };
  window.dispatchEvent(new CustomEvent("knowflow:react-message-thinking", { detail }));
  const handled = Boolean(detail.handled);
  if (handled) message.thinking = Boolean(enabled);
  return handled;
}

export function updateReactMessageTrace(message, trace) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    trace: Array.isArray(trace) ? trace : [],
  };
  window.dispatchEvent(
    new CustomEvent(
      "knowflow:react-message-trace",
      { detail },
    ),
  );
  return Boolean(detail.handled);
}

export function updateReactMessageApprovals(message, approvals) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    approvals: Array.isArray(approvals) ? approvals : [],
  };
  window.dispatchEvent(
    new CustomEvent(
      "knowflow:react-message-approvals",
      { detail },
    ),
  );
  return Boolean(detail.handled);
}

export function updateReactMessageQuestions(message, questions) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    questions: Array.isArray(questions) ? questions : [],
  };
  window.dispatchEvent(
    new CustomEvent("knowflow:react-message-questions", { detail }),
  );
  return Boolean(detail.handled);
}

export function updateReactMessageRun(message, run) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = { messageId, run: run || null };
  window.dispatchEvent(
    new CustomEvent("knowflow:react-message-run", { detail }),
  );
  return Boolean(detail.handled);
}

export function publishReactAgentArtifactsUpdated({
  messageId = "",
  runId = "",
  artifacts = [],
} = {}) {
  const detail = {
    messageId: String(messageId || ""),
    runId: String(runId || ""),
    artifacts: Array.isArray(artifacts) ? artifacts : [],
  };
  window.dispatchEvent(new CustomEvent(
    "knowflow:react-agent-artifacts-updated",
    { detail },
  ));
  return Boolean(detail.handled);
}

export function updateReactMessageToolCalls(message, toolCalls) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    toolCalls: Array.isArray(toolCalls) ? toolCalls : [],
  };
  window.dispatchEvent(
    new CustomEvent("knowflow:react-message-tool-calls", { detail }),
  );
  return Boolean(detail.handled);
}

export function updateReactMessageMemoryActivity(
  message,
  memoryActivity,
) {
  const messageId = message?.messageId || "";
  if (!messageId) return false;
  const detail = {
    messageId,
    memoryActivity: memoryActivity || null,
  };
  window.dispatchEvent(
    new CustomEvent(
      "knowflow:react-message-memory-activity",
      { detail },
    ),
  );
  return Boolean(detail.handled);
}

export function dispatchReactMessagesReset(showWelcome = false) {
  const detail = { showWelcome };
  window.dispatchEvent(new CustomEvent("knowflow:react-messages-reset", { detail }));
  return Boolean(detail.handled);
}
