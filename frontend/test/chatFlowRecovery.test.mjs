import assert from "node:assert/strict";
import test from "node:test";

import { createChatFlow } from "../react/src/controller/chatFlow.js";
import { createAgentProjection, createAgentProjectionFromSnapshot, projectAgentEvent } from "../react/src/controller/agentEvents.js";
import { agentRecoveryActions } from "../react/src/controller/agentRunState.js";

const interruptedRun = {
  id: "run-recovery",
  sessionId: "session-recovery",
  assistantMessageId: 12,
  status: "interrupted",
  steps: [],
  trace: [{ stepId: "read", title: "读取项目", kind: "tool", status: "success" }],
  lastSequence: 3,
  failure: { code: "service_restart_interrupted", retryable: true },
};

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function sse(events) {
  return new Response(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(""), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function until(predicate) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.ok(predicate(), "flow did not settle");
}

async function withFlow(exercise, { run = interruptedRun, fetchHandler, requestHandler } = {}) {
  const original = { window: globalThis.window, CustomEvent: globalThis.CustomEvent, fetch: globalThis.fetch };
  const handlers = new Map();
  const events = [];
  const writes = [];
  const calls = [];
  const runs = [];
  const contents = [];
  const sessions = [];
  let messageSequence = 0;
  globalThis.CustomEvent = class {
    constructor(type, options = {}) { this.type = type; this.detail = options.detail; }
  };
  globalThis.window = {
    addEventListener(type, handler) { handlers.set(type, handler); },
    removeEventListener() {},
    dispatchEvent(event) { events.push(event); return true; },
    setTimeout: (callback) => setTimeout(callback, 0),
    clearTimeout,
  };
  const state = {
    currentUser: { id: 901 },
    currentSessionId: run.sessionId,
    currentSessionTitle: "恢复任务测试",
    activeChatController: null,
    activeRunId: null,
    activeRunMessageId: null,
    activeRunReconnectController: null,
    chatAttachments: [],
    chatQueue: [],
    chatQueuePaused: false,
    sending: false,
  };
  const noop = () => {};
  const messages = [
    { id: 11, role: "user", content: "检查项目并补齐测试" },
    { id: 12, role: "assistant", content: "已读取项目结构。", run, trace: run.trace },
  ];
  globalThis.fetch = async (path, options = {}) => {
    calls.push({ path, options });
    if (options.method === "POST") writes.push(path);
    const custom = await fetchHandler?.(path, options);
    if (custom) return custom;
    return Response.json({ code: 0, data: run });
  };
  const flow = createChatFlow({
    state,
    messageRetryRequests: new Map(),
    request: async (path, options) => (await requestHandler?.(path, options))
      ?? (path.includes("session-recovery") ? messages : []),
    toast: noop,
    appendMessage: () => ({ messageId: `message-${++messageSequence}` }),
    clearChatMessages: noop,
    setMessageContent: (message, role, content) => contents.push({ ...message, role, content }),
    setMessageThinking: noop,
    setSending: value => { state.sending = value; },
    renderActiveSession: () => sessions.push(state.currentSessionId),
    renderAgentApprovals: noop,
    renderAgentQuestions: noop,
    renderAgentRun: (message, nextRun) => runs.push({ message, run: nextRun }),
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
  });
  const act = (action = "resume") => handlers.get("knowflow:react-agent-run-action")({
    detail: { action, runId: run.id, messageId: "message-2" },
  });
  const dispatch = (type, detail) => handlers.get(type)({ type, detail });
  try {
    await exercise({ flow, state, events, writes, calls, runs, contents, sessions, act, dispatch });
  } finally {
    flow.abortChatActivity();
    Object.assign(globalThis, original);
  }
}

test("restoring an interrupted checkpoint hydrates composer recovery without starting execution", async () => {
  await withFlow(async ({ flow, events, writes }) => {
    await flow.continueSession("session-recovery");
    const composer = events.filter(event => event.type === "knowflow:react-agent-composer-state").at(-1)?.detail;
    assert.equal(composer?.mode, "failed");
    assert.equal(composer?.label, "任务已中断");
    assert.equal(composer?.runId, "run-recovery");
    assert.deepEqual(composer?.recoveryActions, ["continue", "retry"]);
    assert.deepEqual(writes, []);
  });
});

test("resume starts after the previous attempt cursor instead of stopping at its old error", async () => {
  await withFlow(async ({ flow, act, calls, runs, contents, state }) => {
    await flow.continueSession("session-recovery");
    await act();
    const stream = calls.find(call => call.path.includes("/events"));
    assert.equal(new URL(stream.path, "http://test").searchParams.get("afterSequence"), "3");
    assert.equal(runs.at(-1)?.run?.status, "completed");
    assert.equal(contents.at(-1)?.content, "恢复后的完整结果");
    assert.equal(state.sending, false);
  }, {
    fetchHandler: (path) => {
      if (!path.includes("/events")) return null;
      const after = Number(new URL(path, "http://test").searchParams.get("afterSequence") || 0);
      return sse([
        { type: "error", sequence: 3, runId: interruptedRun.id, message: "上一轮已经失败" },
        { type: "run_started", sequence: 4, run: { ...interruptedRun, status: "running" } },
        { type: "answer", sequence: 5, content: "恢复后的完整结果", final: true },
        { type: "done", sequence: 6, runId: interruptedRun.id, run: { ...interruptedRun, status: "completed" } },
      ].filter(event => event.sequence > after));
    },
  });
});

test("a terminal snapshot settles a cursor-aligned stream even without a repeated terminal event", () => {
  const result = projectAgentEvent(createAgentProjection(), {
    type: "run_snapshot",
    run: { ...interruptedRun, status: "completed" },
  });
  assert.equal(result.projection.terminal, "completed");
  assert.equal(result.projection.error, null);
});

test("switching sessions fences a late resume acknowledgement and cannot reopen the old run", async () => {
  const acknowledgement = deferred();
  const posted = deferred();
  await withFlow(async ({ flow, act, state, calls, runs }) => {
    await flow.continueSession("session-recovery");
    const resume = act();
    await posted.promise;
    await flow.continueSession("session-other");
    const runCount = runs.length;
    acknowledgement.resolve(Response.json({ code: 0, data: { ...interruptedRun, status: "running" } }));
    await resume;
    assert.equal(state.currentSessionId, "session-other");
    assert.equal(state.activeRunId, null);
    assert.equal(calls.filter(call => call.path.includes("/events")).length, 0);
    assert.equal(runs.length, runCount);
  }, {
    fetchHandler: (path, options) => {
      if (options.method === "POST") { posted.resolve(); return acknowledgement.promise; }
      if (path.includes("/events")) return sse([{ type: "done", run: { ...interruptedRun, status: "completed" } }]);
      return null;
    },
  });
});

test("only one execution recovery can be submitted while another is pending", async () => {
  const acknowledgement = deferred();
  const posted = deferred();
  await withFlow(async ({ flow, act, writes }) => {
    await flow.continueSession("session-recovery");
    const resume = act();
    await posted.promise;
    const restart = act("restart");
    acknowledgement.resolve(Response.json({ code: 0, data: { ...interruptedRun, status: "running" } }));
    await Promise.all([resume, restart]);
    assert.deepEqual(writes, ["/api/agent/runs/run-recovery/resume"]);
  }, {
    fetchHandler: (path, options) => {
      if (options.method === "POST") { posted.resolve(); return acknowledgement.promise; }
      if (path.includes("/events")) return sse([{ type: "done", run: { ...interruptedRun, status: "completed" } }]);
      return null;
    },
  });
});

for (const [kind, status, required, resolved] of [
  ["approval", "waiting_approval", "approval_required", "approval_resolved"],
  ["question", "waiting_input", "user_question_required", "user_question_resolved"],
]) {
  test(`${kind} resolution reconnects after the pause cursor without replaying the old prompt`, async () => {
    const waitingRun = { ...interruptedRun, status, failure: null };
    let streams = 0;
    await withFlow(async ({ flow, dispatch, state, calls, runs, writes, contents }) => {
      await flow.continueSession("session-recovery");
      await until(() => !state.sending);
      await dispatch(`knowflow:react-agent-${kind}-resume`, { runId: waitingRun.id });
      const reconnect = calls.filter(call => call.path.includes("/events")).at(-1);
      assert.equal(new URL(reconnect.path, "http://test").searchParams.get("afterSequence"), "3");
      assert.equal(runs.at(-1)?.run?.status, "completed");
      assert.equal(contents.at(-1)?.content, "确认后已完成");
      assert.deepEqual(writes, []);
    }, {
      run: waitingRun,
      fetchHandler: path => {
        if (!path.includes("/events")) return null;
        if (++streams === 1) return sse([{ type: "run_snapshot", run: waitingRun }]);
        const after = Number(new URL(path, "http://test").searchParams.get("afterSequence") || 0);
        return sse([
          { type: "run_snapshot", run: waitingRun },
          { type: required, sequence: 3, runId: waitingRun.id, approvalId: "approval-1", questionId: "question-1" },
          { type: resolved, sequence: 4, runId: waitingRun.id, approvalId: "approval-1", questionId: "question-1", status: "approved" },
          { type: "run_snapshot", run: waitingRun },
          { type: "run_started", sequence: 5, run: { ...waitingRun, status: "running" } },
          { type: "answer", sequence: 6, content: "确认后已完成", final: true },
          { type: "done", sequence: 7, run: { ...waitingRun, status: "completed" } },
        ].filter(event => event.type === "run_snapshot" || event.sequence > after));
      },
    });
  });
}

test("switching sessions while an approval resume is pending fences its acknowledgement", async () => {
  const waitingRun = { ...interruptedRun, status: "waiting_approval", failure: null };
  const acknowledgement = deferred();
  const posted = deferred();
  await withFlow(async ({ flow, dispatch, state, calls }) => {
    await flow.continueSession("session-recovery");
    await until(() => !state.sending);
    const resume = dispatch("knowflow:react-agent-approval-resume", { runId: waitingRun.id, resumeRequired: true });
    await posted.promise;
    await flow.continueSession("session-other");
    acknowledgement.resolve(Response.json({ code: 0, data: { ...waitingRun, status: "running" } }));
    await resume;
    assert.equal(state.currentSessionId, "session-other");
    assert.equal(state.activeRunId, null);
    assert.equal(calls.filter(call => call.path.includes("/events")).length, 1);
  }, {
    run: waitingRun,
    fetchHandler: (path, options) => {
      if (options.method === "POST") { posted.resolve(); return acknowledgement.promise; }
      if (path.includes("/events")) return sse([{ type: "run_snapshot", run: waitingRun }]);
      return null;
    },
  });
});

test("snapshot hydration retains work evidence and clears a previous attempt terminal on active status", () => {
  const failed = createAgentProjectionFromSnapshot(interruptedRun);
  const metadata = {
    ...interruptedRun,
    status: "running",
    failure: null,
    context: { usedTokens: 1200, maxTokens: 10000 },
    usage: { totalTokens: 1200 },
    artifacts: [{ artifactId: "change-1", path: "src/app.js" }],
    verifications: [{ id: "test-1", kind: "test", tool: "npm_test", status: "passed" }],
  };
  const active = createAgentProjectionFromSnapshot(metadata, failed);
  assert.equal(active.terminal, null);
  assert.equal(active.error, null);
  assert.equal(active.run.status, "running");
  assert.deepEqual(active.artifacts, metadata.artifacts);
  assert.deepEqual(active.verifications, metadata.verifications);
  assert.deepEqual(active.context, metadata.context);
  assert.equal(active.lastSequence, 3);
});

test("only supported recovery actions are offered for checkpoint, cancelled and non-retryable runs", () => {
  assert.deepEqual(agentRecoveryActions(interruptedRun), ["continue", "retry"]);
  assert.deepEqual(agentRecoveryActions({ ...interruptedRun, status: "cancelled" }), ["retry"]);
  assert.deepEqual(agentRecoveryActions({ ...interruptedRun, failure: { code: "langgraph_checkpoint_not_found" } }), ["retry"]);
  assert.deepEqual(agentRecoveryActions({ ...interruptedRun, failure: { retryable: false } }), []);
  assert.deepEqual(agentRecoveryActions({ ...interruptedRun, recoveryActions: ["fix", "fix", "unknown"] }), ["fix"]);
});

test("a live completed status update does not end the stream before its final answer", async () => {
  await withFlow(async ({ flow, act, contents }) => {
    await flow.continueSession("session-recovery");
    await act();
    assert.equal(contents.at(-1)?.content, "完整回答不能被状态更新截断");
  }, {
    fetchHandler: path => path.includes("/events") ? sse([
      { type: "run_updated", sequence: 4, run: { ...interruptedRun, status: "completed" } },
      { type: "answer", sequence: 5, content: "完整回答不能被状态更新截断", final: true },
      { type: "done", sequence: 6, run: { ...interruptedRun, status: "completed" } },
    ]) : null,
  });
});

test("a terminal-only snapshot replaces the cached partial answer with the persisted result", async () => {
  let completed = false;
  const completedRun = { ...interruptedRun, status: "completed", lastSequence: 6, failure: null };
  await withFlow(async ({ flow, act, contents, state }) => {
    await flow.continueSession("session-recovery");
    await act();
    assert.equal(contents.at(-1)?.content, "持久化的完整回答");
    assert.equal(state.activeRunId, null);
  }, {
    requestHandler: path => completed && path.includes("/messages")
      ? [{ id: 12, role: "assistant", content: "持久化的完整回答", run: completedRun }]
      : null,
    fetchHandler: path => {
      if (path.includes("/events")) {
        completed = true;
        return sse([{ type: "run_snapshot", run: completedRun }]);
      }
      return completed ? Response.json({ code: 0, data: completedRun }) : null;
    },
  });
});

test("a recovery action from a discarded message cannot launch work in another session", async () => {
  await withFlow(async ({ flow, act, state, writes }) => {
    await flow.continueSession("session-recovery");
    await flow.continueSession("session-other");
    await act("restart");
    await act("fix");
    assert.deepEqual(writes, []);
    assert.equal(state.currentSessionId, "session-other");
  }, {
    fetchHandler: path => path.includes("/events")
      ? sse([{ type: "done", run: { ...interruptedRun, status: "completed" } }])
      : null,
  });
});

test("an accepted resume waits for the worker transition instead of failing on the old snapshot", async () => {
  await withFlow(async ({ flow, act, contents, runs }) => {
    await flow.continueSession("session-recovery");
    await act();
    assert.equal(runs.at(-1)?.run?.status, "completed");
    assert.equal(contents.at(-1)?.content, "已从检查点继续");
  }, {
    fetchHandler: path => path.includes("/events") ? sse([
      { type: "run_snapshot", run: interruptedRun },
      { type: "run_updated", sequence: 4, run: { ...interruptedRun, status: "running" } },
      { type: "answer", sequence: 5, content: "已从检查点继续", final: true },
      { type: "done", sequence: 6, run: { ...interruptedRun, status: "completed" } },
    ]) : null,
  });
});

test("cancelling a restored paused run consumes cancellation events rather than settling at the old prompt", async () => {
  const waitingRun = { ...interruptedRun, status: "waiting_approval", failure: null };
  let streams = 0;
  await withFlow(async ({ flow, act, state, runs, writes }) => {
    await flow.continueSession("session-recovery");
    await until(() => !state.sending);
    await act("cancel");
    assert.equal(runs.at(-1)?.run?.status, "cancelled");
    assert.equal(state.activeRunId, null);
    assert.deepEqual(writes, ["/api/agent/runs/run-recovery/cancel"]);
  }, {
    run: waitingRun,
    fetchHandler: path => {
      if (path.endsWith("/cancel")) return Response.json({ code: 0, data: { ...waitingRun, status: "cancelling" } });
      if (!path.includes("/events")) return null;
      if (++streams === 1) return sse([{ type: "run_snapshot", run: waitingRun }]);
      return sse([
        { type: "approval_resolved", sequence: 4, approvalId: "approval-1", status: "cancelled" },
        { type: "cancelled", sequence: 5, run: { ...waitingRun, status: "cancelled" } },
      ]);
    },
  });
});

test("fix after reload uses that message's original task rather than another session's last request", async () => {
  await withFlow(async ({ flow, act, state, calls }) => {
    await flow.continueSession("session-recovery");
    state.lastChatRequest = { question: "其他会话的问题" };
    await act("fix");
    const sent = calls.find(call => call.path === "/api/chat/stream");
    assert.ok(sent, "fix must submit the restored task");
    const payload = JSON.parse(sent.options.body);
    assert.ok(payload.question.includes("检查项目并补齐测试"));
    assert.ok(!payload.question.includes("其他会话的问题"));
    assert.equal(payload.sessionId, "session-recovery");
  }, {
    fetchHandler: path => path === "/api/chat/stream"
      ? sse([{ type: "done", run: { ...interruptedRun, id: "run-fix", status: "completed" } }])
      : null,
  });
});
