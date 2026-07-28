export const state = {
  models: [],
  knowledgeBases: [],
  currentSessionId: null,
  selectedKnowledgeBaseId: null,
  selectedChatModelConfigId: "",
  selectedEmbeddingModelConfigId: "",
  selectedChatKnowledgeBaseId: "",
  selectedDocumentKnowledgeBaseId: null,
  selectedRetrievalKnowledgeBaseId: null,
  chatAttachments: [],
  currentUser: null,
  oauthProviders: {},
  sending: false,
  activeChatController: null,
  activeRunReconnectController: null,
  activeRunId: null,
  activeRunMessageId: null,
  lastChatRequest: null,
};

export const messageRetryRequests = new Map();
