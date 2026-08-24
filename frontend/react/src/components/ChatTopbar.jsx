import { useEffect, useState } from "react";
import { safeAgentText } from "../controller/agentEvents.js";
import { agentWindowFeedback } from "./agentWindowFeedback.js";


const RUN_LABELS = {
  completed: "已完成",
  failed: "失败",
  idle: "运行",
  running: "运行中",
  waiting: "等待操作",
};

function cleanSessionTitle(value) {
  return safeAgentText(value, 160);
}

function runHeaderState(run) {
  const feedback = agentWindowFeedback(run);
  const summary = run?.runSummary && typeof run.runSummary === "object"
    ? run.runSummary
    : {};
  const completed = Math.max(0, Number(summary.completedSteps) || 0);
  const total = Math.max(completed, Number(summary.totalSteps) || 0);
  return {
    progress: total ? `${completed}/${total}` : "",
    state: feedback.state,
  };
}

export function ChatTopbar({ drawerCollapsed = true }) {
  const [sessionTitle, setSessionTitle] = useState("");
  const [pendingTitle, setPendingTitle] = useState("");
  const [switching, setSwitching] = useState(false);
  const [runHeader, setRunHeader] = useState(() => runHeaderState(null));

  useEffect(() => {
    const handleActiveSession = (event) => {
      const detail = event.detail || {};
      setSessionTitle(detail.sessionId ? cleanSessionTitle(detail.title) : "");
      setPendingTitle("");
      setSwitching(false);
    };
    const handleSessionSwitch = (event) => {
      const detail = event.detail || {};
      if (detail.status === "loading") {
        setPendingTitle(cleanSessionTitle(detail.title));
        setSwitching(true);
        return;
      }
      setPendingTitle("");
      setSwitching(false);
    };
    window.addEventListener("knowflow:react-active-session-updated", handleActiveSession);
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
    return () => {
      window.removeEventListener("knowflow:react-active-session-updated", handleActiveSession);
      window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
    };
  }, []);

  useEffect(() => {
    const handleRunUpdated = (event) => {
      setRunHeader(runHeaderState(event.detail?.run || null));
    };
    window.addEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
    return () => window.removeEventListener(
      "knowflow:react-agent-run-updated",
      handleRunUpdated,
    );
  }, []);

  const handleRefresh = () => window.dispatchEvent(new CustomEvent("knowflow:react-refresh"));
  const handleDrawerToggle = () => window.dispatchEvent(new CustomEvent("knowflow:react-drawer-toggle", {
    detail: {
      focus: drawerCollapsed,
      restoreFocus: !drawerCollapsed,
    },
  }));
  const runLabel = RUN_LABELS[runHeader.state] || RUN_LABELS.idle;
  const runAccessibleLabel = [runLabel, runHeader.progress, "Alt+T打开运行详情"]
    .filter(Boolean)
    .join("，");
  return (
    <header className={"chat-topbar"}>
      <div className={"chat-session-heading"} aria-busy={switching}>
        <h1 title={pendingTitle || sessionTitle || "问答"}>
          {pendingTitle || sessionTitle || "问答"}
        </h1>
        {switching ? <span className={"chat-session-switching"} role={"status"}>{"打开中"}</span> : null}
      </div>
      <div className={"chat-topbar-actions"}>
        <button
          className={`chat-run-toggle is-${runHeader.state}`}
          id={"inspector-toggle"}
          type={"button"}
          aria-controls={"evidence-drawer"}
          aria-expanded={!drawerCollapsed}
          aria-keyshortcuts={"Alt+T"}
          aria-label={runAccessibleLabel}
          title={`${runLabel}${runHeader.progress ? ` · ${runHeader.progress}` : ""}（Alt+T）`}
          onClick={handleDrawerToggle}
        >
          <span className={"chat-run-dot"} aria-hidden={"true"} />
          <span aria-live={"polite"}>{runLabel}</span>
          {runHeader.progress ? <span className={"chat-run-progress"}>{runHeader.progress}</span> : null}
        </button>
        <button
          aria-label={"刷新当前会话"}
          id={"refresh-btn"}
          title={"刷新当前会话"}
          type={"button"}
          onClick={handleRefresh}
        >
          <svg aria-hidden={"true"} viewBox={"0 0 20 20"} focusable={"false"}>
            <path d={"M15.7 7.3A6 6 0 1 0 16 11"} />
            <path d={"M12.8 4.5h3.4v3.4"} />
          </svg>
        </button>
      </div>
    </header>
  );
}
