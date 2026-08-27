import { useEffect, useRef, useState } from "react";
import { runtimeApi } from "../api/client.js";
import {
  AGENT_NOTIFICATION_PREFERENCE_EVENT,
  agentNotificationPreference,
  buildAgentDiagnosticReport,
  agentWindowFaviconDataUrl,
  agentWindowFeedback,
  shouldNotifyAgentWindow,
} from "./agentWindowFeedback.js";
import { notifyError, notifyToast } from "./errorFeedback.js";

function findFavicon() {
  return document.querySelector('link[rel~="icon"]');
}

export function AgentWindowFeedback() {
  const feedbackRef = useRef(agentWindowFeedback(null));
  const diagnosticRef = useRef(null);
  const runRef = useRef(null);
  const versionRef = useRef("");
  const [fallbackReport, setFallbackReport] = useState("");

  useEffect(() => {
    const originalTitle = document.title || "AgentLens";
    const favicon = findFavicon();
    const originalFavicon = favicon?.getAttribute("href") || "/favicon.svg";
    let notificationEnabled = agentNotificationPreference().enabled;
    void runtimeApi.get()
      .then((runtime) => {
        versionRef.current = String(runtime?.version || "");
      })
      .catch(() => {
        // Offline diagnostics remain useful without a server version.
      });

    const publishNotification = (feedback) => {
      if (
        !feedback.notification
        || !notificationEnabled
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
      runRef.current = event.detail?.run || null;
      const next = agentWindowFeedback(runRef.current);
      const foreground = document.visibilityState === "visible" && document.hasFocus();
      applyFeedback(
        foreground && ["completed", "failed"].includes(next.state)
          ? agentWindowFeedback(null)
          : next,
      );
    };
    const handleNotificationPreference = (event) => {
      notificationEnabled = Boolean(event.detail?.enabled);
    };
    const handleDiagnosticCopy = async () => {
      const report = buildAgentDiagnosticReport(runRef.current, {
        platform: navigator.userAgentData?.platform || navigator.platform || "浏览器",
        version: versionRef.current,
      });
      try {
        if (!navigator.clipboard?.writeText) {
          throw new Error("Clipboard API unavailable");
        }
        await navigator.clipboard.writeText(report);
        notifyToast("脱敏诊断已复制");
      } catch (error) {
        setFallbackReport(report);
        notifyError(error, "自动复制失败，已打开脱敏诊断。");
      }
    };
    const acknowledgeTerminalState = () => {
      if (
        document.visibilityState === "visible"
        && document.hasFocus()
        && ["completed", "failed"].includes(feedbackRef.current.state)
      ) applyFeedback(agentWindowFeedback(null));
    };

    window.addEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
    window.addEventListener(AGENT_NOTIFICATION_PREFERENCE_EVENT, handleNotificationPreference);
    window.addEventListener("knowflow:react-diagnostic-copy-request", handleDiagnosticCopy);
    window.addEventListener("focus", acknowledgeTerminalState);
    document.addEventListener("visibilitychange", acknowledgeTerminalState);
    return () => {
      window.removeEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
      window.removeEventListener(AGENT_NOTIFICATION_PREFERENCE_EVENT, handleNotificationPreference);
      window.removeEventListener("knowflow:react-diagnostic-copy-request", handleDiagnosticCopy);
      window.removeEventListener("focus", acknowledgeTerminalState);
      document.removeEventListener("visibilitychange", acknowledgeTerminalState);
      document.title = originalTitle;
      if (favicon) favicon.setAttribute("href", originalFavicon);
    };
  }, []);

  useEffect(() => {
    if (!fallbackReport) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setFallbackReport("");
    };
    document.addEventListener("keydown", handleKeyDown);
    window.requestAnimationFrame(() => {
      diagnosticRef.current?.focus();
      diagnosticRef.current?.select();
    });
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [fallbackReport]);

  if (!fallbackReport) return null;
  return (
    <div
      className={"modal-backdrop diagnostic-report-backdrop"}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) setFallbackReport("");
      }}
    >
      <section
        aria-labelledby={"diagnostic-report-title"}
        aria-modal={"true"}
        className={"modal-panel diagnostic-report-dialog"}
        role={"dialog"}
      >
        <header className={"modal-head"}>
          <h2 id={"diagnostic-report-title"}>{"脱敏诊断"}</h2>
          <button
            aria-label={"关闭脱敏诊断"}
            className={"icon-button"}
            onClick={() => setFallbackReport("")}
            type={"button"}
          >
            {"×"}
          </button>
        </header>
        <div className={"diagnostic-report-body"}>
          <textarea
            aria-label={"脱敏诊断内容"}
            onFocus={(event) => event.currentTarget.select()}
            readOnly
            ref={diagnosticRef}
            value={fallbackReport}
          />
          <div className={"modal-actions"}>
            <button
              onClick={() => {
                diagnosticRef.current?.focus();
                diagnosticRef.current?.select();
              }}
              type={"button"}
            >
              {"全选诊断"}
            </button>
            <button
              className={"primary"}
              onClick={() => setFallbackReport("")}
              type={"button"}
            >
              {"关闭"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
