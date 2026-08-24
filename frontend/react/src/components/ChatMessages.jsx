import { memo, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { memoryApi } from "../api/client.js";
import { redactEmailAddresses, renderMarkdown } from "../controller/markdown.js";
import {
  memoryActivityTrace,
  mergeMemoryActivityTrace,
  publishMemoryActivity,
} from "../controller/memoryActivity.js";
import { AgentApprovalPrompt } from "./AgentApprovalPrompt.jsx";
import { AgentQuestionPrompt } from "./AgentQuestionPrompt.jsx";
import { AgentDeliveryCard } from "./AgentDeliveryCard.jsx";
import { AgentEvidenceStrip } from "./AgentEvidenceStrip.jsx";
import { AgentTraceStrip } from "./AgentTraceStrip.jsx";
import { AgentTaskPlan } from "./AgentTaskPlan.jsx";
import { AgentThinkingOrb } from "./AgentThinkingOrb.jsx";
import {
  isChatViewportPinned,
  shouldFollowChatUpdate,
} from "./chatScrollState.js";
import {
  activeAgentInteractionOwner,
  pendingAgentInteractions,
} from "./agentRunPresentation.js";

const actionEvents = {
  copy: "knowflow:react-message-copy",
  edit: "knowflow:react-message-edit",
  retry: "knowflow:react-message-retry",
  rewind: "knowflow:react-message-rewind",
};

const ACTIVE_RUN_STATUSES = new Set([
  "pending",
  "planning",
  "queued",
  "running",
  "started",
  "waiting",
  "waiting_approval",
  "waiting_input",
]);

function compactTaskAnchorText(value, maxLength = 180) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

export function activeTaskAnchor(messages = []) {
  const safeMessages = Array.isArray(messages) ? messages : [];
  let assistantIndex = -1;
  for (let index = safeMessages.length - 1; index >= 0; index -= 1) {
    const message = safeMessages[index];
    if (message?.role !== "assistant") continue;
    const status = String(message.run?.status || "").toLowerCase();
    if (message.thinking || message.streaming || ACTIVE_RUN_STATUSES.has(status)) {
      assistantIndex = index;
      break;
    }
  }
  if (assistantIndex < 0) return null;
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = safeMessages[index];
    if (message?.role !== "user") continue;
    const text = compactTaskAnchorText(message.rawContent);
    return text ? { messageId: String(message.id || ""), text } : null;
  }
  return null;
}
const MEMORY_ACTIVITY_MAX_POLLS = 240;

function memoryOperations(activity) {
  return Array.isArray(activity?.operations)
    ? activity.operations
    : [];
}

function memoryWriteOperation(activity) {
  return memoryOperations(activity).find(
    (operation) => operation.kind === "write",
  ) || null;
}

function memoryStatusText(
  activity,
  { syncFailures = 0, pollingExpired = false } = {},
) {
  const summary = activity?.summary || {};
  const recalled = Number(summary.recalled || 0);
  const added = Number(summary.added || 0);
  const updated = Number(summary.updated || 0);
  const deleted = Number(summary.deleted || 0);
  const changed = added + updated + deleted;
  const write = memoryWriteOperation(activity);
  const prefix = recalled ? `参考了${recalled}条记忆` : "";
  if (write?.status === "queued" || write?.status === "running") {
    if (pollingExpired) {
      return [prefix, "后台仍在整理，可刷新查看状态"]
        .filter(Boolean)
        .join(" · ");
    }
    if (syncFailures >= 3) {
      return [prefix, "后台仍在整理，状态同步较慢…"]
        .filter(Boolean)
        .join(" · ");
    }
    return [prefix, "正在整理记忆…"].filter(Boolean).join(" · ");
  }
  if (write?.status === "failed") return "记忆写入失败";
  if (changed) {
    const changes = [
      added ? `新增${added}条` : "",
      updated ? `更新${updated}条` : "",
      deleted ? `删除${deleted}条` : "",
    ].filter(Boolean).join("，");
    return [prefix, changes].filter(Boolean).join(" · ");
  }
  return prefix;
}

function MemoryActivityStatus({ initialActivity, messageId }) {
  const initialWriteId = memoryWriteOperation(initialActivity)?.id || "";
  const [activity, setActivity] = useState(initialActivity || null);
  const [retrying, setRetrying] = useState(false);
  const [syncFailures, setSyncFailures] = useState(0);
  const [pollTick, setPollTick] = useState(0);
  const pollCountRef = useRef(0);
  const write = memoryWriteOperation(activity);
  const pending = write?.status === "queued" || write?.status === "running";
  const pollingExpired = (
    pending
    && pollCountRef.current >= MEMORY_ACTIVITY_MAX_POLLS
  );
  const statusText = memoryStatusText(activity, {
    syncFailures,
    pollingExpired,
  });

  const publishActivity = (nextActivity) => {
    setActivity(nextActivity);
    publishMemoryActivity(messageId, nextActivity);
  };

  useEffect(() => {
    setActivity(initialActivity || null);
  }, [initialActivity]);

  useEffect(() => {
    pollCountRef.current = 0;
    setSyncFailures(0);
  }, [initialWriteId, messageId]);

  useEffect(() => {
    if (
      !pending
      || !activity?.messageId
      || pollCountRef.current >= MEMORY_ACTIVITY_MAX_POLLS
    ) {
      return undefined;
    }
    const timeout = window.setTimeout(async () => {
      pollCountRef.current += 1;
      try {
        const nextActivity = await memoryApi.activity(
          activity.messageId,
        );
        setSyncFailures(0);
        publishActivity(nextActivity);
      } catch {
        setSyncFailures((value) => value + 1);
      } finally {
        setPollTick((value) => value + 1);
      }
    }, 1200);
    return () => window.clearTimeout(timeout);
  }, [
    activity?.messageId,
    pending,
    pollTick,
    write?.attemptCount,
    write?.status,
  ]);

  if (!statusText) return null;

  const openDetails = () => {
    window.dispatchEvent(
      new CustomEvent("knowflow:react-agent-trace-open", {
        detail: {
          messageId,
          trace: memoryActivityTrace(activity),
          approvals: [],
          run: null,
        },
      }),
    );
    window.dispatchEvent(
      new CustomEvent("knowflow:react-drawer-open", {
        detail: { focus: true },
      }),
    );
  };
  const retry = async () => {
    if (!write?.id || retrying) return;
    setRetrying(true);
    try {
      const next = await memoryApi.retryOperation(write.id);
      pollCountRef.current = 0;
      setSyncFailures(0);
      publishActivity(next);
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div
      className={[
        "memory-activity-status",
        write?.status || "succeeded",
      ].join(" ")}
      aria-live={"polite"}
    >
      <button type={"button"} onClick={openDetails}>
        <span className={"memory-activity-signal"} aria-hidden={"true"}></span>
        <span>{statusText}</span>
        <span aria-hidden={"true"}>{"↗"}</span>
      </button>
      {write?.status === "failed" ? (
        <button
          className={"memory-activity-retry"}
          type={"button"}
          disabled={retrying}
          onClick={retry}
        >
          {retrying ? "重试中…" : "重试"}
        </button>
      ) : null}
    </div>
  );
}

const AgentTurnRunBlock = memo(function AgentTurnRunBlock({
  approvals,
  interactionPending,
  messageId,
  run,
  toolCalls,
  trace,
}) {
  return (
    <div className={"agent-turn-run-block"}>
      <AgentTraceStrip
        interactionPending={interactionPending}
        messageId={messageId}
        trace={trace}
        approvals={approvals}
        toolCalls={toolCalls}
        run={run}
      />
    </div>
  );
});

function MessageBubble({ interactionOwner, message, pendingInteractionCount = 0 }) {
  const pendingInteractions = pendingAgentInteractions(message);
  const activeInteraction = pendingInteractions[0] || null;
  const ownsInteraction = Boolean(
    activeInteraction && interactionOwner?.messageId === String(message.id),
  );
  const resolvedApprovals = (Array.isArray(message.approvals) ? message.approvals : [])
    .filter((approval) => approval?.status !== "waiting" || approval?.decision);
  const bubbleClassName = [
    "message",
    message.role,
    message.trace?.length ? "has-agent-trace" : "",
    message.thinking ? "thinking" : "",
    message.streaming ? "streaming" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const props = {
    className: bubbleClassName,
    "data-raw-content": message.rawContent,
    "data-react-message-id": message.id,
    "data-source-message-id": message.sourceMessageId || undefined,
    "aria-busy": message.thinking ? "true" : undefined,
  };

  if (message.role === "assistant") {
    return (
      <div {...props}>
        <AgentTurnRunBlock
          interactionPending={Boolean(interactionOwner)}
          messageId={message.id}
          trace={message.trace}
          approvals={message.approvals}
          toolCalls={message.toolCalls}
          run={message.run}
        />
        <div className={"agent-turn-answer"}>
          {message.run?.status === "waiting_start" ? (
          <AgentTaskPlan
            compact
            messageId={message.id}
            run={message.run}
            trace={message.trace}
          />
          ) : null}
          {resolvedApprovals.length ? (
          <div className={"agent-approval-list"}>
            {resolvedApprovals.map((approval) => (
              <AgentApprovalPrompt
                approval={approval}
                key={approval.approvalId}
              />
            ))}
          </div>
          ) : null}
          {activeInteraction ? (
            <div
              className="agent-interaction-owner"
              aria-current={ownsInteraction ? "true" : undefined}
              data-interaction-active={ownsInteraction ? "true" : "false"}
              data-interaction-kind={activeInteraction.kind}
            >
              {activeInteraction.kind === "approval" ? (
                <AgentApprovalPrompt
                  approval={activeInteraction.value}
                  autoFocus={ownsInteraction}
                  compact={!ownsInteraction}
                  interactive={ownsInteraction}
                  key={activeInteraction.value.approvalId}
                  queuedCount={ownsInteraction ? pendingInteractionCount - 1 : 0}
                />
              ) : (
                <AgentQuestionPrompt
                  autoFocus={ownsInteraction}
                  interactive={ownsInteraction}
                  question={activeInteraction.value}
                  key={activeInteraction.value.questionId}
                  queuedCount={ownsInteraction ? pendingInteractionCount - 1 : 0}
                />
              )}
            </div>
          ) : null}
          {message.thinking ? (
          <AgentThinkingOrb trace={message.trace} />
        ) : (
          <>
            <div
              className={"message-markdown"}
              dangerouslySetInnerHTML={{
                __html: renderMarkdown(redactEmailAddresses(message.rawContent)),
              }}
            />
            <AgentDeliveryCard
              messageId={message.id}
              run={message.run}
              trace={message.trace}
              approvals={message.approvals}
            />
            <AgentEvidenceStrip
              messageId={message.id}
              run={message.run}
              trace={message.trace}
              approvals={message.approvals}
            />
            <MemoryActivityStatus
              initialActivity={message.memoryActivity}
              messageId={message.id}
            />
          </>
          )}
        </div>
      </div>
    );
  }

  return <div {...props}>{message.rawContent}</div>;
}

function normalizeRawContent(value) {
  return String(value ?? "");
}

const TRANSCRIPT_SEARCH_LIMIT = 1000;

export function transcriptSearchMatches(messages, query) {
  const needle = String(query || "").trim().toLocaleLowerCase();
  if (!needle) return [];
  const matches = [];
  for (const message of Array.isArray(messages) ? messages : []) {
    if (message?.thinking) continue;
    const content = normalizeRawContent(message?.rawContent).toLocaleLowerCase();
    if (!content) continue;
    let offset = 0;
    while (offset <= content.length - needle.length && matches.length < TRANSCRIPT_SEARCH_LIMIT) {
      const index = content.indexOf(needle, offset);
      if (index < 0) break;
      matches.push({ messageId: String(message.id), offset: index });
      offset = index + Math.max(1, needle.length);
    }
    if (matches.length >= TRANSCRIPT_SEARCH_LIMIT) break;
  }
  return matches;
}

function MessageRow({
  interactionOwner,
  message,
  pendingInteractionCount,
  searchCurrent = false,
  searchMatch = false,
}) {
  const rowClassName = [
    "message-row",
    message.role,
    message.thinking ? "thinking-row" : "",
    searchMatch ? "transcript-search-match" : "",
    searchCurrent ? "transcript-search-current" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rowClassName}>
      <MessageBubble
        interactionOwner={interactionOwner}
        message={message}
        pendingInteractionCount={pendingInteractionCount}
      />
      {message.role === "user" ? (
        <div className={"message-actions"} role={"group"} aria-label={"消息操作"}>
          {message.sourceMessageId ? (
            <button
              type={"button"}
              data-message-action={"rewind"}
              aria-label={"从此处继续"}
              title={"从此处继续（原会话和文件不变）"}
            >
              <svg viewBox={"0 0 24 24"} width={"18"} height={"18"} aria-hidden={"true"}>
                <path d={"M9 14 4 9l5-5"}></path>
                <path d={"M4 9h9a7 7 0 0 1 7 7v4"}></path>
              </svg>
            </button>
          ) : null}
          <button
            type={"button"}
            data-message-action={"edit"}
            aria-label={"编辑并重新发送"}
            title={"编辑并重新发送"}
          >
            <svg viewBox={"0 0 24 24"} width={"18"} height={"18"} aria-hidden={"true"}>
              <path d={"M12 20h9"}></path>
              <path d={"M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"}></path>
            </svg>
          </button>
        </div>
      ) : null}
      {message.role === "assistant" && !message.thinking && !message.streaming ? (
        <div className={"message-actions"} role={"group"} aria-label={"消息操作"}>
          <button type={"button"} data-message-action={"copy"} aria-label={"复制答案"} title={"复制答案"}>
            <svg viewBox={"0 0 24 24"} width={"18"} height={"18"} aria-hidden={"true"}>
              <rect x={"9"} y={"9"} width={"11"} height={"11"} rx={"2"}></rect>
              <path d={"M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3"}></path>
            </svg>
          </button>
          {message.retryable ? (
            <button
              type={"button"}
              className={"retry-answer-button"}
              data-message-action={"retry"}
              aria-label={"重新生成"}
              title={"重新生成"}
            >
              <svg viewBox={"0 0 24 24"} width={"18"} height={"18"} aria-hidden={"true"}>
                <path d={"M20 11a8 8 0 1 0-2.34 5.66"}></path>
                <path d={"M20 4v7h-7"}></path>
              </svg>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ChatMessages() {
  const messagesRef = useRef(null);
  const searchInputRef = useRef(null);
  const nextMessageIdRef = useRef(1);
  const followOutputRef = useRef(true);
  const scrollFrameRef = useRef(0);
  const [messages, setMessages] = useState([]);
  const [showWelcome, setShowWelcome] = useState(true);
  const [sessionSwitch, setSessionSwitch] = useState(null);
  const [followingOutput, setFollowingOutput] = useState(true);
  const [hasNewOutput, setHasNewOutput] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchCursor, setSearchCursor] = useState(0);
  const searchMatches = useMemo(
    () => transcriptSearchMatches(messages, searchQuery),
    [messages, searchQuery],
  );
  const currentSearchMatch = searchMatches[searchCursor] || null;
  const searchMessageIds = useMemo(
    () => new Set(searchMatches.map((match) => match.messageId)),
    [searchMatches],
  );
  const interactionOwner = useMemo(
    () => activeAgentInteractionOwner(messages),
    [messages],
  );
  const currentTask = useMemo(
    () => activeTaskAnchor(messages),
    [messages],
  );
  const pendingInteractionCount = interactionOwner
    ? interactionOwner.queuedCount + 1
    : 0;
  const findBubble = (messageId) =>
    messagesRef.current?.querySelector('[data-react-message-id="' + messageId + '"]') || null;
  const revealCurrentTask = () => {
    const row = findBubble(currentTask?.messageId)?.closest(".message-row");
    if (!row) return;
    setFollowOutput(false);
    row.scrollIntoView({
      block: "start",
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  };
  const setFollowOutput = (nextValue) => {
    const next = Boolean(nextValue);
    followOutputRef.current = next;
    setFollowingOutput((current) => current === next ? current : next);
    if (next) setHasNewOutput(false);
  };
  const scrollToBottom = ({ force = false, behavior = "auto" } = {}) => {
    const node = messagesRef.current;
    if (!node) return;
    if (!shouldFollowChatUpdate({ pinned: followOutputRef.current, force })) {
      setHasNewOutput(true);
      return;
    }
    window.cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      const viewport = messagesRef.current;
      if (!viewport) return;
      setFollowOutput(true);
      if (typeof viewport.scrollTo === "function") {
        viewport.scrollTo({ top: viewport.scrollHeight, behavior });
      } else {
        viewport.scrollTop = viewport.scrollHeight;
      }
    });
  };
  const handleMessagesScroll = () => {
    const pinned = isChatViewportPinned(messagesRef.current);
    if (pinned !== followOutputRef.current) setFollowOutput(pinned);
  };
  const jumpToLatest = () => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setFollowOutput(true);
    scrollToBottom({ force: true, behavior: reduceMotion ? "auto" : "smooth" });
  };
  const closeSearch = () => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchCursor(0);
  };
  const openSearch = (query = "") => {
    setSearchOpen(true);
    setSearchQuery(String(query || ""));
    setSearchCursor(0);
    window.requestAnimationFrame(() => searchInputRef.current?.focus());
  };
  const moveSearch = (delta) => {
    if (!searchMatches.length) return;
    setSearchCursor((current) => (
      (current + delta + searchMatches.length) % searchMatches.length
    ));
  };

  useEffect(() => {
    setSearchCursor((current) => Math.max(0, Math.min(current, searchMatches.length - 1)));
  }, [searchMatches.length]);

  useEffect(() => {
    if (!searchOpen || !currentSearchMatch) return;
    const bubble = findBubble(currentSearchMatch.messageId);
    const row = bubble?.closest(".message-row");
    if (!row) return;
    setFollowOutput(false);
    row.scrollIntoView({
      block: "center",
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
    });
  }, [currentSearchMatch?.messageId, currentSearchMatch?.offset, searchOpen]);

  useEffect(() => {
    const handleSearchOpen = (event) => openSearch(event.detail?.query || "");
    const handleFindShortcut = (event) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLocaleLowerCase() !== "f") return;
      if (!document.querySelector("#page-chat.active")) return;
      event.preventDefault();
      openSearch(searchOpen ? searchQuery : "");
    };
    window.addEventListener("knowflow:react-transcript-search-open", handleSearchOpen);
    window.addEventListener("keydown", handleFindShortcut);
    return () => {
      window.removeEventListener("knowflow:react-transcript-search-open", handleSearchOpen);
      window.removeEventListener("keydown", handleFindShortcut);
    };
  }, [searchOpen, searchQuery]);
  const normalizeMessage = (payload, id) => {
    const rawContent = normalizeRawContent(payload.rawContent ?? payload.content);
    return {
      id,
      role: payload.role === "user" ? "user" : "assistant",
      rawContent: payload.thinking ? "" : rawContent,
      thinking: Boolean(payload.thinking),
      streaming: Boolean(payload.streaming),
      retryable: Boolean(payload.retryable),
      trace: Array.isArray(payload.trace)
        ? payload.trace
        : [],
      approvals: Array.isArray(payload.approvals)
        ? payload.approvals
        : [],
      questions: Array.isArray(payload.questions) ? payload.questions : [],
      toolCalls: Array.isArray(payload.toolCalls) ? payload.toolCalls : [],
      run: payload.run || null,
      memoryActivity: payload.memoryActivity || null,
      sourceMessageId: payload.sourceMessageId ?? null,
    };
  };
  const updateMessage = (messageId, updater) => {
    let didUpdate = false;
    flushSync(() => {
      setMessages((currentMessages) =>
        currentMessages.map((message) => {
          if (message.id !== messageId) return message;
          didUpdate = true;
          return updater(message);
        }),
      );
    });
    scrollToBottom();
    return { messageId, bubble: findBubble(messageId), handled: didUpdate };
  };
  const resetMessages = ({ showWelcome: nextShowWelcome = false } = {}) => {
    flushSync(() => {
      setMessages([]);
      setShowWelcome(Boolean(nextShowWelcome));
    });
    scrollToBottom({ force: true });
    return messagesRef.current;
  };
  const appendMessage = (payload) => {
    const messageId = "react-message-" + nextMessageIdRef.current;
    nextMessageIdRef.current += 1;
    const message = normalizeMessage(payload || {}, messageId);
    flushSync(() => {
      setShowWelcome(false);
      setMessages((currentMessages) => [...currentMessages, message]);
    });
    scrollToBottom({ force: payload?.role === "user" });
    return { messageId, bubble: findBubble(messageId) };
  };

  useEffect(() => {
    document.querySelector("#page-chat")?.classList.toggle("chat-empty", showWelcome);
    return () => document.querySelector("#page-chat")?.classList.remove("chat-empty");
  }, [showWelcome]);

  useEffect(() => () => {
    window.cancelAnimationFrame(scrollFrameRef.current);
  }, []);

  useEffect(() => {
    const messagesNode = messagesRef.current;
    if (!messagesNode) return undefined;
    const handleMessageActionClick = (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const button = target?.closest("[data-message-action]");
      if (!button || !messagesNode.contains(button)) return;
      const eventName = actionEvents[button.dataset.messageAction];
      if (!eventName) return;
      const bubble = button.closest(".message-row")?.querySelector(".message") || null;
      event.preventDefault();
      window.dispatchEvent(
        new CustomEvent(eventName, {
          detail: {
            bubble,
            messageId: bubble?.dataset.reactMessageId || "",
            sourceMessageId: bubble?.dataset.sourceMessageId || "",
            rawContent: bubble?.dataset.rawContent || "",
          },
        }),
      );
    };
    const handleMessageCommand = (event) => {
      const detail = event.detail || {};
      const action = String(detail.action || "");
      if (!["copy", "edit", "rewind"].includes(action)) return;
      const buttons = Array.from(
        messagesNode.querySelectorAll(`[data-message-action="${action}"]`),
      ).filter((button) => !button.disabled);
      const button = buttons[buttons.length - 1];
      detail.handled = Boolean(button);
      if (button) button.click();
    };
    messagesNode.addEventListener("click", handleMessageActionClick);
    window.addEventListener("knowflow:react-message-command", handleMessageCommand);
    return () => {
      messagesNode.removeEventListener("click", handleMessageActionClick);
      window.removeEventListener("knowflow:react-message-command", handleMessageCommand);
    };
  }, []);

  useEffect(() => {
    const handleAppend = (event) => {
      const detail = event.detail || {};
      const result = appendMessage(detail);
      detail.messageId = result.messageId;
      detail.bubble = result.bubble;
      detail.handled = Boolean(result.messageId);
    };
    const handleReset = (event) => {
      const detail = event.detail || {};
      setSearchOpen(false);
      setSearchQuery("");
      setSearchCursor(0);
      detail.node = resetMessages({ showWelcome: detail.showWelcome });
      detail.handled = true;
    };
    const handleContent = (event) => {
      const detail = event.detail || {};
      const messageId = detail.messageId || detail.bubble?.dataset?.reactMessageId;
      if (!messageId) return;

      const rawContent = normalizeRawContent(detail.rawContent ?? detail.content);
      const result = updateMessage(messageId, (message) => ({
        ...message,
        rawContent,
        thinking: false,
        streaming: Boolean(detail.streaming),
      }));
      detail.messageId = result.messageId;
      detail.bubble = result.bubble;
      detail.handled = result.handled;
    };
    const handleThinking = (event) => {
      const detail = event.detail || {};
      const messageId = detail.messageId || detail.bubble?.dataset?.reactMessageId;
      if (!messageId) return;

      const thinking = Boolean(detail.enabled);
      const result = updateMessage(messageId, (message) => ({
        ...message,
        rawContent: thinking ? "" : message.rawContent,
        thinking,
        streaming: Boolean(detail.streaming),
      }));
      detail.messageId = result.messageId;
      detail.bubble = result.bubble;
      detail.handled = result.handled;
    };
    const handleTrace = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          trace: Array.isArray(detail.trace)
            ? detail.trace
            : [],
        }),
      );
      detail.handled = result.handled;
    };
    const handleApprovals = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          approvals: Array.isArray(detail.approvals)
            ? detail.approvals
            : [],
        }),
      );
      detail.handled = result.handled;
    };
    const handleQuestions = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          questions: Array.isArray(detail.questions) ? detail.questions : [],
        }),
      );
      detail.handled = result.handled;
    };
    const handleRun = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          run: detail.run || null,
        }),
      );
      detail.handled = result.handled;
    };
    const handleArtifacts = (event) => {
      const detail = event.detail || {};
      const nextArtifacts = Array.isArray(detail.artifacts) ? detail.artifacts : [];
      if (detail.messageId) {
        const result = updateMessage(detail.messageId, (message) => ({
          ...message,
          run: message.run ? { ...message.run, artifacts: nextArtifacts } : message.run,
        }));
        detail.handled = result.handled;
        return;
      }
      if (!detail.runId) return;
      let didUpdate = false;
      flushSync(() => {
        setMessages((currentMessages) => currentMessages.map((message) => {
          const runId = String(message.run?.id || message.run?.runId || "");
          if (runId !== String(detail.runId)) return message;
          didUpdate = true;
          return { ...message, run: { ...message.run, artifacts: nextArtifacts } };
        }));
      });
      detail.handled = didUpdate;
    };
    const handleToolCalls = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          toolCalls: Array.isArray(detail.toolCalls)
            ? detail.toolCalls
            : [],
        }),
      );
      detail.handled = result.handled;
    };
    const handleMemoryActivity = (event) => {
      const detail = event.detail || {};
      if (!detail.messageId) return;
      const result = updateMessage(
        detail.messageId,
        (message) => ({
          ...message,
          memoryActivity: detail.memoryActivity || null,
          trace: mergeMemoryActivityTrace(
            message.trace,
            detail.memoryActivity,
          ),
        }),
      );
      detail.handled = result.handled;
    };

    window.addEventListener("knowflow:react-message-append", handleAppend);
    window.addEventListener("knowflow:react-messages-reset", handleReset);
    window.addEventListener("knowflow:react-message-content", handleContent);
    window.addEventListener("knowflow:react-message-thinking", handleThinking);
    window.addEventListener("knowflow:react-message-trace", handleTrace);
    window.addEventListener("knowflow:react-message-approvals", handleApprovals);
    window.addEventListener("knowflow:react-message-questions", handleQuestions);
    window.addEventListener("knowflow:react-message-run", handleRun);
    window.addEventListener("knowflow:react-agent-artifacts-updated", handleArtifacts);
    window.addEventListener("knowflow:react-message-tool-calls", handleToolCalls);
    window.addEventListener(
      "knowflow:react-message-memory-activity",
      handleMemoryActivity,
    );
    return () => {
      window.removeEventListener("knowflow:react-message-append", handleAppend);
      window.removeEventListener("knowflow:react-messages-reset", handleReset);
      window.removeEventListener("knowflow:react-message-content", handleContent);
      window.removeEventListener("knowflow:react-message-thinking", handleThinking);
      window.removeEventListener("knowflow:react-message-trace", handleTrace);
      window.removeEventListener("knowflow:react-message-approvals", handleApprovals);
      window.removeEventListener("knowflow:react-message-questions", handleQuestions);
      window.removeEventListener("knowflow:react-message-run", handleRun);
      window.removeEventListener("knowflow:react-agent-artifacts-updated", handleArtifacts);
      window.removeEventListener("knowflow:react-message-tool-calls", handleToolCalls);
      window.removeEventListener(
        "knowflow:react-message-memory-activity",
        handleMemoryActivity,
      );
    };
  }, []);

  useEffect(() => {
    const handleSessionSwitchState = (event) => {
      const detail = event.detail || {};
      if (detail.status === "success") {
        setSessionSwitch(null);
        return;
      }
      setSessionSwitch({
        status: detail.status === "error" ? "error" : "loading",
        sessionId: detail.sessionId || "",
        title: detail.title || "任务",
        chatModelConfigId: detail.chatModelConfigId ?? null,
      });
    };
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
    return () => window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitchState);
  }, []);

  const retrySessionSwitch = () => {
    if (!sessionSwitch?.sessionId) return;
    window.dispatchEvent(new CustomEvent("knowflow:react-session-continue", {
      detail: sessionSwitch,
    }));
  };

  return (
    <>
      {searchOpen ? (
        <div className={"transcript-search-bar"} role={"search"} aria-label={"搜索当前对话"}>
          <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
            <circle cx={"8.5"} cy={"8.5"} r={"5.5"}></circle>
            <path d={"m13 13 4 4"}></path>
          </svg>
          <input
            ref={searchInputRef}
            type={"search"}
            value={searchQuery}
            aria-label={"搜索词"}
            placeholder={"搜索当前对话"}
            onChange={(event) => {
              setSearchQuery(event.target.value);
              setSearchCursor(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") closeSearch();
              else if (event.key === "Enter") {
                event.preventDefault();
                moveSearch(event.shiftKey ? -1 : 1);
              }
            }}
          />
          <span className={"transcript-search-count"} aria-live={"polite"}>
            {searchQuery.trim()
              ? (searchMatches.length ? `${searchCursor + 1}/${searchMatches.length}` : "无结果")
              : ""}
          </span>
          <button type={"button"} aria-label={"上一个匹配"} disabled={!searchMatches.length} onClick={() => moveSearch(-1)}>↑</button>
          <button type={"button"} aria-label={"下一个匹配"} disabled={!searchMatches.length} onClick={() => moveSearch(1)}>↓</button>
          <button type={"button"} aria-label={"关闭搜索"} onClick={closeSearch}>×</button>
        </div>
      ) : null}
      <div
        className={`messages${sessionSwitch?.status === "loading" ? " session-switching" : ""}`}
        id={"chat-messages"}
        ref={messagesRef}
        aria-busy={sessionSwitch?.status === "loading"}
        onScroll={handleMessagesScroll}
      >
        {currentTask ? (
          <button
            className={"active-task-anchor"}
            type={"button"}
            onClick={revealCurrentTask}
            aria-label={`回到当前任务：${currentTask.text}`}
            title={currentTask.text}
          >
            <strong>{"当前任务"}</strong>
            <span>{currentTask.text}</span>
            <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
              <path d={"M7 4h9v9"}></path>
              <path d={"M16 4 5 15"}></path>
            </svg>
          </button>
        ) : null}
        {sessionSwitch ? (
          <div
            className={`session-switch-state ${sessionSwitch.status}`}
            role={sessionSwitch.status === "error" ? "alert" : "status"}
          >
            {sessionSwitch.status === "loading" ? (
              <AgentThinkingOrb
                state={"connecting"}
                label={`正在打开「${sessionSwitch.title}」`}
              />
            ) : (
              <>
                <span>{`无法打开「${sessionSwitch.title}」`}</span>
                <button type={"button"} onClick={retrySessionSwitch}>{"重试"}</button>
              </>
            )}
          </div>
        ) : null}
        {showWelcome ? (
          <div className={"welcome-card"}>
            <h2>{"有什么可以帮你？"}</h2>
          </div>
        ) : null}
        {messages.map((message) => (
          <MessageRow
            interactionOwner={interactionOwner}
            key={message.id}
            message={message}
            pendingInteractionCount={pendingInteractionCount}
            searchMatch={searchMessageIds.has(String(message.id))}
            searchCurrent={currentSearchMatch?.messageId === String(message.id)}
          />
        ))}
      </div>
      {!showWelcome && !followingOutput ? (
        <button
          className={`chat-jump-to-latest${hasNewOutput ? " has-new-output" : ""}`}
          type={"button"}
          aria-label={hasNewOutput ? "查看最新Agent输出" : "回到对话底部"}
          aria-live={"polite"}
          onClick={jumpToLatest}
        >
          <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M5 8l5 5 5-5"} fill={"none"} stroke={"currentColor"} strokeWidth={"1.8"} strokeLinecap={"round"} strokeLinejoin={"round"} />
          </svg>
          <span>{hasNewOutput ? "查看最新输出" : "回到最新"}</span>
          {hasNewOutput ? <i aria-hidden={"true"}></i> : null}
        </button>
      ) : null}
    </>
  );
}
