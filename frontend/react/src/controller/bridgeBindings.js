import { copySelection } from "./copyPresentation.js";

const ANSWER_COPY_SUCCESS_TOAST = "答案已复制";

async function copyAssistantMessageContent(content, toast, label = "答案") {
  await navigator.clipboard.writeText(content || "");
  toast(label === "答案" ? ANSWER_COPY_SUCCESS_TOAST : `${label}已复制`);
}

export function bindReactControllerEvents({
  state,
  clearChatMessages,
  clearQueuedChats,
  continueSession,
  handleComposerPaste,
  notifyReactKnowledgeSelectionUpdated,
  notifyReactModelSelectionUpdated,
  refresh,
  refreshModels,
  removeChatAttachment,
  removeQueuedChat,
  retrieveQueuedChat,
  reprioritizeQueuedChat,
  restoreQueuedChats,
  renderActiveSession,
  renderCurrentUser,
  requestComposerReset,
  requestComposerMenuClose,
  resolveChatKnowledgeBaseId,
  resolveChatModelConfigId,
  resolveKnowledgeBaseId,
  retryAnswer,
  rewindSessionAtMessage,
  resumeQueuedChats,
  showAppScreen,
  showAuthScreen,
  startNewChat,
  stopChatGeneration,
  submitChat,
  syncKnowledgeBasesFromReact,
  syncKnowledgeSelectionFromReact,
  toast,
  uploadChatAttachment,
}) {
  window.addEventListener("knowflow:react-auth-success", (event) => {
    const detail = event.detail || {};
    if (detail.user) {
      state.currentUser = detail.user;
      renderCurrentUser();
      restoreQueuedChats();
    }
    showAppScreen();
    if (detail.message) toast(detail.message);
    refresh().catch((error) => toast(error.message || "刷新失败", 4200, "error"));
  });

  window.addEventListener("knowflow:react-auth-logout", (event) => {
    const detail = event.detail || {};
    clearQueuedChats({ preserveStored: true });
    state.currentUser = null;
    state.currentSessionId = null;
    state.currentSessionTitle = "";
    renderActiveSession();
    clearChatMessages();
    showAuthScreen(state.oauthProviders);
    if (detail.message) toast(detail.message);
  });

  window.addEventListener("knowflow:react-active-session-updated", (event) => {
    const detail = event.detail || {};
    if (String(detail.sessionId || "") !== String(state.currentSessionId || "")) return;
    if (Object.prototype.hasOwnProperty.call(detail, "title")) {
      state.currentSessionTitle = String(detail.title || "").trim();
    }
  });

  window.addEventListener("knowflow:react-message-copy", (event) => {
    const detail = event.detail || {};
    const result = copySelection({
      assistant: detail.rawContent || "",
      assistantMessage: detail.assistantMessage,
      messages: detail.messages,
      args: detail.args,
    });
    if (!result.ok) {
      toast(result.message, 3200, "neutral");
      return;
    }
    copyAssistantMessageContent(result.text, toast, result.label)
      .catch(() => toast("复制失败，请重试", 4200, "error"));
  });

  window.addEventListener("knowflow:react-message-edit", (event) => {
    const question = String(event.detail?.rawContent || "").trim();
    if (!question) {
      toast("这条消息没有可编辑的内容", 4200, "error");
      return;
    }
    requestComposerReset({ focus: true, question });
    toast("已放回输入框，可修改后重新发送");
  });

  window.addEventListener("knowflow:react-message-retry", (event) => {
    retryAnswer(event.detail?.messageId || null).catch((error) => toast(error.message || "重试失败", 4200, "error"));
  });

  window.addEventListener("knowflow:react-message-rewind", (event) => {
    rewindSessionAtMessage(
      event.detail?.sourceMessageId,
      event.detail?.rawContent,
    )
      .then((branch) => {
        if (branch) toast("已从所选问题创建新分支，原会话和文件保持不变");
      })
      .catch((error) => toast(error.message || "回到历史消息失败", 4200, "error"));
  });

  window.addEventListener("knowflow:react-page-change", (event) => {
    const page = event.detail?.page;
    if (page) window.dispatchEvent(new CustomEvent("knowflow:react-page-activated", { detail: { page } }));
  });

  window.addEventListener("knowflow:react-new-chat", () => startNewChat());
  window.addEventListener("knowflow:react-refresh", () => refresh().catch((error) => toast(error.message || "刷新失败", 4200, "error")));

  window.addEventListener("knowflow:react-knowledge-selection-sync", (event) =>
    syncKnowledgeSelectionFromReact(event.detail || {}).catch((error) => toast(error.message || "打开知识库失败", 4200, "error")),
  );
  window.addEventListener("knowflow:react-knowledge-bases-sync", (event) =>
    syncKnowledgeBasesFromReact(event.detail || {}).catch((error) => toast(error.message || "同步知识库失败", 4200, "error")),
  );

  window.addEventListener("knowflow:react-chat-files-change", async (event) => {
    const files = Array.from(event.detail?.files || []);
    try {
      for (const file of files) await uploadChatAttachment(file);
    } catch (error) {
      toast(error.message || "附件上传失败", 4200, "error");
    }
    if (event.detail?.input) event.detail.input.value = "";
    requestComposerMenuClose();
  });

  window.addEventListener("knowflow:react-composer-kb-change", (event) => {
    const value = resolveChatKnowledgeBaseId(event.detail?.value || "");
    state.selectedChatKnowledgeBaseId = value;
    notifyReactKnowledgeSelectionUpdated(undefined, { selectedChatKnowledgeBaseId: value });
  });

  window.addEventListener("knowflow:react-chat-model-change", (event) => {
    const value = resolveChatModelConfigId(event.detail?.value || "");
    state.selectedChatModelConfigId = value;
    notifyReactModelSelectionUpdated(value);
  });

  window.addEventListener("knowflow:react-chat-reasoning-change", (event) => {
    const value = String(event.detail?.value || "default");
    state.selectedReasoningEffort = [
      "default", "none", "low", "medium", "high", "xhigh", "max",
    ].includes(value) ? value : "default";
    window.dispatchEvent(new CustomEvent(
      "knowflow:react-reasoning-selection-updated",
      { detail: { value: state.selectedReasoningEffort } },
    ));
  });

  window.addEventListener("knowflow:react-chat-kb-change", (event) => {
    const value = resolveChatKnowledgeBaseId(event.detail?.value || "");
    state.selectedChatKnowledgeBaseId = value;
    notifyReactKnowledgeSelectionUpdated(undefined, { selectedChatKnowledgeBaseId: value });
  });

  window.addEventListener("knowflow:react-session-continue", (event) => {
    const detail = event.detail || {};
    const modelId = resolveChatModelConfigId(
      detail.chatModelConfigId || "",
    );
    continueSession(detail.sessionId, {
      title: detail.title,
      chatModelConfigId: detail.chatModelConfigId ?? null,
    })
      .then((opened) => {
        if (!opened) return;
        state.selectedChatModelConfigId = modelId;
        notifyReactModelSelectionUpdated(modelId);
      })
      .catch((error) => {
        if (error?.name !== "AbortError") {
          toast(error.message || "打开任务失败", 4200, "error");
        }
      });
  });

  window.addEventListener("knowflow:react-models-refresh-request", () =>
    refreshModels().catch((error) => toast(error.message || "刷新模型失败", 4200, "error")),
  );

  window.addEventListener("knowflow:react-retrieval-kb-change", (event) => {
    state.selectedRetrievalKnowledgeBaseId = resolveKnowledgeBaseId(event.detail?.value || "") || "";
    notifyReactKnowledgeSelectionUpdated(undefined, { selectedRetrievalKnowledgeBaseId: state.selectedRetrievalKnowledgeBaseId || "" });
  });

  window.addEventListener("knowflow:react-chat-submit", (event) =>
    submitChat({ question: event.detail?.question, skillId: event.detail?.skillId }).catch((error) => toast(error.message || "发送失败", 4200, "error")),
  );
  window.addEventListener("knowflow:react-chat-paste", (event) =>
    handleComposerPaste(event.detail || {}).catch((error) => toast(error.message || "粘贴失败", 4200, "error")),
  );
  window.addEventListener("knowflow:react-attachments-replace", (event) => {
    state.chatAttachments = (Array.isArray(event.detail?.attachments) ? event.detail.attachments : [])
      .map((attachment) => ({ ...attachment }));
    renderAttachmentTray();
  });
  window.addEventListener("knowflow:react-chat-enter-submit", (event) =>
    submitChat({ question: event.detail?.question, skillId: event.detail?.skillId }).catch((error) => toast(error.message || "发送失败", 4200, "error")),
  );
  window.addEventListener("knowflow:react-chat-stop", () => stopChatGeneration());
  window.addEventListener("knowflow:react-chat-queue-action", (event) => {
    const action = event.detail?.action;
    if (action === "remove") removeQueuedChat(event.detail?.requestId);
    if (action === "retrieve") retrieveQueuedChat(event.detail?.requestId);
    if (action === "clear") clearQueuedChats();
    if (action === "resume") resumeQueuedChats();
    if (action === "priority") {
      reprioritizeQueuedChat(event.detail?.requestId, event.detail?.priority);
    }
  });

  window.addEventListener("knowflow:react-attachment-remove", (event) => removeChatAttachment(event.detail?.attachmentId));
}
