import { useEffect, useRef, useState } from "react";
import { workspaceApi } from "../api/client.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { agentWindowFeedback } from "./agentWindowFeedback.js";
import { AgentNotificationToggle } from "./AgentNotificationToggle.jsx";
import { workspaceGitPresentation } from "./workspaceGitPresentation.js";


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

export function workspaceHeaderState(status, loading = false, error = "") {
  if (loading) return { label: "工作区", state: "loading" };
  if (error) {
    return {
      label: "工作区状态异常",
      state: "error",
      title: error,
    };
  }
  if (!status?.enabled) return { label: "工作区关闭", state: "disabled" };
  const itemCount = Math.max(0, Number(status.itemCount) || 0);
  const instructionSources = Array.isArray(status.projectInstructions?.sources)
    ? status.projectInstructions.sources
      .map((item) => safeAgentText(item?.path, 120))
      .filter(Boolean)
    : [];
  const instructionCount = instructionSources.length;
  const git = workspaceGitPresentation(status);
  const parts = [
    git.repository ? git.label : "隔离工作区",
    !git.repository && itemCount ? `${itemCount}项` : "",
    instructionCount ? `${instructionCount}份项目指令` : "",
  ].filter(Boolean);
  const title = [
    git.title,
    `工作区内${itemCount}项`,
    instructionSources.length
      ? `项目指令：${instructionSources.join("、")}`
      : "尚未发现AGENTS.md或CLAUDE.md",
  ].filter(Boolean).join("。 ");
  return {
    label: parts.join(" · "),
    state: git.repository ? git.state : status.sandboxReady ? "ready" : "available",
    title,
  };
}

export function ChatTopbar({ drawerCollapsed = true }) {
  const [sessionTitle, setSessionTitle] = useState("");
  const [pendingTitle, setPendingTitle] = useState("");
  const [switching, setSwitching] = useState(false);
  const [runHeader, setRunHeader] = useState(() => runHeaderState(null));
  const [workspaceStatus, setWorkspaceStatus] = useState(null);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [workspaceError, setWorkspaceError] = useState("");
  const workspaceReloadRef = useRef(() => {});

  useEffect(() => {
    let active = true;
    const loadWorkspace = async ({ showLoading = false } = {}) => {
      if (active && showLoading) setWorkspaceLoading(true);
      try {
        const status = await workspaceApi.status();
        if (active) {
          setWorkspaceStatus(status);
          setWorkspaceError("");
        }
      } catch {
        if (active) setWorkspaceError("工作区状态读取失败，请重试。");
      } finally {
        if (active) setWorkspaceLoading(false);
      }
    };
    workspaceReloadRef.current = () => void loadWorkspace({ showLoading: true });
    const handleWorkspaceUpdated = () => void loadWorkspace();
    void loadWorkspace({ showLoading: true });
    window.addEventListener("knowflow:react-workspace-updated", handleWorkspaceUpdated);
    return () => {
      active = false;
      workspaceReloadRef.current = () => {};
      window.removeEventListener("knowflow:react-workspace-updated", handleWorkspaceUpdated);
    };
  }, []);

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
      const nextRunHeader = runHeaderState(event.detail?.run || null);
      setRunHeader(nextRunHeader);
      if (["completed", "failed"].includes(nextRunHeader.state)) {
        window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated"));
      }
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
  const handleWorkspaceOpen = () => window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
    detail: { page: "workspace" },
  }));
  const handleWorkspaceRetry = () => {
    workspaceReloadRef.current();
  };
  const runLabel = RUN_LABELS[runHeader.state] || RUN_LABELS.idle;
  const workspaceHeader = workspaceHeaderState(
    workspaceStatus,
    workspaceLoading,
    workspaceError,
  );
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
        <AgentNotificationToggle />
        <button
          className={`chat-workspace-toggle is-${workspaceHeader.state}`}
          type={"button"}
          aria-label={workspaceError
            ? `${workspaceHeader.label}，重试`
            : `${workspaceHeader.label}，打开工作区`}
          title={`${workspaceHeader.label}。${workspaceHeader.title || ""}。${workspaceError ? "重试读取状态" : "仅当前用户可见（打开工作区）"}`}
          onClick={workspaceError ? handleWorkspaceRetry : handleWorkspaceOpen}
        >
          <svg aria-hidden={"true"} viewBox={"0 0 20 20"} focusable={"false"}>
            <path d={"M2.8 5.4h5l1.4 1.7h8v8.2H2.8z"} />
          </svg>
          <span>{workspaceHeader.label}</span>
        </button>
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
