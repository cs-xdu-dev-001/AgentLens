import {
  resolveChatKnowledgeBaseId as resolveChatKnowledgeBaseIdFromList,
  resolveChatModelConfigId as resolveChatModelConfigIdFromList,
  resolveEmbeddingModelConfigId as resolveEmbeddingModelConfigIdFromList,
  resolveKnowledgeBaseId as resolveKnowledgeBaseIdFromList,
} from "./selectionResolvers.js";

export function createCatalogSync({
  state,
  request,
  notifyReactKnowledgeOptionsUpdated,
  notifyReactKnowledgeSelectionUpdated,
  notifyReactModelOptionsUpdated,
  switchPage,
}) {
  function resolveChatModelConfigId(preferredId = "") {
    return resolveChatModelConfigIdFromList(state.models, preferredId);
  }

  function resolveEmbeddingModelConfigId(preferredId = "") {
    return resolveEmbeddingModelConfigIdFromList(state.models, preferredId);
  }

  function resolveKnowledgeBaseId(preferredId = null) {
    return resolveKnowledgeBaseIdFromList(state.knowledgeBases, preferredId);
  }

  function resolveChatKnowledgeBaseId(preferredId = "") {
    return resolveChatKnowledgeBaseIdFromList(state.knowledgeBases, preferredId);
  }

  function renderModels() {
    state.selectedChatModelConfigId = resolveChatModelConfigId(state.selectedChatModelConfigId);
    state.selectedEmbeddingModelConfigId = resolveEmbeddingModelConfigId(state.selectedEmbeddingModelConfigId);
    notifyReactModelOptionsUpdated(state.models, state.selectedChatModelConfigId, state.selectedEmbeddingModelConfigId);
  }

  function syncKnowledgeSelectControls(selectedKnowledgeBaseId) {
    const selectedValue = selectedKnowledgeBaseId || "";
    state.selectedDocumentKnowledgeBaseId = resolveKnowledgeBaseId(selectedValue) || "";
    state.selectedRetrievalKnowledgeBaseId = resolveKnowledgeBaseId(selectedValue) || "";
    state.selectedChatKnowledgeBaseId = resolveChatKnowledgeBaseId(selectedValue);
  }

  async function syncKnowledgeSelectionFromReact(detail = {}) {
    const selectedKnowledgeBaseId = resolveKnowledgeBaseId(detail.selectedKnowledgeBaseId);
    state.selectedKnowledgeBaseId = selectedKnowledgeBaseId;
    syncKnowledgeSelectControls(selectedKnowledgeBaseId);
    notifyReactKnowledgeSelectionUpdated(selectedKnowledgeBaseId, {
      selectedChatKnowledgeBaseId: selectedKnowledgeBaseId || "",
      selectedDocumentKnowledgeBaseId: selectedKnowledgeBaseId || "",
      selectedRetrievalKnowledgeBaseId: selectedKnowledgeBaseId || "",
    });
    switchPage("knowledge");
  }

  async function syncKnowledgeBasesFromReact(detail = {}) {
    if (Array.isArray(detail.knowledgeBases)) {
      state.knowledgeBases = detail.knowledgeBases;
    }
    state.selectedKnowledgeBaseId = resolveKnowledgeBaseId(detail.selectedKnowledgeBaseId || state.selectedKnowledgeBaseId);
    syncKnowledgeSelectControls(state.selectedKnowledgeBaseId);
    renderKnowledgeBases();
  }

  function renderKnowledgeBases() {
    const currentDocKb = resolveKnowledgeBaseId(state.selectedDocumentKnowledgeBaseId || state.selectedKnowledgeBaseId);
    const currentChatKb = resolveChatKnowledgeBaseId(state.selectedChatKnowledgeBaseId || "");
    const currentRetrievalKb = resolveKnowledgeBaseId(state.selectedRetrievalKnowledgeBaseId || state.selectedKnowledgeBaseId);

    state.selectedKnowledgeBaseId = resolveKnowledgeBaseId(state.selectedKnowledgeBaseId || currentDocKb);

    const selectedDocumentKnowledgeBaseId = currentDocKb || state.selectedKnowledgeBaseId || state.knowledgeBases[0]?.id || "";
    const selectedRetrievalKnowledgeBaseId = currentRetrievalKb || state.selectedKnowledgeBaseId || state.knowledgeBases[0]?.id || "";
    state.selectedDocumentKnowledgeBaseId = selectedDocumentKnowledgeBaseId || "";
    state.selectedRetrievalKnowledgeBaseId = selectedRetrievalKnowledgeBaseId || "";
    state.selectedChatKnowledgeBaseId = currentChatKb || "";
    notifyReactKnowledgeOptionsUpdated(state.knowledgeBases, state.selectedKnowledgeBaseId, {
      selectedChatKnowledgeBaseId: state.selectedChatKnowledgeBaseId,
      selectedDocumentKnowledgeBaseId,
      selectedRetrievalKnowledgeBaseId,
    });
  }

  async function refreshModels() {
    state.models = await request("/api/model-configs");
    renderModels();
  }

  async function refreshKnowledgeBases() {
    state.knowledgeBases = await request("/api/knowledge-bases");
    renderKnowledgeBases();
  }

  async function refresh() {
    await Promise.all([
      refreshModels(),
      refreshKnowledgeBases(),
    ]);
  }

  return {
    refresh,
    refreshKnowledgeBases,
    refreshModels,
    renderKnowledgeBases,
    renderModels,
    resolveChatKnowledgeBaseId,
    resolveChatModelConfigId,
    resolveEmbeddingModelConfigId,
    resolveKnowledgeBaseId,
    syncKnowledgeBasesFromReact,
    syncKnowledgeSelectionFromReact,
  };
}
