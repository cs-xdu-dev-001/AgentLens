import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { redactEmailAddresses, renderMarkdown } from "../controller/markdown.js";
import { AgentApprovalPrompt } from "./AgentApprovalPrompt.jsx";
import { AgentTraceStrip } from "./AgentTraceStrip.jsx";

const actionEvents = {
  copy: "knowflow:react-message-copy",
  retry: "knowflow:react-message-retry",
};

function MessageBubble({ message }) {
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
    "aria-busy": message.thinking ? "true" : undefined,
  };

  if (message.role === "assistant") {
    return (
      <div {...props}>
        <AgentTraceStrip
          messageId={message.id}
          trace={message.trace}
          approvals={message.approvals}
        />
        {message.approvals?.length ? (
          <div className={"agent-approval-list"}>
            {message.approvals.map((approval) => (
              <AgentApprovalPrompt
                approval={approval}
                key={approval.approvalId}
              />
            ))}
          </div>
        ) : null}
        {message.thinking ? (
          <div
            className={"thinking-indicator"}
            aria-label={"模型正在处理"}
          >
            <span></span>
            <span></span>
            <span></span>
          </div>
        ) : (
          <div
            className={"message-markdown"}
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(redactEmailAddresses(message.rawContent)),
            }}
          />
        )}
      </div>
    );
  }

  return <div {...props}>{message.rawContent}</div>;
}

function normalizeRawContent(value) {
  return String(value ?? "");
}

function MessageRow({ message }) {
  const rowClassName = ["message-row", message.role, message.thinking ? "thinking-row" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={rowClassName}>
      <MessageBubble message={message} />
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
  const nextMessageIdRef = useRef(1);
  const [messages, setMessages] = useState([]);
  const [showWelcome, setShowWelcome] = useState(true);
  const findBubble = (messageId) =>
    messagesRef.current?.querySelector('[data-react-message-id="' + messageId + '"]') || null;
  const scrollToBottom = () => {
    const node = messagesRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  };
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
    scrollToBottom();
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
    scrollToBottom();
    return { messageId, bubble: findBubble(messageId) };
  };

  useEffect(() => {
    document.querySelector("#page-chat")?.classList.toggle("chat-empty", showWelcome);
    return () => document.querySelector("#page-chat")?.classList.remove("chat-empty");
  }, [showWelcome]);

  useEffect(() => {
    const messagesNode = messagesRef.current;
    if (!messagesNode) return undefined;
    const handleMessageActionClick = (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const button = target?.closest("[data-message-action]");
      if (!button || !messagesNode.contains(button)) return;
      const eventName = actionEvents[button.dataset.messageAction];
      if (!eventName) return;
      const bubble = button.closest(".message-row")?.querySelector(".message.assistant") || null;
      event.preventDefault();
      window.dispatchEvent(
        new CustomEvent(eventName, {
          detail: {
            bubble,
            messageId: bubble?.dataset.reactMessageId || "",
            rawContent: bubble?.dataset.rawContent || "",
          },
        }),
      );
    };
    messagesNode.addEventListener("click", handleMessageActionClick);
    return () => messagesNode.removeEventListener("click", handleMessageActionClick);
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

    window.addEventListener("knowflow:react-message-append", handleAppend);
    window.addEventListener("knowflow:react-messages-reset", handleReset);
    window.addEventListener("knowflow:react-message-content", handleContent);
    window.addEventListener("knowflow:react-message-thinking", handleThinking);
    window.addEventListener("knowflow:react-message-trace", handleTrace);
    window.addEventListener("knowflow:react-message-approvals", handleApprovals);
    return () => {
      window.removeEventListener("knowflow:react-message-append", handleAppend);
      window.removeEventListener("knowflow:react-messages-reset", handleReset);
      window.removeEventListener("knowflow:react-message-content", handleContent);
      window.removeEventListener("knowflow:react-message-thinking", handleThinking);
      window.removeEventListener("knowflow:react-message-trace", handleTrace);
      window.removeEventListener("knowflow:react-message-approvals", handleApprovals);
    };
  }, []);

  return (
    <div className={"messages"} id={"chat-messages"} ref={messagesRef}>
      {showWelcome ? (
        <div className={"welcome-card"}>
          <h2>{"有什么可以帮你？"}</h2>
        </div>
      ) : null}
      {messages.map((message) => (
        <MessageRow key={message.id} message={message} />
      ))}
    </div>
  );
}
