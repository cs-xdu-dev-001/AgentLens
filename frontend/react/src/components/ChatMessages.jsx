import { Virtuoso } from "react-virtuoso";
import { ChevronRight, CircleCheck, FolderTree, GitCompareArrows, History } from "lucide-react";
import { forwardRef, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { memoryApi } from "../api/client.js";
import { redactEmailAddresses, renderMarkdown } from "../controller/markdown.js";
import { applyTranscriptSearchHighlights } from "../controller/chatSearch.js";
import { copyTextToClipboard } from "../controller/clipboard.js";
import { redactCopyText } from "../controller/copyPresentation.js";
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
  buildAgentRunPresentation,
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

const MessageScroller = forwardRef(function MessageScroller(
  { children, style, ...props },
  ref,
) {
  return (
    <div ref={ref} {...props} style={style}>
      {children}
    </div>
  );
});

const MessageListFooter = memo(function MessageListFooter() {
  return <div className={"message-list-footer"} aria-hidden={"true"}></div>;
});

function SessionSwitchState({ sessionSwitch, onRetry }) {
  if (!sessionSwitch) return null;
  return (
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
          <button type={"button"} onClick={onRetry}>{"重试"}</button>
        </>
      )}
    </div>
  );
}

const MessageListHeader = memo(function MessageListHeader({ context }) {
  const currentTask = context?.currentTask || null;
  const sessionSwitch = context?.sessionSwitch || null;
  const retrySessionSwitch = context?.retrySessionSwitch || (() => {});
  return (
    <div className={"message-list-header"}>
      {currentTask ? (
        <button
          className={"active-task-anchor"}
          type={"button"}
          onClick={context?.revealCurrentTask}
          aria-label={`回到当前任务：${currentTask.text}；${currentTask.presentation?.status?.label || "执行中"}`}
          title={currentTask.text}
          style={{
            "--task-progress-scale": Math.max(
              0,
              Math.min(100, Number(currentTask.presentation?.progressPercent) || 0),
            ) / 100,
          }}
        >
          <strong>{"任务"}</strong>
          <span className={"active-task-anchor-copy"}>{currentTask.text}</span>
          {currentTask.presentation?.metrics ? (
            <span className={"active-task-anchor-metrics"}>{currentTask.presentation.metrics}</span>
          ) : null}
          <span className={`active-task-anchor-state ${currentTask.presentation?.status?.className || "running"}`}>
            {currentTask.presentation?.status?.label || "执行中"}
          </span>
          <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M7 4h9v9"}></path>
            <path d={"M16 4 5 15"}></path>
          </svg>
        </button>
      ) : null}
      <SessionSwitchState sessionSwitch={sessionSwitch} onRetry={retrySessionSwitch} />
    </div>
  );
});

const MESSAGE_VIRTUOSO_COMPONENTS = Object.freeze({
  Footer: MessageListFooter,
  Header: MessageListHeader,
  Scroller: MessageScroller,
});

function messageItemContent(_index, message, context) {
  return (
    <MessageRow
      interactionOwner={context?.interactionOwner || null}
      key={message.id}
      message={message}
      pendingInteractionCount={context?.pendingInteractionCount || 0}
      searchMatch={context?.searchMessageIds?.has(String(message.id)) || false}
      searchCurrent={context?.currentSearchMessageId === String(message.id)}
    />
  );
}

function messageItemKey(_index, message) {
  return message.id;
}

let codeHighlighterPromise = null;

function loadCodeHighlighter() {
  if (!codeHighlighterPromise) {
    codeHighlighterPromise = import("../controller/codeHighlighting.js").catch((error) => {
      codeHighlighterPromise = null;
      throw error;
    });
  }
  return codeHighlighterPromise;
}

function compactTaskAnchorText(value, maxLength = 180) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

export function activeTaskAnchor(messages = [], now = Date.now()) {
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
  const assistantMessage = safeMessages[assistantIndex];
  const presentation = buildAgentRunPresentation({
    run: assistantMessage?.run || null,
    trace: assistantMessage?.trace || [],
    now,
  });
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = safeMessages[index];
    if (message?.role !== "user") continue;
    const text = compactTaskAnchorText(message.rawContent);
    return text ? {
      assistantMessageId: String(assistantMessage?.id || ""),
      messageId: String(message.id || ""),
      presentation,
      text,
    } : null;
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

const MessageMarkdown = memo(function MessageMarkdown({ rawContent, streaming }) {
  const rootRef = useRef(null);
  const html = useMemo(
    () => renderMarkdown(redactEmailAddresses(rawContent)),
    [rawContent],
  );

  useEffect(() => {
    const root = rootRef.current;
    if (streaming || !root?.querySelector("[data-message-code-block]")) {
      return undefined;
    }
    let active = true;
    loadCodeHighlighter()
      .then(({ highlightMessageCodeBlocks }) => {
        if (active && root.isConnected) highlightMessageCodeBlocks(root);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [html, streaming]);

  return (
    <div
      ref={rootRef}
      className={"message-markdown"}
      dangerouslySetInnerHTML={{ __html: html }}
    />
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
            <MessageMarkdown
              rawContent={message.rawContent}
              streaming={message.streaming}
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

const MessageRow = memo(function MessageRow({
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
}, (previous, next) => previous.message === next.message
  && previous.pendingInteractionCount === next.pendingInteractionCount
  && previous.searchCurrent === next.searchCurrent
  && previous.searchMatch === next.searchMatch
  && sameInteractionOwner(previous.interactionOwner, next.interactionOwner));

function sameInteractionOwner(previous, next) {
  return (previous?.messageId || "") === (next?.messageId || "")
    && (previous?.kind || "") === (next?.kind || "")
    && (previous?.queuedCount || 0) === (next?.queuedCount || 0);
}

const WELCOME_ACTIONS = [
  {
    id: "understand",
    icon: FolderTree,
    label: "梳理项目结构",
    prompt: "请梳理当前工作区的项目结构、技术栈、关键入口和运行方式，并告诉我最值得先关注的部分。",
  },
  {
    id: "review",
    icon: GitCompareArrows,
    label: "检查当前改动",
    prompt: "请检查当前工作区的未提交改动，指出可能的缺陷、风险和遗漏；发现明确问题时直接修复，并运行相关验证。",
  },
  {
    id: "test",
    icon: CircleCheck,
    label: "运行测试并修复",
    prompt: "请运行与当前项目相关的测试，定位失败原因并修复问题，完成后汇报验证结果。",
  },
  {
    id: "continue",
    icon: History,
    label: "继续最近的工作",
    prompt: "请结合当前工作区状态和最近的Git提交判断上次工作进展，并从最合理的下一步继续。",
  },
];

function WelcomeSurface({ onSeed, workspaceState }) {
  const workspaceMode = workspaceState?.loading
    ? "loading"
    : workspaceState?.error
      ? "error"
      : workspaceState?.status?.enabled
        ? "ready"
        : "disabled";
  const workspaceCopy = workspaceMode === "error"
    ? "工作区状态异常"
    : workspaceMode === "disabled"
      ? "工作区未启用"
      : workspaceMode === "loading"
        ? "正在连接工作区"
        : "打开当前工作区";
  const openWorkspace = () => window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
    detail: { page: "workspace" },
  }));
  return (
    <div className={"welcome-card"} data-welcome-surface={"true"}>
      <div className={"welcome-heading"}>
        <h2>{"有什么可以帮你？"}</h2>
        <button
          className={["welcome-context", workspaceMode].join(" ")}
          data-workspace-state={workspaceMode}
          type={"button"}
          disabled={workspaceMode === "loading"}
          aria-busy={workspaceMode === "loading"}
          aria-live={"polite"}
          onClick={openWorkspace}
        >
          <span className={"welcome-context-dot"} aria-hidden={"true"}></span>
          <span>{workspaceCopy}</span>
          {workspaceMode !== "loading" ? <ChevronRight size={16} aria-hidden={"true"} /> : null}
        </button>
      </div>
      <nav className={"welcome-actions"} aria-label={"常用起始任务"}>
        {WELCOME_ACTIONS.map((action) => {
          const Icon = action.icon;
          return (
            <button
              className={"welcome-action"}
              data-welcome-action={action.id}
              key={action.id}
              type={"button"}
              onClick={() => onSeed(action.prompt)}
            >
              <span className={"welcome-action-icon"}>
                <Icon size={18} strokeWidth={1.7} aria-hidden={"true"} />
              </span>
              <span className={"welcome-action-label"}>{action.label}</span>
              <ChevronRight className={"welcome-action-arrow"} size={16} aria-hidden={"true"} />
            </button>
          );
        })}
      </nav>
      <div className={"welcome-shortcuts"} aria-hidden={"true"}>
        <span><kbd>/</kbd>{"命令"}</span>
        <span><kbd>@</kbd>{"文件"}</span>
        <span><kbd>Enter</kbd>{"发送"}</span>
      </div>
    </div>
  );
}

export function ChatMessages({ workspaceState = { loading: true }, onEmptyStateChange }) {
  const messagesRef = useRef(null);
  const virtuosoRef = useRef(null);
  const messageStateRef = useRef([]);
  const messageIndexRef = useRef(new Map());
  const searchInputRef = useRef(null);
  const searchHighlightFrameRef = useRef(0);
  const searchHighlightCleanupRef = useRef(null);
  const nextMessageIdRef = useRef(1);
  const followOutputRef = useRef(true);
  const scrollFrameRef = useRef(0);
  const messageRenderFrameRef = useRef(0);
  const messageRenderPendingRef = useRef(false);
  const pendingMessageScrollRef = useRef({ force: false, behavior: "auto" });
  const mountedRef = useRef(true);
  const [messages, setMessages] = useState([]);
  const [showWelcome, setShowWelcome] = useState(true);
  const [sessionSwitch, setSessionSwitch] = useState(null);
  const [followingOutput, setFollowingOutput] = useState(true);
  const [hasNewOutput, setHasNewOutput] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchCursor, setSearchCursor] = useState(0);
  const [taskClock, setTaskClock] = useState(() => Date.now());
  // Keep the logical message list ahead of React's paint while token updates are
  // coalesced. Unrelated renders must not overwrite a queued stream snapshot.
  if (!messageRenderPendingRef.current) messageStateRef.current = messages;
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
    () => activeTaskAnchor(messages, taskClock),
    [messages, taskClock],
  );
  const currentTaskId = currentTask?.assistantMessageId || "";
  useEffect(() => {
    if (!currentTaskId) return undefined;
    setTaskClock(Date.now());
    const timer = window.setInterval(() => setTaskClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [currentTaskId]);
  const pendingInteractionCount = interactionOwner
    ? interactionOwner.queuedCount + 1
    : 0;
  const setMessagesScroller = useCallback((node) => {
    messagesRef.current = node && typeof node.querySelector === "function" ? node : null;
  }, []);
  const findBubble = (messageId) =>
    messagesRef.current?.querySelector('[data-react-message-id="' + messageId + '"]') || null;
  const revealCurrentTask = () => {
    const taskIndex = messageStateRef.current.findIndex(
      (message) => String(message.id) === String(currentTask?.messageId || ""),
    );
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (taskIndex >= 0 && virtuosoRef.current?.scrollToIndex) {
      setFollowOutput(false);
      virtuosoRef.current.scrollToIndex({
        index: taskIndex,
        align: "start",
        behavior: reduceMotion ? "auto" : "smooth",
      });
      return;
    }
    const row = findBubble(currentTask?.messageId)?.closest(".message-row");
    if (!row) return;
    setFollowOutput(false);
    row.scrollIntoView({
      block: "start",
      behavior: reduceMotion ? "auto" : "smooth",
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
      if (messageStateRef.current.length && virtuosoRef.current?.scrollToIndex) {
        virtuosoRef.current.scrollToIndex({
          index: "LAST",
          align: "end",
          behavior,
        });
      } else if (typeof viewport.scrollTo === "function") {
        viewport.scrollTo({ top: viewport.scrollHeight, behavior });
      } else {
        viewport.scrollTop = viewport.scrollHeight;
      }
    });
  };

  const cancelMessageRender = () => {
    if (messageRenderFrameRef.current) {
      window.cancelAnimationFrame(messageRenderFrameRef.current);
      messageRenderFrameRef.current = 0;
    }
    messageRenderPendingRef.current = false;
    pendingMessageScrollRef.current = { force: false, behavior: "auto" };
  };

  const commitMessageState = (
    nextMessages,
    { defer = false, forceScroll = false, behavior = "auto" } = {},
  ) => {
    messageStateRef.current = nextMessages;
    if (!defer) {
      cancelMessageRender();
      flushSync(() => setMessages(nextMessages));
      scrollToBottom({ force: forceScroll, behavior });
      return;
    }

    messageRenderPendingRef.current = true;
    pendingMessageScrollRef.current = {
      force: pendingMessageScrollRef.current.force || Boolean(forceScroll),
      behavior: behavior || "auto",
    };
    if (messageRenderFrameRef.current) return;
    messageRenderFrameRef.current = window.requestAnimationFrame(() => {
      messageRenderFrameRef.current = 0;
      if (!mountedRef.current || !messageRenderPendingRef.current) return;
      messageRenderPendingRef.current = false;
      const scrollOptions = pendingMessageScrollRef.current;
      pendingMessageScrollRef.current = { force: false, behavior: "auto" };
      flushSync(() => setMessages(messageStateRef.current));
      scrollToBottom(scrollOptions);
    });
  };
  const handleMessagesScroll = () => {
    const pinned = isChatViewportPinned(messagesRef.current);
    if (pinned !== followOutputRef.current) setFollowOutput(pinned);
  };
  const handleVirtuosoAtBottom = (atBottom) => {
    if (Boolean(atBottom) !== followOutputRef.current) setFollowOutput(atBottom);
  };
  const followVirtuosoOutput = useCallback((atBottom) => {
    if (!followOutputRef.current || !atBottom) return false;
    return "auto";
  }, []);
  const jumpToLatest = () => {
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    setFollowOutput(true);
    scrollToBottom({ force: true, behavior: reduceMotion ? "auto" : "smooth" });
  };
  const closeSearch = () => {
    setSearchOpen(false);
    setSearchQuery("");
    setSearchCursor(0);
    window.requestAnimationFrame(() => document.querySelector('textarea[name="question"]')?.focus());
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
    if (!searchOpen || !searchQuery.trim()) {
      searchHighlightCleanupRef.current?.();
      searchHighlightCleanupRef.current = null;
      return undefined;
    }
    setFollowOutput(false);
    const targetIndex = currentSearchMatch
      ? messages.findIndex((message) => String(message.id) === String(currentSearchMatch.messageId))
      : -1;
    if (targetIndex >= 0) {
      virtuosoRef.current?.scrollToIndex?.({
        index: targetIndex,
        align: "center",
        behavior: "auto",
      });
    }
    window.cancelAnimationFrame(searchHighlightFrameRef.current);
    let secondFrame = 0;
    searchHighlightFrameRef.current = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        searchHighlightCleanupRef.current?.();
        searchHighlightCleanupRef.current = applyTranscriptSearchHighlights(
          messagesRef.current,
          searchQuery,
          searchCursor,
        );
      });
    });
    return () => {
      window.cancelAnimationFrame(searchHighlightFrameRef.current);
      window.cancelAnimationFrame(secondFrame);
      searchHighlightCleanupRef.current?.();
      searchHighlightCleanupRef.current = null;
    };
  }, [
    currentSearchMatch,
    messages,
    searchCursor,
    searchOpen,
    searchQuery,
  ]);

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
  const updateMessage = (messageId, updater, options = {}) => {
    const currentMessages = messageStateRef.current;
    let messageIndex = messageIndexRef.current.get(messageId);
    if (
      !Number.isInteger(messageIndex)
      || currentMessages[messageIndex]?.id !== messageId
    ) {
      messageIndex = currentMessages.findIndex((message) => message.id === messageId);
      if (messageIndex >= 0) messageIndexRef.current.set(messageId, messageIndex);
    }
    if (messageIndex < 0) return { messageId, bubble: findBubble(messageId), handled: false };
    const currentMessage = currentMessages[messageIndex];
    const nextMessage = updater(currentMessage);
    if (nextMessage === currentMessage) {
      return { messageId, bubble: findBubble(messageId), handled: true };
    }
    const nextMessages = currentMessages.slice();
    nextMessages[messageIndex] = nextMessage;
    commitMessageState(nextMessages, options);
    return { messageId, bubble: findBubble(messageId), handled: true };
  };
  const resetMessages = ({ showWelcome: nextShowWelcome = false } = {}) => {
    messageStateRef.current = [];
    messageIndexRef.current.clear();
    cancelMessageRender();
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
    const nextMessages = [...messageStateRef.current, message];
    messageStateRef.current = nextMessages;
    messageIndexRef.current.set(messageId, nextMessages.length - 1);
    cancelMessageRender();
    flushSync(() => {
      setShowWelcome(false);
      setMessages(nextMessages);
    });
    scrollToBottom({ force: payload?.role === "user" });
    return { messageId, bubble: findBubble(messageId) };
  };

  useEffect(() => {
    onEmptyStateChange?.(showWelcome);
  }, [onEmptyStateChange, showWelcome]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.cancelAnimationFrame(scrollFrameRef.current);
      window.cancelAnimationFrame(messageRenderFrameRef.current);
      window.cancelAnimationFrame(searchHighlightFrameRef.current);
      searchHighlightCleanupRef.current?.();
      searchHighlightCleanupRef.current = null;
      messageRenderFrameRef.current = 0;
      messageRenderPendingRef.current = false;
      pendingMessageScrollRef.current = { force: false, behavior: "auto" };
    };
  }, []);

  useEffect(() => {
    const copyTimers = new Set();
    const copyCodeBlock = async (button) => {
      if (!button || button.dataset.copying === "true") return;
      const code = button.closest("[data-message-code-block]")?.querySelector("code");
      const value = redactCopyText(code?.textContent || "");
      if (!value) return;
      const initialLabel = button.textContent || "复制";
      button.dataset.copying = "true";
      button.disabled = true;
      try {
        await copyTextToClipboard(value);
        button.textContent = "已复制";
        button.setAttribute("aria-label", "已复制代码");
        button.setAttribute("title", "已复制代码");
      } catch {
        button.textContent = "复制失败";
        button.setAttribute("aria-label", "复制代码失败");
        button.setAttribute("title", "复制代码失败");
      } finally {
        button.disabled = false;
        const timer = window.setTimeout(() => {
          copyTimers.delete(timer);
          if (!button.isConnected) return;
          button.dataset.copying = "false";
          button.textContent = initialLabel;
          button.setAttribute("aria-label", "复制代码");
          button.setAttribute("title", "复制代码");
        }, 1_600);
        copyTimers.add(timer);
      }
    };
    const handleMessageActionClick = (event) => {
      const messagesNode = messagesRef.current;
      if (!messagesNode) return;
      const target = event.target instanceof Element ? event.target : null;
      const codeCopyButton = target?.closest("[data-message-code-copy]");
      if (codeCopyButton && messagesNode.contains(codeCopyButton)) {
        event.preventDefault();
        void copyCodeBlock(codeCopyButton);
        return;
      }
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
      if (!["copy", "edit", "retry", "rewind"].includes(action)) return;
      if (action === "copy") {
        const assistantMessage = [...messageStateRef.current].reverse().find((message) => (
          message?.role === "assistant" && !message.thinking && !message.streaming
        ));
        if (!assistantMessage) {
          detail.handled = false;
          return;
        }
        const copyDetail = {
          action,
          args: String(detail.args || "").trim(),
          assistantMessage,
          messages: messageStateRef.current,
          messageId: assistantMessage.id,
          rawContent: assistantMessage.rawContent,
        };
        window.dispatchEvent(new CustomEvent(actionEvents.copy, { detail: copyDetail }));
        detail.handled = true;
        return;
      }
      const candidates = messageStateRef.current
        .map((message, index) => ({ message, index }))
        .filter(({ message }) => {
          if (action === "edit") return message?.role === "user";
          if (action === "rewind") return message?.role === "user" && Boolean(message.sourceMessageId);
          return message?.role === "assistant"
            && !message.thinking
            && !message.streaming
            && Boolean(message.retryable);
        });
      const target = candidates[candidates.length - 1];
      if (!target) {
        detail.handled = false;
        return;
      }
      const messageId = String(target.message.id || "");
      const bubble = findBubble(messageId);
      const visibleButton = bubble?.closest(".message-row")?.querySelector(
        `[data-message-action="${action}"]`,
      );
      if (visibleButton && !visibleButton.disabled) {
        detail.handled = true;
        visibleButton.click();
        return;
      }
      detail.handled = true;
      if (virtuosoRef.current?.scrollToIndex) {
        virtuosoRef.current.scrollToIndex({
          index: target.index,
          align: "center",
          behavior: "auto",
        });
      }
      window.dispatchEvent(
        new CustomEvent(actionEvents[action], {
          detail: {
            action,
            bubble,
            messageId,
            sourceMessageId: target.message.sourceMessageId || "",
            rawContent: target.message.rawContent || "",
          },
        }),
      );
    };
    document.addEventListener("click", handleMessageActionClick);
    window.addEventListener("knowflow:react-message-command", handleMessageCommand);
    return () => {
      document.removeEventListener("click", handleMessageActionClick);
      window.removeEventListener("knowflow:react-message-command", handleMessageCommand);
      copyTimers.forEach((timer) => window.clearTimeout(timer));
      copyTimers.clear();
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
      }), { defer: Boolean(detail.streaming) });
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
      const nextMessages = messageStateRef.current.map((message) => {
        const runId = String(message.run?.id || message.run?.runId || "");
        if (runId !== String(detail.runId)) return message;
        didUpdate = true;
        return { ...message, run: { ...message.run, artifacts: nextArtifacts } };
      });
      if (didUpdate) commitMessageState(nextMessages);
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

  const seedComposer = (prompt) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-composer-reset", {
      detail: { focus: true, question: prompt },
    }));
  };

  const messageListContext = useMemo(() => ({
    currentTask,
    interactionOwner,
    pendingInteractionCount,
    retrySessionSwitch,
    revealCurrentTask,
    searchMessageIds,
    currentSearchMessageId: currentSearchMatch?.messageId || "",
    sessionSwitch,
  }), [
    currentSearchMatch?.messageId,
    currentTask,
    interactionOwner,
    pendingInteractionCount,
    searchMessageIds,
    sessionSwitch,
  ]);
  const messagesClassName = `messages messages-virtualized${sessionSwitch?.status === "loading" ? " session-switching" : ""}`;

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
      {messages.length ? (
        <Virtuoso
          ref={virtuosoRef}
          className={messagesClassName}
          id={"chat-messages"}
          data={messages}
          data-message-count={messages.length}
          aria-busy={sessionSwitch?.status === "loading"}
          onScroll={handleMessagesScroll}
          scrollerRef={setMessagesScroller}
          components={MESSAGE_VIRTUOSO_COMPONENTS}
          context={messageListContext}
          computeItemKey={messageItemKey}
          itemContent={messageItemContent}
          atBottomThreshold={96}
          atBottomStateChange={handleVirtuosoAtBottom}
          followOutput={followVirtuosoOutput}
          defaultItemHeight={72}
          initialItemCount={Math.min(messages.length, 24)}
          increaseViewportBy={{ top: 600, bottom: 600 }}
          minOverscanItemCount={3}
          skipAnimationFrameInResizeObserver={true}
          style={{ height: "100%" }}
        />
      ) : (
        <div
          className={messagesClassName}
          id={"chat-messages"}
          ref={setMessagesScroller}
          data-message-count={0}
          aria-busy={sessionSwitch?.status === "loading"}
          onScroll={handleMessagesScroll}
        >
          <SessionSwitchState sessionSwitch={sessionSwitch} onRetry={retrySessionSwitch} />
          {showWelcome ? (
            <WelcomeSurface onSeed={seedComposer} workspaceState={workspaceState} />
          ) : null}
        </div>
      )}
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
