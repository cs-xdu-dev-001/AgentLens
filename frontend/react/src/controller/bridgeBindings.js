async function copyAssistantMessageContent(content, toast) {
  await navigator.clipboard.writeText(content || "");
  toast("答案已复制");
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
  reprioritizeQueuedChat,
  renderActiveSession,
  renderCurrentUser,
  requestComposerMenuClose,
  resolveChatKnowledgeBaseId,
  resolveChatModelConfigId,
  resolveKnowledgeBaseId,
  retryAnswer,
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
    }
    showAppScreen();
    if (detail.message) toast(detail.message);
    refresh().catch((error) => toast(error.message || "刷新失败", 4200, "error"));
  });

  window.addEventListener("knowflow:react-auth-logout", (event) => {
    const detail = event.detail || {};
    state.currentUser = null;
    state.currentSessionId = null;
    clearQueuedChats();
    renderActiveSession();
    clearChatMessages();
    showAuthScreen(state.oauthProviders);
    if (detail.message) toast(detail.message);
  });

  window.addEventListener("knowflow:react-message-copy", (event) => {
    const content = event.detail?.rawContent || "";
    copyAssistantMessageContent(content, toast).catch(() => toast("复制失败，请重试", 4200, "error"));
  });

  window.addEventListener("knowflow:react-message-retry", (event) => {
    retryAnswer(event.detail?.messageId || null).catch((error) => toast(error.message || "重试失败", 4200, "error"));
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
  window.addEventListener("knowflow:react-chat-enter-submit", (event) =>
    submitChat({ question: event.detail?.question, skillId: event.detail?.skillId }).catch((error) => toast(error.message || "发送失败", 4200, "error")),
  );
  window.addEventListener("knowflow:react-chat-stop", () => stopChatGeneration());
  window.addEventListener("knowflow:react-chat-queue-action", (event) => {
    const action = event.detail?.action;
    if (action === "remove") removeQueuedChat(event.detail?.requestId);
    if (action === "clear") clearQueuedChats();
    if (action === "resume") resumeQueuedChats();
    if (action === "priority") {
      reprioritizeQueuedChat(event.detail?.requestId, event.detail?.priority);
    }
  });

  window.addEventListener("knowflow:react-attachment-remove", (event) => removeChatAttachment(event.detail?.attachmentId));
}
