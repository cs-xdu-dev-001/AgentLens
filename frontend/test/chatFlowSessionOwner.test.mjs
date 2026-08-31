import assert from "node:assert/strict";
import test from "node:test";

import { createChatFlow } from "../react/src/controller/chatFlow.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function createWindowStub() {
  return {
    addEventListener: () => {},
    clearTimeout,
    dispatchEvent: () => true,
    setTimeout,
  };
}

test("a session response cannot cross an authenticated user boundary", async () => {
  const originalWindow = globalThis.window;
  const originalCustomEvent = globalThis.CustomEvent;
  globalThis.window = createWindowStub();
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
    }
  };

  const response = deferred();
  const remembered = [];
  let clearedMessages = 0;
  const state = {
    activeChatController: null,
    activeRunId: null,
    activeRunMessageId: null,
    activeRunReconnectController: null,
    chatAttachments: [],
    chatQueue: [],
    chatQueueBlockReason: "",
    chatQueuePaused: false,
    currentSessionId: null,
    currentSessionTitle: "",
    currentUser: { id: 1 },
  };
  const noop = () => {};

  try {
    const flow = createChatFlow({
      state,
      messageRetryRequests: new Map(),
      request: () => response.promise,
      toast: noop,
      appendMessage: noop,
      clearChatMessages: () => { clearedMessages += 1; },
      setMessageContent: noop,
      setMessageThinking: noop,
      setSending: noop,
      renderActiveSession: noop,
      renderAgentApprovals: noop,
      renderAgentQuestions: noop,
      renderAgentRun: noop,
      renderAgentTrace: noop,
      renderMemoryActivity: noop,
      renderAttachmentTray: noop,
      notifyReactKnowledgeSelectionUpdated: noop,
      notifyReactModelSelectionUpdated: noop,
      renderReferences: noop,
      renderRagQuality: noop,
      renderToolTimeline: noop,
      openRetrievalDrawerFromRun: noop,
      requestComposerReset: noop,
      requestReactSessionsRefresh: noop,
      switchPage: noop,
      rememberActiveSession: (sessionId) => remembered.push(sessionId),
    });

    const opening = flow.continueSession("session-a");
    state.currentUser = { id: 2 };
    response.resolve([]);

    assert.equal(await opening, false);
    assert.equal(state.currentSessionId, null);
    assert.equal(clearedMessages, 0);
    assert.deepEqual(remembered, []);
  } finally {
    globalThis.window = originalWindow;
    globalThis.CustomEvent = originalCustomEvent;
  }
});

test("a global approval jump focuses the requested approval after session hydration", async () => {
  const originalWindow = globalThis.window;
  const originalCustomEvent = globalThis.CustomEvent;
  const events = [];
  globalThis.window = {
    ...createWindowStub(),
    dispatchEvent: (event) => {
      events.push(event);
      return true;
    },
  };
  globalThis.CustomEvent = class CustomEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.detail = options.detail;
    }
  };
  const state = {
    activeChatController: null,
    activeRunId: null,
    activeRunMessageId: null,
    activeRunReconnectController: null,
    chatAttachments: [],
    chatQueue: [],
    chatQueueBlockReason: "",
    chatQueuePaused: false,
    currentSessionId: null,
    currentSessionTitle: "",
    currentUser: { id: 1 },
  };
  const noop = () => {};
  try {
    const flow = createChatFlow({
      state,
      messageRetryRequests: new Map(),
      request: async () => [],
      toast: noop,
      appendMessage: noop,
      clearChatMessages: noop,
      setMessageContent: noop,
      setMessageThinking: noop,
      setSending: noop,
      renderActiveSession: noop,
      renderAgentApprovals: noop,
      renderAgentQuestions: noop,
      renderAgentRun: noop,
      renderAgentTrace: noop,
      renderMemoryActivity: noop,
      renderAttachmentTray: noop,
      notifyReactKnowledgeSelectionUpdated: noop,
      notifyReactModelSelectionUpdated: noop,
      renderReferences: noop,
      renderRagQuality: noop,
      renderToolTimeline: noop,
      openRetrievalDrawerFromRun: noop,
      requestComposerReset: noop,
      requestReactSessionsRefresh: noop,
      switchPage: noop,
      rememberActiveSession: noop,
    });
    assert.equal(await flow.continueSession("session-focus", {
      approvalId: "apr_focus",
      approvalMessageId: 42,
    }), true);
    await new Promise((resolve) => setTimeout(resolve, 10));
    const focus = events.find(
      (event) => event.type === "knowflow:react-agent-interaction-focus",
    );
    assert.deepEqual(focus?.detail, {
      approvalId: "apr_focus",
      messageId: 42,
    });
  } finally {
    globalThis.window = originalWindow;
    globalThis.CustomEvent = originalCustomEvent;
  }
});
