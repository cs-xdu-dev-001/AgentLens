import { useEffect, useRef } from "react";
import {
  agentWindowFaviconDataUrl,
  agentWindowFeedback,
  shouldNotifyAgentWindow,
} from "./agentWindowFeedback.js";

function findFavicon() {
  return document.querySelector('link[rel~="icon"]');
}

export function AgentWindowFeedback() {
  const feedbackRef = useRef(agentWindowFeedback(null));

  useEffect(() => {
    const originalTitle = document.title || "AgentLens";
    const favicon = findFavicon();
    const originalFavicon = favicon?.getAttribute("href") || "/favicon.svg";

    const publishNotification = (feedback) => {
      if (
        !feedback.notification
        || typeof window.Notification !== "function"
        || window.Notification.permission !== "granted"
      ) return;
      try {
        new window.Notification("AgentLens", {
          body: feedback.notification,
          icon: "/favicon.svg",
          tag: `agentlens-${feedback.runId || feedback.state}`,
        });
      } catch {
        // Browser or operating-system notifications can be unavailable even after permission was granted.
      }
    };

    const applyFeedback = (next) => {
      const previous = feedbackRef.current;
      feedbackRef.current = next;
      document.title = next.title;
      if (favicon) {
        favicon.setAttribute(
          "href",
          next.state === "idle" ? originalFavicon : agentWindowFaviconDataUrl(next.state),
        );
      }
      if (shouldNotifyAgentWindow(previous, next, {
        visibilityState: document.visibilityState,
        hasFocus: document.hasFocus(),
      })) publishNotification(next);
    };

    const handleRunUpdated = (event) => {
      const next = agentWindowFeedback(event.detail?.run);
      const foreground = document.visibilityState === "visible" && document.hasFocus();
      applyFeedback(
        foreground && ["completed", "failed"].includes(next.state)
          ? agentWindowFeedback(null)
          : next,
      );
    };
    const acknowledgeTerminalState = () => {
      if (
        document.visibilityState === "visible"
        && document.hasFocus()
        && ["completed", "failed"].includes(feedbackRef.current.state)
      ) applyFeedback(agentWindowFeedback(null));
    };

    window.addEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
    window.addEventListener("focus", acknowledgeTerminalState);
    document.addEventListener("visibilitychange", acknowledgeTerminalState);
    return () => {
      window.removeEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
      window.removeEventListener("focus", acknowledgeTerminalState);
      document.removeEventListener("visibilitychange", acknowledgeTerminalState);
      document.title = originalTitle;
      if (favicon) favicon.setAttribute("href", originalFavicon);
    };
  }, []);

  return null;
}
