import { useEffect, useRef, useState } from "react";
import { Folder, RefreshCw } from "lucide-react";
import { workspaceApi } from "../api/client.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { agentWindowFeedback } from "./agentWindowFeedback.js";
import { AgentNotificationToggle } from "./AgentNotificationToggle.jsx";
import { workspaceGitPresentation } from "./workspaceGitPresentation.js";
import { Tooltip } from "./Tooltip.jsx";


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

export function ChatTopbar({ drawerCollapsed = true, onWorkspaceStateChange }) {
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
    let latestRequest = 0;
    const loadWorkspace = async ({ showLoading = false } = {}) => {
      const request = ++latestRequest;
      if (active && showLoading) {
        setWorkspaceLoading(true);
        onWorkspaceStateChange?.({ status: null, loading: true, error: "" });
      }
      try {
        const status = await workspaceApi.status();
        if (active && request === latestRequest) {
          setWorkspaceStatus(status);
          setWorkspaceError("");
          onWorkspaceStateChange?.({ status, loading: false, error: "" });
        }
      } catch {
        if (active && request === latestRequest) {
          const error = "工作区状态读取失败，请重试。";
          setWorkspaceError(error);
          onWorkspaceStateChange?.({ status: null, loading: false, error });
        }
      } finally {
        if (active && request === latestRequest) setWorkspaceLoading(false);
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
  }, [onWorkspaceStateChange]);

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
  const workspaceTooltip = [
    workspaceHeader.label,
    workspaceHeader.title,
    workspaceError ? "点击重试读取状态" : "点击打开工作区",
  ].filter(Boolean).join("。 ");
  const runAccessibleLabel = [runLabel, runHeader.progress, "Alt+T打开运行详情"]
    .filter(Boolean)
    .join("，");
  return (
    <header className={"chat-topbar"}>
      <div className={"chat-session-heading"} aria-busy={switching}>
        <h1 title={pendingTitle || sessionTitle || "新任务"}>
          {pendingTitle || sessionTitle || "新任务"}
        </h1>
        {switching ? <span className={"chat-session-switching"} role={"status"}>{"打开中"}</span> : null}
      </div>
      <div className={"chat-topbar-actions"}>
        <AgentNotificationToggle />
        <Tooltip content={workspaceTooltip} side={"bottom"}>
          <button
            className={`chat-workspace-toggle is-${workspaceHeader.state}`}
            type={"button"}
            aria-busy={workspaceLoading}
            disabled={workspaceLoading && Boolean(workspaceError)}
            aria-label={workspaceError
              ? `${workspaceHeader.label}，重试`
              : `${workspaceHeader.label}，打开工作区`}
            onClick={workspaceError ? handleWorkspaceRetry : handleWorkspaceOpen}
          >
            <Folder size={16} strokeWidth={1.8} aria-hidden={"true"} />
            <span className={"chat-workspace-label"}>{workspaceHeader.label}</span>
          </button>
        </Tooltip>
        <Tooltip content={drawerCollapsed ? "打开运行详情" : "收起运行详情"} shortcut={"Alt+T"} side={"bottom"}>
          <button
            className={`chat-run-toggle is-${runHeader.state}`}
            id={"inspector-toggle"}
            type={"button"}
            aria-controls={"evidence-drawer"}
            aria-expanded={!drawerCollapsed}
            aria-keyshortcuts={"Alt+T"}
            aria-label={runAccessibleLabel}
            onClick={handleDrawerToggle}
          >
            <span className={"chat-run-dot"} aria-hidden={"true"} />
            <span aria-live={"polite"}>{runLabel}</span>
            {runHeader.progress ? <span className={"chat-run-progress"}>{runHeader.progress}</span> : null}
          </button>
        </Tooltip>
        <Tooltip content={"刷新当前会话"} side={"bottom"}>
          <button
            aria-label={"刷新当前会话"}
            id={"refresh-btn"}
            type={"button"}
            onClick={handleRefresh}
          >
            <RefreshCw size={16} strokeWidth={1.8} aria-hidden={"true"} />
          </button>
        </Tooltip>
      </div>
    </header>
  );
}
