import { notifyAuthRequired } from "../api/client.js";
import { agentRunApi } from "../api/client.js";
import { normalizeErrorMessage } from "../api/errors.js";
import { isActiveRun } from "./agentRunState.js";

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

    let answerBuffer = "";
    let trace = [];
    let approvals = [];
    let run = null;
    let receivedDone = false;
    const controller = new AbortController();
    state.activeChatController = controller;
    setSending(true);
    renderReferences([]);
    renderToolTimeline([]);
    renderAgentApprovals(answer, approvals);
    renderAgentRun(answer, run);

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
            if (!state.activeRunId && eventPayload.runId) {
              state.activeRunId = eventPayload.runId;
              state.activeRunMessageId = answer.messageId;
            }
            trace = mergeTraceStep(trace, eventPayload);
            renderAgentTrace(answer, trace);
          }
          if (
            eventPayload.type === "run_snapshot"
            || eventPayload.type === "plan_created"
            || eventPayload.type === "run_updated"
            || eventPayload.type === "step_updated"
          ) {
            run = eventPayload.run || run;
            state.activeRunId = isActiveRun(run) ? run.id : null;
            state.activeRunMessageId = isActiveRun(run)
              ? answer.messageId
              : null;
            renderAgentRun(answer, run);
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
          if (eventPayload.type === "cancelled") {
            run = eventPayload.run || run;
            state.activeRunId = null;
            state.activeRunMessageId = null;
            renderAgentRun(answer, run);
          }
          if (eventPayload.type === "done") {
            receivedDone = true;
            cancelPendingApprovals();
            if (Array.isArray(eventPayload.trace)) {
              trace = eventPayload.trace;
              renderAgentTrace(answer, trace);
            }
            if (eventPayload.run) {
              run = eventPayload.run;
              renderAgentRun(answer, run);
            }
            if (eventPayload.memoryActivity) {
              renderMemoryActivity(
                answer,
                eventPayload.memoryActivity,
              );
            }
            state.activeRunId = isActiveRun(run) ? run.id : null;
            state.activeRunMessageId = isActiveRun(run)
              ? answer.messageId
              : null;
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

  async function reconnectAgentRun(runId, messageId, signal = undefined) {
    const message = {
      messageId,
      streaming: true,
      thinking: false,
    };
    let answerBuffer = "";
    let trace = [];
    let approvals = [];
    const cancelPendingApprovals = () => {
      const next = markApprovalsCancelled(approvals);
      const changed = next.some(
        (approval, index) => approval !== approvals[index],
      );
      approvals = next;
      if (changed) renderAgentApprovals(message, approvals);
    };
    try {
      const response = await fetch(
        `/api/agent/runs/${runId}/events`,
        { credentials: "include", signal },
      );
      if (!response.ok) {
        throw new Error(await readStreamError(response));
      }
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
          if (
            eventPayload.type === "run_snapshot"
            || eventPayload.type === "plan_created"
            || eventPayload.type === "run_updated"
            || eventPayload.type === "step_updated"
          ) {
            const nextRun = eventPayload.run || null;
            renderAgentRun(message, nextRun);
            state.activeRunId = isActiveRun(nextRun)
              ? nextRun.id
              : null;
            state.activeRunMessageId = isActiveRun(nextRun)
              ? messageId
              : null;
          }
          if (eventPayload.type === "agent_step") {
            trace = mergeTraceStep(trace, eventPayload);
            renderAgentTrace(message, trace);
          }
          if (eventPayload.type === "approval_required") {
            approvals = mergeApproval(approvals, eventPayload);
            renderAgentApprovals(message, approvals);
          }
          if (eventPayload.type === "approval_resolved") {
            approvals = mergeApproval(approvals, eventPayload);
            renderAgentApprovals(message, approvals);
          }
          if (eventPayload.type === "answer") {
            answerBuffer += eventPayload.content || "";
            setMessageContent(message, "assistant", answerBuffer);
          }
          if (eventPayload.type === "done") {
            cancelPendingApprovals();
            if (eventPayload.run) {
              renderAgentRun(message, eventPayload.run);
            }
            if (eventPayload.sessionId) {
              state.currentSessionId = eventPayload.sessionId;
            }
            if (eventPayload.memoryActivity) {
              renderMemoryActivity(
                message,
                eventPayload.memoryActivity,
              );
            }
            state.activeRunId = null;
            state.activeRunMessageId = null;
            renderActiveSession();
          }
          if (eventPayload.type === "error") {
            cancelPendingApprovals();
            renderAgentRun(message, eventPayload.run || null);
            state.activeRunId = null;
            state.activeRunMessageId = null;
            setMessageContent(
              message,
              "assistant",
              `请求失败：${eventPayload.message || "Agent运行失败。"}`,
            );
            renderActiveSession();
          }
          if (eventPayload.type === "cancelled") {
            cancelPendingApprovals();
            renderAgentRun(message, eventPayload.run || null);
            state.activeRunId = null;
            state.activeRunMessageId = null;
            setMessageContent(
              message,
              "assistant",
              answerBuffer || "生成已停止。",
            );
            renderActiveSession();
          }
        }
      }
      if (!answerBuffer) {
        const snapshot = await agentRunApi.get(runId);
        if (snapshot?.assistantMessageId && snapshot?.sessionId) {
          const messages = await request(
            `/api/sessions/${snapshot.sessionId}/messages`,
          );
          const saved = messages.find(
            (item) => item.id === snapshot.assistantMessageId,
          );
          if (saved) {
            setMessageContent(message, "assistant", saved.content);
            renderAgentTrace(message, saved.trace || []);
            renderAgentRun(message, saved.run || snapshot);
            renderMemoryActivity(
              message,
              saved.memoryActivity || null,
            );
          }
        }
      }
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

  window.addEventListener(
    "knowflow:react-agent-run-action",
    handleAgentRunAction,
  );

  return {
    continueSession,
    retryAnswer,
    startNewChat,
    stopChatGeneration,
    submitChat,
  };
}
