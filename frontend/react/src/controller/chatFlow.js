import { notifyAuthRequired } from "../api/client.js";
import { normalizeErrorMessage } from "../api/errors.js";

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

function mergeTraceStep(trace, step) {
  const next = Array.isArray(trace) ? [...trace] : [];
  const index = next.findIndex(
    (item) => item.stepId === step.stepId,
  );
  if (index >= 0) {
    next[index] = { ...next[index], ...step };
  } else {
    next.push(step);
  }
  return next;
}

function markTraceInterrupted(trace) {
  return (Array.isArray(trace) ? trace : []).map((step) => {
    if (step.status === "waiting" && step.kind === "approval") {
      return {
        ...step,
        status: "cancelled",
        title: "确认已取消",
        errorCode: "approval_cancelled",
      };
    }
    return step.status === "running"
      ? {
          ...step,
          status: "failed",
          title: "连接中断",
          errorCode: "stream_interrupted",
        }
      : step;
  });
}

function mergeApproval(approvals, event) {
  const next = Array.isArray(approvals) ? [...approvals] : [];
  const index = next.findIndex(
    (item) => item.approvalId === event.approvalId,
  );
  const value = {
    ...(index >= 0 ? next[index] : {}),
    ...event,
    status:
      event.type === "approval_required"
        ? "waiting"
        : event.status || "cancelled",
  };
  if (index >= 0) next[index] = value;
  else next.push(value);
  return next;
}

function markApprovalsCancelled(approvals) {
  return (Array.isArray(approvals) ? approvals : []).map((approval) =>
    approval.status === "waiting" && !approval.decision
      ? {
          ...approval,
          status: "cancelled",
          decision: "cancelled",
        }
      : approval,
  );
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
  renderAgentTrace,
  renderAttachmentTray,
  renderReferences,
  renderRagQuality,
  renderToolTimeline,
  openRetrievalDrawerFromRun,
  requestComposerReset,
  requestReactSessionsRefresh,
  switchPage,
}) {
  async function continueSession(sessionId) {
    const messages = await request(`/api/sessions/${sessionId}/messages`);
    clearChatMessages(false);
    messages.forEach((message) =>
      appendMessage(
        message.role,
        message.content,
        {
          trace: Array.isArray(message.trace)
            ? message.trace
            : [],
        },
      ),
    );
    state.currentSessionId = sessionId;
    renderActiveSession();
    requestReactSessionsRefresh();
    switchPage("chat");
  }

  function startNewChat() {
    state.currentSessionId = null;
    renderActiveSession();
    clearChatMessages(true);
    renderReferences([]);
    renderToolTimeline([]);
    renderAgentTrace(null, []);
    renderAgentApprovals(null, []);
    requestComposerReset({ focus: true });
    state.chatAttachments = [];
    renderAttachmentTray();
    requestReactSessionsRefresh();
    switchPage("chat");
  }

  function stopChatGeneration() {
    if (!state.activeChatController || state.activeChatController.signal.aborted) return;
    state.activeChatController.abort();
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

    const requestSnapshot = { question, payload: { ...payload } };
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

    let answerBuffer = "";
    let trace = [];
    let approvals = [];
    let receivedDone = false;
    const controller = new AbortController();
    state.activeChatController = controller;
    setSending(true);
    renderReferences([]);
    renderToolTimeline([]);
    renderAgentApprovals(answer, approvals);

    const cancelPendingApprovals = () => {
      const next = markApprovalsCancelled(approvals);
      const changed = next.some(
        (approval, index) => approval !== approvals[index],
      );
      approvals = next;
      if (changed) renderAgentApprovals(answer, approvals);
    };
    const handleLocalApprovalState = (event) => {
      const detail = event.detail || {};
      if (
        !detail.approvalId ||
        !["resolved", "expired"].includes(detail.state)
      ) return;
      const current = approvals.find(
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
      approvals = mergeApproval(approvals, {
        type: "approval_submitted",
        approvalId: detail.approvalId,
        decision,
        status,
      });
      renderAgentApprovals(answer, approvals);
      if (current.stepId) {
        trace = mergeTraceStep(trace, {
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
        });
        renderAgentTrace(answer, trace);
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
      const references = [];
      const calls = [];
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
          if (eventPayload.type === "agent_step") {
            trace = mergeTraceStep(trace, eventPayload);
            renderAgentTrace(answer, trace);
          }
          if (eventPayload.type === "approval_required") {
            approvals = mergeApproval(approvals, eventPayload);
            renderAgentApprovals(answer, approvals);
          }
          if (eventPayload.type === "approval_resolved") {
            approvals = mergeApproval(approvals, eventPayload);
            renderAgentApprovals(answer, approvals);
          }
          if (eventPayload.type === "answer") {
            answerBuffer += eventPayload.content || "";
            setMessageContent(answer, "assistant", answerBuffer);
          }
          if (eventPayload.type === "reference") {
            references.push(eventPayload);
            renderReferences(references);
          }
          if (eventPayload.type === "tool") {
            calls.push(eventPayload);
            renderToolTimeline(calls);
          }
          if (eventPayload.type === "quality") {
            renderRagQuality(eventPayload.ragQuality, eventPayload.retrievalRun);
            openRetrievalDrawerFromRun(eventPayload.retrievalRun);
          }
          if (eventPayload.type === "error") {
            cancelPendingApprovals();
            trace = markTraceInterrupted(trace);
            renderAgentTrace(answer, trace);
            throw new Error(
              eventPayload.message || "Agent运行失败。",
            );
          }
          if (eventPayload.type === "done") {
            receivedDone = true;
            cancelPendingApprovals();
            if (Array.isArray(eventPayload.trace)) {
              trace = eventPayload.trace;
              renderAgentTrace(answer, trace);
            }
            state.currentSessionId = eventPayload.sessionId;
            renderActiveSession();
          }
        }
      }
      if (!receivedDone) {
        cancelPendingApprovals();
        if (trace.length) {
          trace = markTraceInterrupted(trace);
          renderAgentTrace(answer, trace);
        }
      }
      if (answer.thinking) {
        setMessageContent(answer, "assistant", answerBuffer || "模型没有返回内容。");
      }
      if (!retryRequest) {
        requestComposerReset();
        state.chatAttachments = [];
        renderAttachmentTray();
      }
      requestReactSessionsRefresh();
    } catch (error) {
      cancelPendingApprovals();
      if (trace.length) {
        trace = markTraceInterrupted(trace);
        renderAgentTrace(answer, trace);
      }
      if (controller.signal.aborted || error?.name === "AbortError") {
        setMessageContent(answer, "assistant", answerBuffer || "生成已停止。");
      } else {
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

  return {
    continueSession,
    retryAnswer,
    startNewChat,
    stopChatGeneration,
    submitChat,
  };
}
