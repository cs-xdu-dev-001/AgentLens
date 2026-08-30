import { createAttachmentFlow } from "./attachmentFlow.js";
import { createAuthFlow } from "./authFlow.js";
import { bindReactControllerEvents } from "./bridgeBindings.js";
import { createCatalogSync } from "./catalogSync.js";
import { createChatFlow } from "./chatFlow.js";
import { state, messageRetryRequests } from "./controllerState.js";
import {
  clearActiveSessionPreference,
  readActiveSessionPreference,
  selectSessionToRestore,
  writeActiveSessionPreference,
} from "./sessionPersistence.js";
import {
  appendReactMessage,
  dispatchReactMessagesReset,
  updateReactMessageApprovals,
  updateReactMessageQuestions,
  updateReactMessageContent,
  updateReactMessageThinking,
  updateReactMessageToolCalls,
  updateReactMessageTrace,
  updateReactMessageRun,
  updateReactMessageMemoryActivity,
} from "./messageEvents.js";
import {
  notifyReactAuthStateUpdated,
  notifyReactKnowledgeOptionsUpdated,
  notifyReactKnowledgeSelectionUpdated,
  notifyReactModelOptionsUpdated,
  notifyReactModelSelectionUpdated,
  toast,
} from "./reactNotifications.js";
import { request } from "./request.js";

function setMessageContent(bubble, role, content) {
  const raw = String(content || "");
  updateReactMessageContent(bubble, role, raw);
}

function setMessageThinking(bubble, enabled) {
  updateReactMessageThinking(bubble, enabled);
}

function dispatchReactEvent(name, detail = {}) {
  window.dispatchEvent(new CustomEvent(name, { detail }));
}

function switchPage(page) {
  dispatchReactEvent("knowflow:react-page-activated", { page });
}

function renderReferences(references) {
  dispatchReactEvent("knowflow:react-references-updated", { references });
}

function openRetrievalDrawerFromRun(retrievalRun) {
  if (!retrievalRun?.id) return;
  toast(`检索记录 #${retrievalRun.id} 已保存，可在证据面板查看质量详情。`);
}

function renderRagQuality(ragQuality, retrievalRun) {
  dispatchReactEvent("knowflow:react-rag-quality-updated", { ragQuality, retrievalRun });
}

function renderToolTimeline(message, calls) {
  const toolCalls = Array.isArray(calls) ? calls : [];
  updateReactMessageToolCalls(message, toolCalls);
  dispatchReactEvent("knowflow:react-tool-timeline-updated", {
    messageId: message?.messageId || "",
    toolCalls,
  });
}

function renderAgentTrace(message, trace) {
  updateReactMessageTrace(message, trace);
  dispatchReactEvent(
    "knowflow:react-agent-trace-updated",
    {
      messageId: message?.messageId || "",
      trace: Array.isArray(trace) ? trace : [],
    },
  );
}

function renderAgentApprovals(message, approvals) {
  updateReactMessageApprovals(message, approvals);
  dispatchReactEvent(
    "knowflow:react-agent-approvals-updated",
    {
      messageId: message?.messageId || "",
      approvals: Array.isArray(approvals) ? approvals : [],
    },
  );
}

function renderAgentQuestions(message, questions) {
  updateReactMessageQuestions(message, questions);
}

function renderAgentRun(message, run) {
  updateReactMessageRun(message, run);
  const runId = String(run?.id || run?.runId || "");
  const active = ["planning", "running", "waiting_approval", "waiting_input"].includes(run?.status);
  if (active && runId && state.autoOpenedRunId !== runId) {
    state.autoOpenedRunId = runId;
    dispatchReactEvent("knowflow:react-drawer-open");
  }
  dispatchReactEvent(
    "knowflow:react-agent-run-updated",
    {
      messageId: message?.messageId || "",
      run: run || null,
    },
  );
}

function renderMemoryActivity(message, memoryActivity) {
  updateReactMessageMemoryActivity(message, memoryActivity);
}

function renderAttachmentTray() {
  dispatchReactEvent("knowflow:react-attachments-updated", { attachments: state.chatAttachments });
}

function renderActiveSession() {
  dispatchReactEvent("knowflow:react-active-session-updated", {
    sessionId: state.currentSessionId || "",
    title: state.currentSessionTitle || "",
  });
}

function requestComposerMenuClose() {
  window.dispatchEvent(new CustomEvent("knowflow:react-composer-menu-close"));
}

function requestReactSessionsRefresh() {
  dispatchReactEvent("knowflow:react-sessions-refresh-request", { currentSessionId: state.currentSessionId });
}

function appendMessage(role, content, options = {}) {
  return appendReactMessage(role, content, options);
}

function setSending(sending) {
  state.sending = sending;
  dispatchReactEvent("knowflow:react-sending-updated", { sending });
}

function requestComposerReset(options = {}) {
  dispatchReactEvent("knowflow:react-composer-reset", {
    focus: Boolean(options.focus),
    question: String(options.question || ""),
    skillId: options.skillId ?? null,
  });
}

function clearChatMessages(showWelcome = false) {
  messageRetryRequests.clear();
  dispatchReactMessagesReset(showWelcome);
}

function sessionOwner(userId = state.currentUser?.id) {
  return { id: userId };
}

function rememberActiveSession(sessionId, userId = state.currentUser?.id) {
  writeActiveSessionPreference(sessionOwner(userId), sessionId);
}

const authFlow = createAuthFlow({
  state,
  notifyReactAuthStateUpdated,
});

const catalogSync = createCatalogSync({
  state,
  request,
  notifyReactKnowledgeOptionsUpdated,
  notifyReactKnowledgeSelectionUpdated,
  notifyReactModelOptionsUpdated,
  switchPage,
});

const attachmentFlow = createAttachmentFlow({
  state,
  request,
  toast,
  renderAttachmentTray,
  requestComposerMenuClose,
});

const chatFlow = createChatFlow({
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
  renderAgentQuestions,
  renderAgentRun,
  renderAgentTrace,
  renderMemoryActivity,
  renderAttachmentTray,
  notifyReactKnowledgeSelectionUpdated,
  notifyReactModelSelectionUpdated,
  renderReferences,
  renderRagQuality,
  renderToolTimeline,
  openRetrievalDrawerFromRun,
  requestComposerReset,
  requestReactSessionsRefresh,
  switchPage,
  rememberActiveSession,
});

async function openRestoredSession(session, ownerUserId) {
  const modelId = catalogSync.resolveChatModelConfigId(
    session.chat_model_config_id || "",
  );
  const opened = await chatFlow.continueSession(session.id, {
    title: session.title,
    chatModelConfigId: modelId || null,
    ownerUserId,
  });
  if (!opened) return false;
  state.selectedChatModelConfigId = modelId;
  notifyReactModelSelectionUpdated(state.selectedChatModelConfigId);
  return true;
}

async function restoreActiveSession() {
  const ownerUserId = String(state.currentUser?.id ?? "");
  if (!ownerUserId) return false;
  const owner = sessionOwner(ownerUserId);
  const isCurrentOwner = () => (
    ownerUserId === String(state.currentUser?.id ?? "")
  );
  const preference = readActiveSessionPreference(owner);
  if (["new", "unavailable"].includes(preference.kind)) return false;

  let sessions;
  try {
    sessions = await request("/api/sessions");
  } catch {
    return false;
  }
  if (!isCurrentOwner()) return false;
  const candidate = selectSessionToRestore(sessions, preference);
  if (!candidate) {
    if (preference.kind === "session") clearActiveSessionPreference(owner);
    return false;
  }

  try {
    return await openRestoredSession(candidate, ownerUserId);
  } catch (error) {
    if (error?.name === "AbortError") return false;
    if (error?.status !== 404) return false;
    if (!isCurrentOwner()) return false;
    clearActiveSessionPreference(owner);

    const fallback = selectSessionToRestore(
      (Array.isArray(sessions) ? sessions : []).filter(
        (session) => String(session?.id || "") !== String(candidate.id),
      ),
      { kind: "missing", sessionId: "" },
    );
    if (!fallback) return false;
    try {
      return await openRestoredSession(fallback, ownerUserId);
    } catch {
      return false;
    }
  }
}

function bindEvents() {
  bindReactControllerEvents({
    abortChatActivity: chatFlow.abortChatActivity,
    state,
    clearChatMessages,
    continueSession: chatFlow.continueSession,
    handleComposerPaste: attachmentFlow.handleComposerPaste,
    notifyReactKnowledgeSelectionUpdated,
    notifyReactModelSelectionUpdated,
    refresh: catalogSync.refresh,
    refreshModels: catalogSync.refreshModels,
    removeChatAttachment: attachmentFlow.removeChatAttachment,
    removeQueuedChat: chatFlow.removeQueuedChat,
    retrieveQueuedChat: chatFlow.retrieveQueuedChat,
    reprioritizeQueuedChat: chatFlow.reprioritizeQueuedChat,
    renderActiveSession,
    renderCurrentUser: authFlow.renderCurrentUser,
    requestComposerReset,
    requestComposerMenuClose,
    resolveChatKnowledgeBaseId: catalogSync.resolveChatKnowledgeBaseId,
    resolveChatModelConfigId: catalogSync.resolveChatModelConfigId,
    resolveKnowledgeBaseId: catalogSync.resolveKnowledgeBaseId,
    restoreActiveSession,
    retryAnswer: chatFlow.retryAnswer,
    resumeQueuedChats: chatFlow.resumeQueuedChats,
    showAppScreen: authFlow.showAppScreen,
    showAuthScreen: authFlow.showAuthScreen,
    startNewChat: chatFlow.startNewChat,
    clearQueuedChats: chatFlow.clearQueuedChats,
    stopChatGeneration: chatFlow.stopChatGeneration,
    submitChat: chatFlow.submitChat,
    syncKnowledgeBasesFromReact: catalogSync.syncKnowledgeBasesFromReact,
    syncKnowledgeSelectionFromReact: catalogSync.syncKnowledgeSelectionFromReact,
    toast,
    uploadChatAttachment: attachmentFlow.uploadChatAttachment,
  });
}

async function bootstrap() {
  bindEvents();
  renderAttachmentTray();
  const authenticated = await authFlow.checkAuth();
  if (authenticated) {
    await catalogSync.refresh();
    await restoreActiveSession();
  }
}

export function startKnowFlowController() {
  if (window.__knowflowControllerStarted) {
    return;
  }
  window.__knowflowControllerStarted = true;
  bootstrap().catch((error) => {
    authFlow.showAuthScreen();
    toast(error.message || "启动失败", 4200, "error");
  });
}
