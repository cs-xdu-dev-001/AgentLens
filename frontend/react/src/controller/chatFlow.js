import { notifyAuthRequired } from "../api/client.js";
import { agentRunApi } from "../api/client.js";
import { normalizeErrorMessage } from "../api/errors.js";
import {
  agentEventError,
  agentEventIs,
  agentReconnectDelay,
  cancelPendingAgentApprovals,
  createAgentProjection,
  isRetryableAgentStreamStatus,
  markAgentTraceInterrupted,
  mergeAgentToolCall,
  projectAgentEvent,
  shouldProcessAgentEvent,
} from "./agentEvents.js";
import { isActiveRun } from "./agentRunState.js";

export { mergeAgentToolCall as mergeToolCall } from "./agentEvents.js";

async function readStreamError(response) {
  const fallback = response.status === 401 ? "请先登录。" : "请求失败，请稍后重试。";
  const text = await response.text();
  if (!text) return fallback;
  try {
    const payload = JSON.parse(text);
    return normalizeErrorMessage(payload.message || payload.detail?.message || payload.detail, fallback);
  } catch {
    return normalizeErrorMessage(text, fallback);
  }
}

function waitForAgentReconnect(delayMs, signal) {
  if (signal?.aborted) {
    const error = new Error("Agent连接已取消。");
    error.name = "AbortError";
    return Promise.reject(error);
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      window.clearTimeout(timer);
      const error = new Error("Agent连接已取消。");
      error.name = "AbortError";
      reject(error);
    };
    const timer = window.setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, delayMs);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

function clonePlainSnapshotValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => clonePlainSnapshotValue(item));
  }
  if (!value || typeof value !== "object") return value;

  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return value;
  }

  const clone = prototype === null ? Object.create(null) : {};
  Object.entries(value).forEach(([key, item]) => {
    clone[key] = clonePlainSnapshotValue(item);
  });
  return clone;
}

export function cloneChatPayload(payload) {
  return {
    ...payload,
    enabledTools: clonePlainSnapshotValue(payload.enabledTools),
    attachments: clonePlainSnapshotValue(payload.attachments),
  };
}

export function createChatFlow({
  state,
  messageRetryRequests,
  request,
  toast,
  appendMessage,
  clearChatMessages,
  setMessageContent,
  setMessageThinking,
  setSending,
  renderActiveSession,
  renderAgentApprovals,
  renderAgentRun,
  renderAgentTrace,
  renderMemoryActivity,
  renderAttachmentTray,
  renderReferences,
  renderRagQuality,
  renderToolTimeline,
  openRetrievalDrawerFromRun,
  requestComposerReset,
  requestReactSessionsRefresh,
  switchPage,
}) {
  function renderProjectedAgentState(message, result) {
    const { projection, changed } = result;
    const changedSet = new Set(changed);
    if (changedSet.has("answer")) {
      setMessageContent(message, "assistant", projection.answer);
    }
    if (changedSet.has("trace")) {
      renderAgentTrace(message, projection.trace);
    }
    if (changedSet.has("approvals")) {
      renderAgentApprovals(message, projection.approvals);
    }
    if (changedSet.has("toolCalls")) {
      renderToolTimeline(projection.toolCalls);
    }
    if (changedSet.has("references")) {
      renderReferences(projection.references);
    }
    if (changedSet.has("run")) {
      renderAgentRun(message, projection.run);
    }
    if (changedSet.has("memoryActivity")) {
      renderMemoryActivity(message, projection.memoryActivity);
    }
    if (changedSet.has("quality")) {
      renderRagQuality(projection.ragQuality, projection.retrievalRun);
      openRetrievalDrawerFromRun(projection.retrievalRun);
    }
    if (projection.sessionId) {
      state.currentSessionId = projection.sessionId;
    }
    if (projection.terminal) {
      state.activeRunId = null;
      state.activeRunMessageId = null;
      renderActiveSession();
    } else if (projection.run) {
      state.activeRunId = isActiveRun(projection.run)
        ? projection.run.id
        : null;
      state.activeRunMessageId = isActiveRun(projection.run)
        ? message.messageId
        : null;
    }
    return projection;
  }

  function applyAgentEvent(projection, event, message) {
    const result = projectAgentEvent(projection, event);
    renderProjectedAgentState(message, result);
    return result.projection;
  }

  async function continueSession(sessionId) {
    const messages = await request(`/api/sessions/${sessionId}/messages`);
    state.activeRunReconnectController?.abort();
    state.activeRunReconnectController = null;
    state.activeRunId = null;
    state.activeRunMessageId = null;
    clearChatMessages(false);
    let reconnectTarget = null;
    messages.forEach((message) => {
      const appended = appendMessage(
        message.role,
        message.content,
        {
          trace: Array.isArray(message.trace)
            ? message.trace
            : [],
          run: message.run || null,
          memoryActivity: message.memoryActivity || null,
        },
      );
      if (
        message.role === "assistant"
        && appended?.messageId
        && isActiveRun(message.run)
      ) {
        reconnectTarget = {
          messageId: appended.messageId,
          runId: message.run.id,
        };
      }
    });
    state.currentSessionId = sessionId;
    renderActiveSession();
    requestReactSessionsRefresh();
    switchPage("chat");
    if (reconnectTarget) {
      const controller = new AbortController();
      state.activeRunReconnectController = controller;
      state.activeRunId = reconnectTarget.runId;
      state.activeRunMessageId = reconnectTarget.messageId;
      setSending(true);
      reconnectAgentRun(
        reconnectTarget.runId,
        reconnectTarget.messageId,
        controller.signal,
      )
        .catch((error) => {
          if (error?.name !== "AbortError") {
            toast(error.message || "恢复任务连接失败", 4200, "error");
          }
        })
        .finally(() => {
          if (state.activeRunReconnectController === controller) {
            state.activeRunReconnectController = null;
            setSending(false);
          }
        });
    }
  }

  function startNewChat() {
    state.activeRunReconnectController?.abort();
    state.activeRunReconnectController = null;
    state.currentSessionId = null;
    renderActiveSession();
    clearChatMessages(true);
    renderReferences([]);
    renderToolTimeline([]);
    renderAgentTrace(null, []);
    renderAgentApprovals(null, []);
    renderAgentRun(null, null);
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close"));
    requestComposerReset({ focus: true });
    state.chatAttachments = [];
    renderAttachmentTray();
    requestReactSessionsRefresh();
    switchPage("chat");
  }

  function stopChatGeneration() {
    if (state.activeRunId) {
      agentRunApi.cancel(state.activeRunId).catch(() => {});
    }
    if (
      state.activeChatController
      && !state.activeChatController.signal.aborted
    ) {
      state.activeChatController.abort();
    }
  }

  async function retryAnswer(messageId = null) {
    if (state.sending) {
      stopChatGeneration();
      return;
    }
    const retryRequest = messageId ? messageRetryRequests.get(messageId) : state.lastChatRequest;
    if (!retryRequest) {
      toast("暂无可重试的问题");
      return;
    }
    await submitChat({
      retryRequest,
      replaceAnswer: messageId ? { messageId, streaming: false, thinking: false } : null,
      suppressUserMessage: Boolean(messageId),
    });
  }

  async function submitChat(options = {}) {
    if (state.sending) {
      stopChatGeneration();
      return;
    }
    const retryRequest = options.retryRequest || null;
    const replaceAnswer = options.replaceAnswer || null;
    const suppressUserMessage = options.suppressUserMessage || Boolean(replaceAnswer);
    let question = retryRequest?.question || String(options.question || "").trim();
    if (!question && state.chatAttachments.length) {
      question = "请总结上传的文件。";
    }
    if (!question) return;

    const knowledgeBaseId = retryRequest?.payload?.knowledgeBaseId ?? (state.selectedChatKnowledgeBaseId ? Number(state.selectedChatKnowledgeBaseId) : null);
    const chatModelConfigId = retryRequest?.payload?.chatModelConfigId ?? (state.selectedChatModelConfigId ? Number(state.selectedChatModelConfigId) : null);
    const skillId = retryRequest?.payload?.skillId ?? options.skillId ?? null;
    const attachments =
      retryRequest?.payload?.attachments ||
      state.chatAttachments.map(({ filename, fileType, mimeType, content, previewUrl }) => ({
        filename,
        fileType,
        mimeType,
        content,
        previewUrl,
      }));
    const attachmentNames = attachments.map((item) => item.filename).filter(Boolean).join(", ");
    const payload = {
      knowledgeBaseId,
      sessionId: state.currentSessionId,
      question,
      chatModelConfigId,
      useRag: Boolean(knowledgeBaseId),
      enableTools: true,
      autoAgent: true,
      toolMode: "auto",
      enabledTools: [],
      attachments: attachments,
    };
    if (skillId) payload.skillId = skillId;
    if (retryRequest?.payload) {
      payload.enableTools = true;
      payload.autoAgent = true;
      payload.toolMode = "auto";
      payload.enabledTools = [];
    }

    const requestSnapshot = { question, payload: cloneChatPayload(payload) };
    state.lastChatRequest = requestSnapshot;
    if (!suppressUserMessage) {
      appendMessage("user", attachmentNames ? `${question}\n\n附件：${attachmentNames}` : question);
    }

    const answer = replaceAnswer || appendMessage("assistant", "", { thinking: true, streaming: true });
    if (!answer?.messageId) {
      throw new Error("消息组件尚未准备好。");
    }
    answer.streaming = true;
    answer.thinking = true;
    messageRetryRequests.set(answer.messageId, requestSnapshot);
    if (replaceAnswer) {
      setMessageThinking(answer, true);
    }

    let projection = createAgentProjection();
    let recoveredStream = false;
    const controller = new AbortController();
    state.activeChatController = controller;
    setSending(true);
    renderReferences([]);
    renderToolTimeline([]);
    renderAgentApprovals(answer, projection.approvals);
    renderAgentRun(answer, projection.run);

    const cancelPendingApprovals = () => {
      const next = cancelPendingAgentApprovals(projection.approvals);
      const changed = next.some(
        (approval, index) => approval !== projection.approvals[index],
      );
      projection = { ...projection, approvals: next };
      if (changed) renderAgentApprovals(answer, next);
    };
    const handleLocalApprovalState = (event) => {
      const detail = event.detail || {};
      if (
        !detail.approvalId ||
        !["resolved", "expired"].includes(detail.state)
      ) return;
      const current = projection.approvals.find(
        (approval) =>
          approval.approvalId === detail.approvalId,
      );
      if (!current) return;
      const decision =
        detail.state === "expired"
          ? "expired"
          : detail.decision;
      const status =
        decision === "allow_once"
          ? "success"
          : "failed";
      projection = applyAgentEvent(projection, {
        type: "approval_submitted",
        approvalId: detail.approvalId,
        decision,
        status,
      }, answer);
      if (current.stepId) {
        projection = applyAgentEvent(projection, {
          type: "agent_step",
          stepId: current.stepId,
          status,
          title:
            decision === "allow_once"
              ? "Approval granted"
              : decision === "deny"
                ? "Approval denied"
                : "Approval expired",
          outputSummary: { decision },
          errorCode:
            decision === "allow_once"
              ? null
              : decision === "deny"
                ? "permission_denied"
                : "approval_expired",
        }, answer);
      }
    };
    window.addEventListener(
      "knowflow:react-approval-local-state",
      handleLocalApprovalState,
    );

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        signal: controller.signal,
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const message = await readStreamError(response);
        if (response.status === 401) {
          notifyAuthRequired({ path: "/api/chat/stream", status: response.status, message });
        }
        throw new Error(message);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const seenEventIds = new Set();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop();
        for (const event of events) {
          const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
          if (!dataLine) continue;
          const eventPayload = JSON.parse(dataLine.slice(6));
          if (!shouldProcessAgentEvent(seenEventIds, eventPayload)) continue;
          projection = applyAgentEvent(projection, eventPayload, answer);
          if (!state.activeRunId && eventPayload.runId && !projection.terminal) {
            state.activeRunId = eventPayload.runId;
            state.activeRunMessageId = answer.messageId;
          }
          if (projection.error) throw new Error(projection.error.message);
        }
      }
      if (
        !projection.terminal
        && !projection.paused
        && state.activeRunId
        && !controller.signal.aborted
      ) {
        projection = await reconnectAgentRun(
          state.activeRunId,
          answer.messageId,
          controller.signal,
          projection.lastSequence,
          projection,
        );
        recoveredStream = true;
      }
      if (!projection.terminal && !projection.paused && !recoveredStream) {
        cancelPendingApprovals();
        if (projection.trace.length) {
          projection = {
            ...projection,
            trace: markAgentTraceInterrupted(projection.trace),
          };
          renderAgentTrace(answer, projection.trace);
        }
      }
      if (answer.thinking) {
        setMessageContent(
          answer,
          "assistant",
          projection.answer
            || (projection.paused
              ? "等待确认后继续。"
              : projection.terminal === "cancelled"
                ? "生成已停止。"
                : "模型没有返回内容。"),
        );
      }
      if (!retryRequest) {
        requestComposerReset();
        state.chatAttachments = [];
        renderAttachmentTray();
      }
      requestReactSessionsRefresh();
    } catch (error) {
      if (controller.signal.aborted || error?.name === "AbortError") {
        cancelPendingApprovals();
        setMessageContent(answer, "assistant", projection.answer || "生成已停止。");
      } else if (state.activeRunId) {
        try {
          projection = await reconnectAgentRun(
            state.activeRunId,
            answer.messageId,
            controller.signal,
            projection.lastSequence,
            projection,
          );
          recoveredStream = true;
        } catch (reconnectError) {
          cancelPendingApprovals();
          if (projection.trace.length) {
            projection = {
              ...projection,
              trace: markAgentTraceInterrupted(projection.trace),
            };
            renderAgentTrace(answer, projection.trace);
          }
          setMessageContent(
            answer,
            "assistant",
            `请求失败：${reconnectError.message || error.message || "未知错误"}`,
          );
          toast("聊天请求失败", 4200, "error");
        }
      } else {
        cancelPendingApprovals();
        if (projection.trace.length) {
          projection = {
            ...projection,
            trace: markAgentTraceInterrupted(projection.trace),
          };
          renderAgentTrace(answer, projection.trace);
        }
        setMessageContent(answer, "assistant", `请求失败：${error.message || "未知错误"}`);
        toast("聊天请求失败", 4200, "error");
      }
    } finally {
      window.removeEventListener(
        "knowflow:react-approval-local-state",
        handleLocalApprovalState,
      );
      if (state.activeChatController === controller) state.activeChatController = null;
      answer.streaming = false;
      answer.thinking = false;
      setMessageThinking(answer, false);
      setSending(false);
    }
  }

  async function reconnectAgentRun(
    runId,
    messageId,
    signal = undefined,
    afterSequence = 0,
    initialProjection = null,
  ) {
    const message = {
      messageId,
      streaming: true,
      thinking: false,
    };
    let projection = createAgentProjection({
      ...(initialProjection || {}),
      lastSequence: Math.max(
        Number(initialProjection?.lastSequence || 0),
        Number(afterSequence || 0),
      ),
    });
    const seenEventIds = new Set();
    const maxReconnectAttempts = 5;
    let settled = false;
    let lastError = null;

    try {
      for (let attempt = 0; attempt <= maxReconnectAttempts; attempt += 1) {
        const replayQuery = projection.lastSequence > 0
          ? `?afterSequence=${encodeURIComponent(projection.lastSequence)}`
          : "";
        let response;
        try {
          response = await fetch(
            `/api/agent/runs/${runId}/events${replayQuery}`,
            { credentials: "include", signal },
          );
        } catch (error) {
          if (signal?.aborted || error?.name === "AbortError") throw error;
          lastError = error;
          if (attempt >= maxReconnectAttempts) break;
          await waitForAgentReconnect(agentReconnectDelay(attempt), signal);
          continue;
        }

        if (!response.ok) {
          const error = new Error(await readStreamError(response));
          error.status = response.status;
          error.retryable = isRetryableAgentStreamStatus(response.status);
          if (response.status === 401) {
            notifyAuthRequired({
              path: `/api/agent/runs/${runId}/events`,
              status: response.status,
              message: error.message,
            });
          }
          lastError = error;
          if (!error.retryable || attempt >= maxReconnectAttempts) throw error;
          await waitForAgentReconnect(agentReconnectDelay(attempt), signal);
          continue;
        }

        try {
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const events = buffer.split("\n\n");
            buffer = events.pop();
            for (const event of events) {
              const dataLine = event
                .split("\n")
                .find((line) => line.startsWith("data: "));
              if (!dataLine) continue;
              const eventPayload = JSON.parse(dataLine.slice(6));
              if (!shouldProcessAgentEvent(seenEventIds, eventPayload)) continue;
              projection = applyAgentEvent(projection, eventPayload, message);
              if (!state.activeRunId && eventPayload.runId && !projection.terminal) {
                state.activeRunId = eventPayload.runId;
                state.activeRunMessageId = messageId;
              }
              if (projection.error) {
                setMessageContent(
                  message,
                  "assistant",
                  `请求失败：${projection.error.message}`,
                );
                const error = new Error(projection.error.message);
                error.retryable = false;
                throw error;
              }
              if (projection.terminal || projection.paused) {
                settled = true;
                break;
              }
            }
            if (settled) break;
          }
        } catch (error) {
          if (signal?.aborted || error?.name === "AbortError") throw error;
          if (error?.retryable === false) throw error;
          lastError = error;
        }

        if (projection.terminal || projection.paused) {
          settled = true;
          break;
        }
        if (attempt >= maxReconnectAttempts) break;
        await waitForAgentReconnect(agentReconnectDelay(attempt), signal);
      }

      if (!settled) {
        const error = new Error(
          lastError?.message || "Agent连接多次中断，请刷新页面恢复运行状态。",
        );
        error.retryable = true;
        throw error;
      }

      if (!projection.answer) {
        const snapshot = await agentRunApi.get(runId);
        if (snapshot?.assistantMessageId && snapshot?.sessionId) {
          const messages = await request(
            `/api/sessions/${snapshot.sessionId}/messages`,
          );
          const saved = messages.find(
            (item) => item.id === snapshot.assistantMessageId,
          );
          if (saved) {
            projection = createAgentProjection({
              ...projection,
              answer: saved.content || "",
              trace: saved.trace || projection.trace,
              run: saved.run || snapshot,
              memoryActivity:
                saved.memoryActivity || projection.memoryActivity,
              sessionId: snapshot.sessionId,
            });
            setMessageContent(message, "assistant", projection.answer);
            renderAgentTrace(message, projection.trace);
            renderAgentRun(message, projection.run);
            renderMemoryActivity(message, projection.memoryActivity);
          }
        }
      }
      if (projection.terminal === "cancelled" && !projection.answer) {
        setMessageContent(message, "assistant", "生成已停止。");
      }
      return projection;
    } finally {
      message.streaming = false;
      message.thinking = false;
      setMessageThinking(message, false);
    }
  }
  async function handleAgentRunAction(event) {
    const detail = event.detail || {};
    const action = detail.action;
    const runId = detail.runId;
    const messageId = detail.messageId;
    if (
      !runId
      || !messageId
      || !["start", "replan", "resume", "restart", "cancel"].includes(action)
    ) return;
    try {
      setSending(true);
      const result = await agentRunApi[action](runId);
      const nextRun = result?.run || result;
      const nextRunId = nextRun?.id || runId;
      renderAgentRun({ messageId }, nextRun);
      if (action !== "cancel") {
        state.activeRunId = nextRunId;
        state.activeRunMessageId = messageId;
        await reconnectAgentRun(nextRunId, messageId);
      } else {
        state.activeRunId = null;
        state.activeRunMessageId = null;
      }
    } catch (error) {
      toast(error.message || "任务操作失败", 4200, "error");
    } finally {
      setSending(false);
    }
  }

  async function handleApprovalResume(event) {
    const detail = event.detail || {};
    const runId = detail.runId;
    const messageId = state.activeRunMessageId;
    if (!runId || !messageId) {
      requestReactSessionsRefresh();
      return;
    }
    try {
      setSending(true);
      if (detail.resumeRequired) {
        await agentRunApi.resume(runId);
      }
      state.activeRunId = runId;
      await reconnectAgentRun(runId, messageId);
    } catch (error) {
      toast(error.message || "恢复审批后的任务失败", 4200, "error");
    } finally {
      setSending(false);
    }
  }

  window.addEventListener(
    "knowflow:react-agent-run-action",
    handleAgentRunAction,
  );
  window.addEventListener(
    "knowflow:react-agent-approval-resume",
    handleApprovalResume,
  );

  return {
    continueSession,
    retryAnswer,
    startNewChat,
    stopChatGeneration,
    submitChat,
  };
}
