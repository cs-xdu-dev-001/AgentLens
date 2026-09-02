import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { AuthScreen } from "./components/AuthScreen.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { ChatPage } from "./components/ChatPage.jsx";
import { CommandPalette } from "./components/CommandPalette.jsx";
import { composerCommandSuggestions } from "./components/composerCommands.js";
import { Toast } from "./components/Toast.jsx";
import { AgentWindowFeedback } from "./components/AgentWindowFeedback.jsx";
import { KnowFlowController } from "./components/KnowFlowController.jsx";
import { useAuth } from "./auth/AuthProvider.jsx";

const pageKeys = new Set(["chat", "knowledge", "skills", "workspace", "memory", "tools", "settings", "cli-auth"]);
const palettePageActions = new Set(["knowledge", "workspace", "tools", "skills", "memory", "settings"]);
const SIDEBAR_LAYOUT_VERSION = "20260522-chatgpt-sidebar";
const pageModuleLoaders = Object.freeze({
  knowledge: () => import("./components/KnowledgePage.jsx"),
  skills: () => import("./components/SkillsPage.jsx"),
  workspace: () => import("./components/WorkbenchPage.jsx"),
  memory: () => import("./components/MemoryPage.jsx"),
  tools: () => import("./components/ToolsPage.jsx"),
  settings: () => import("./components/SettingsPage.jsx"),
  "cli-auth": () => import("./components/CliDeviceAuthPage.jsx"),
});

function lazyNamed(page, exportName) {
  return lazy(() => pageModuleLoaders[page]().then((module) => ({
    default: module[exportName],
  })));
}

const KnowledgePage = lazyNamed("knowledge", "KnowledgePage");
const SkillsPage = lazyNamed("skills", "SkillsPage");
const WorkbenchPage = lazyNamed("workspace", "WorkbenchPage");
const MemoryPage = lazyNamed("memory", "MemoryPage");
const ToolsPage = lazyNamed("tools", "ToolsPage");
const SettingsPage = lazyNamed("settings", "SettingsPage");
const CliDeviceAuthPage = lazyNamed("cli-auth", "CliDeviceAuthPage");

function preloadPageModule(page) {
  pageModuleLoaders[page]?.().catch(() => {
    // Navigation still owns the visible recovery state if a speculative load fails.
  });
}

function DeferredPage({ active, label, page, visited, children }) {
  if (!active && !visited) return null;
  return (
    <Suspense
      fallback={active ? (
        <section
          className={"page active deferred-page-loading"}
          id={`page-${page}`}
          aria-busy={"true"}
          aria-live={"polite"}
        >
          <span>{`正在打开${label}`}</span>
        </section>
      ) : null}
    >
      {children}
    </Suspense>
  );
}

function readStoredBoolean(key, defaultValue) {
  if (typeof window === "undefined") return defaultValue;
  try {
    const stored = window.localStorage.getItem(key);
    return stored === null ? defaultValue : stored === "1";
  } catch {
    return defaultValue;
  }
}

function writeStoredBoolean(key, value) {
  try {
    window.localStorage.setItem(key, value ? "1" : "0");
  } catch {
    // Storage can be unavailable in private contexts; layout still works in memory.
  }
}

function readInitialSidebarCollapsed() {
  if (typeof window === "undefined") return false;
  try {
    if (window.localStorage.getItem("knowflow.sidebarLayoutVersion") !== SIDEBAR_LAYOUT_VERSION) {
      window.localStorage.setItem("knowflow.sidebarLayoutVersion", SIDEBAR_LAYOUT_VERSION);
      window.localStorage.setItem("knowflow.sidebarCollapsed", "0");
    }
  } catch {
    return false;
  }
  return readStoredBoolean("knowflow.sidebarCollapsed", false);
}

function readInitialPage() {
  if (typeof window === "undefined") return "chat";
  const page = new URLSearchParams(window.location.search).get("page");
  return page === "tools" || pageKeys.has(page) ? page : "chat";
}

function currentFocusOutsideWorkbench() {
  if (typeof document === "undefined" || typeof HTMLElement === "undefined") return null;
  const element = document.activeElement;
  if (
    !(element instanceof HTMLElement)
    || element === document.body
    || element.closest("#evidence-drawer")
  ) return null;
  return element;
}

function restoreWorkbenchOrigin(element) {
  window.requestAnimationFrame(() => {
    if (element?.isConnected && typeof element.focus === "function") {
      element.focus();
      return;
    }
    window.dispatchEvent(new CustomEvent("knowflow:react-composer-focus"));
  });
}

function paletteSessionTitle(session) {
  const title = String(session?.title || "").trim();
  if (title && title !== "新会话") return title;
  return String(session?.latest_run?.goalSummary || "新任务").trim() || "新任务";
}

function WorkbenchShell() {
  const { authenticated, loading } = useAuth();
  const [activePage, setActivePage] = useState(readInitialPage);
  const [visitedPages, setVisitedPages] = useState(() => new Set(["chat", readInitialPage()]));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readInitialSidebarCollapsed);
  const [drawerCollapsed, setDrawerCollapsed] = useState(() => readStoredBoolean("knowflow.drawerCollapsed", true));
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const [paletteSessions, setPaletteSessions] = useState([]);
  const [paletteRuntime, setPaletteRuntime] = useState({
    sending: false,
    recoveryActions: [],
    queuePaused: false,
    switching: false,
    usage: {},
  });
  const [workbenchRun, setWorkbenchRun] = useState(null);
  const [workbenchMessageId, setWorkbenchMessageId] = useState("");
  const pendingWorkbenchFocusRef = useRef(false);
  const drawerCollapsedRef = useRef(drawerCollapsed);
  const drawerFocusOriginRef = useRef(null);
  const shellLocked = loading || !authenticated;

  drawerCollapsedRef.current = drawerCollapsed;

  useEffect(() => {
    setVisitedPages((current) => {
      if (current.has(activePage)) return current;
      const next = new Set(current);
      next.add(activePage);
      return next;
    });
  }, [activePage]);

  useEffect(() => {
    const handlePageEvent = (event) => {
      const page = event.detail?.page;
      if (pageKeys.has(page)) {
        setActivePage(page);
      }
    };
    window.addEventListener("knowflow:react-page-change", handlePageEvent);
    window.addEventListener("knowflow:react-page-activated", handlePageEvent);
    return () => {
      window.removeEventListener("knowflow:react-page-change", handlePageEvent);
      window.removeEventListener("knowflow:react-page-activated", handlePageEvent);
    };
  }, []);

  useEffect(() => {
    const handleSessionIndex = (event) => {
      const nextSessions = event.detail?.sessions;
      setPaletteSessions(Array.isArray(nextSessions) ? nextSessions : []);
    };
    const handleSending = (event) => {
      setPaletteRuntime((current) => ({
        ...current,
        sending: Boolean(event.detail?.sending),
      }));
    };
    const handleAgentState = (event) => {
      const actions = Array.isArray(event.detail?.recoveryActions)
        ? event.detail.recoveryActions.filter((action) => ["continue", "retry", "fix"].includes(action))
        : [];
      setPaletteRuntime((current) => ({ ...current, recoveryActions: actions }));
    };
    const handleQueue = (event) => {
      setPaletteRuntime((current) => ({
        ...current,
        queuePaused: Boolean(event.detail?.paused),
      }));
    };
    const handleCommandUsage = (event) => {
      const usage = event.detail?.usage;
      setPaletteRuntime((current) => ({
        ...current,
        usage: usage && typeof usage === "object" ? { ...usage } : {},
      }));
    };
    const handleSessionSwitch = (event) => {
      setPaletteRuntime((current) => ({
        ...current,
        switching: event.detail?.status === "loading",
      }));
    };
    window.addEventListener("knowflow:react-session-index-updated", handleSessionIndex);
    window.addEventListener("knowflow:react-sending-updated", handleSending);
    window.addEventListener("knowflow:react-agent-composer-state", handleAgentState);
    window.addEventListener("knowflow:react-chat-queue-updated", handleQueue);
    window.addEventListener("knowflow:react-command-usage-updated", handleCommandUsage);
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
    return () => {
      window.removeEventListener("knowflow:react-session-index-updated", handleSessionIndex);
      window.removeEventListener("knowflow:react-sending-updated", handleSending);
      window.removeEventListener("knowflow:react-agent-composer-state", handleAgentState);
      window.removeEventListener("knowflow:react-chat-queue-updated", handleQueue);
      window.removeEventListener("knowflow:react-command-usage-updated", handleCommandUsage);
      window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
    };
  }, []);

  useEffect(() => {
    const runIdOf = (run) => String(run?.id || run?.runId || "");
    let activeSessionId = "";
    const updateRun = (nextRun, nextMessageId = "") => {
      if (!nextRun || typeof nextRun !== "object") return;
      setWorkbenchRun((current) => {
        const currentId = runIdOf(current);
        const nextId = runIdOf(nextRun);
        if (currentId && nextId && currentId !== nextId) return nextRun;
        const nextArtifacts = Array.isArray(nextRun.artifacts)
          ? nextRun.artifacts
          : current?.artifacts;
        return {
          ...(current || {}),
          ...nextRun,
          ...(nextArtifacts ? { artifacts: nextArtifacts } : {}),
        };
      });
      if (nextMessageId) setWorkbenchMessageId(String(nextMessageId));
    };
    const handleRunUpdated = (event) => updateRun(event.detail?.run, event.detail?.messageId);
    const handleTraceOpened = (event) => updateRun(event.detail?.run, event.detail?.messageId);
    const handleWorkspaceOpened = (event) => {
      updateRun(event.detail?.run, event.detail?.messageId);
      setActivePage("workspace");
    };
    const handleArtifactsUpdated = (event) => {
      const eventRunId = String(event.detail?.runId || "");
      const eventMessageId = String(event.detail?.messageId || "");
      setWorkbenchRun((current) => {
        if (!current) return current;
        const currentId = runIdOf(current);
        if (eventRunId && currentId && eventRunId !== currentId) return current;
        return {
          ...current,
          artifacts: Array.isArray(event.detail?.artifacts) ? event.detail.artifacts : [],
        };
      });
      if (eventMessageId) setWorkbenchMessageId(eventMessageId);
    };
    const clearWorkbenchRun = () => {
      setWorkbenchRun(null);
      setWorkbenchMessageId("");
    };
    const handleActiveSession = (event) => {
      const nextSessionId = String(event.detail?.sessionId || "");
      if (activeSessionId && nextSessionId && activeSessionId !== nextSessionId) {
        clearWorkbenchRun();
      }
      if (nextSessionId) activeSessionId = nextSessionId;
    };
    const handleSessionSwitch = (event) => {
      if (event.detail?.status === "loading") clearWorkbenchRun();
    };
    window.addEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
    window.addEventListener("knowflow:react-agent-trace-open", handleTraceOpened);
    window.addEventListener("knowflow:react-workspace-open", handleWorkspaceOpened);
    window.addEventListener("knowflow:react-agent-artifacts-updated", handleArtifactsUpdated);
    window.addEventListener("knowflow:react-active-session-updated", handleActiveSession);
    window.addEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
    window.addEventListener("knowflow:react-messages-reset", clearWorkbenchRun);
    return () => {
      window.removeEventListener("knowflow:react-agent-run-updated", handleRunUpdated);
      window.removeEventListener("knowflow:react-agent-trace-open", handleTraceOpened);
      window.removeEventListener("knowflow:react-workspace-open", handleWorkspaceOpened);
      window.removeEventListener("knowflow:react-agent-artifacts-updated", handleArtifactsUpdated);
      window.removeEventListener("knowflow:react-active-session-updated", handleActiveSession);
      window.removeEventListener("knowflow:react-session-switch-state", handleSessionSwitch);
      window.removeEventListener("knowflow:react-messages-reset", clearWorkbenchRun);
    };
  }, []);

  useEffect(() => {
    const handleWorkbenchShortcut = (event) => {
      if (event.repeat) return;
      const key = String(event.key || "").toLowerCase();
      const webShortcut = event.altKey && ["t", "e", "g"].includes(key)
        && !event.ctrlKey && !event.metaKey;
      const desktopShortcut = event.ctrlKey && ["t", "e", "g"].includes(key)
        && !event.altKey && !event.metaKey;
      if (!webShortcut && !desktopShortcut) return;
      if (document.querySelector('[role="dialog"][aria-modal="true"], dialog[open]')) return;

      const workbench = document.getElementById("evidence-drawer");
      const hasWorkbenchContent = workbench?.dataset.hasRun === "true";
      const requestedTab = key === "g" ? "artifacts" : "trace";
      const artifactCount = Number(workbench?.dataset.artifactCount || 0);
      if (
        (key === "t" && drawerCollapsed && !hasWorkbenchContent)
        || (key !== "t" && !hasWorkbenchContent)
        || (key === "g" && artifactCount < 1)
      ) return;

      event.preventDefault();
      const nextCollapsed = key === "t" && activePage === "chat" ? !drawerCollapsed : false;
      if (nextCollapsed) {
        const origin = drawerFocusOriginRef.current;
        drawerFocusOriginRef.current = null;
        restoreWorkbenchOrigin(origin);
      } else {
        drawerFocusOriginRef.current = currentFocusOutsideWorkbench();
        pendingWorkbenchFocusRef.current = true;
        window.dispatchEvent(new CustomEvent("knowflow:react-workbench-select-tab", {
          detail: { activeTab: requestedTab },
        }));
      }
      drawerCollapsedRef.current = nextCollapsed;
      writeStoredBoolean("knowflow.drawerCollapsed", nextCollapsed);
      setDrawerCollapsed(nextCollapsed);
      setActivePage("chat");
    };
    window.addEventListener("keydown", handleWorkbenchShortcut);
    return () => window.removeEventListener("keydown", handleWorkbenchShortcut);
  }, [activePage, drawerCollapsed]);

  useEffect(() => {
    document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
    return () => document.body.classList.remove("sidebar-collapsed");
  }, [sidebarCollapsed]);

  useEffect(() => {
    document.body.classList.toggle("mobile-history-open", mobileHistoryOpen);
    return () => document.body.classList.remove("mobile-history-open");
  }, [mobileHistoryOpen]);

  useEffect(() => {
    if (activePage !== "chat" && mobileHistoryOpen) {
      setMobileHistoryOpen(false);
    }
  }, [activePage, mobileHistoryOpen]);

  useEffect(() => {
    const closeOnWideViewport = () => {
      if (window.innerWidth > 760) setMobileHistoryOpen(false);
    };
    window.addEventListener("resize", closeOnWideViewport);
    return () => window.removeEventListener("resize", closeOnWideViewport);
  }, []);

  useEffect(() => {
    document.body.classList.toggle("drawer-collapsed", drawerCollapsed);
    return () => document.body.classList.remove("drawer-collapsed");
  }, [drawerCollapsed]);

  useEffect(() => {
    if (drawerCollapsed || !pendingWorkbenchFocusRef.current) return;
    pendingWorkbenchFocusRef.current = false;
    window.requestAnimationFrame(() => {
      window.dispatchEvent(new CustomEvent("knowflow:react-workbench-focus"));
    });
  }, [activePage, drawerCollapsed]);

  useEffect(() => {
    const toggleSidebar = () => {
      setSidebarCollapsed((current) => {
        const next = !current;
        writeStoredBoolean("knowflow.sidebarCollapsed", next);
        return next;
      });
    };
    const openSidebar = () => {
      writeStoredBoolean("knowflow.sidebarCollapsed", false);
      setSidebarCollapsed(false);
      if (window.innerWidth <= 760) setMobileHistoryOpen(true);
    };
    const toggleDrawer = (event) => {
      const next = !drawerCollapsedRef.current;
      drawerCollapsedRef.current = next;
      if (next) {
        const origin = drawerFocusOriginRef.current;
        drawerFocusOriginRef.current = null;
        if (event.detail?.restoreFocus !== false) restoreWorkbenchOrigin(origin);
      } else if (event.detail?.focus) {
        drawerFocusOriginRef.current = currentFocusOutsideWorkbench();
        pendingWorkbenchFocusRef.current = true;
      }
      writeStoredBoolean("knowflow.drawerCollapsed", next);
      setDrawerCollapsed(next);
    };
    const closeDrawer = (event) => {
      drawerCollapsedRef.current = true;
      writeStoredBoolean("knowflow.drawerCollapsed", true);
      setDrawerCollapsed(true);
      if (event.detail?.restoreFocus) {
        const origin = drawerFocusOriginRef.current;
        drawerFocusOriginRef.current = null;
        restoreWorkbenchOrigin(origin);
      }
    };
    const openDrawer = (event) => {
      const wasCollapsed = drawerCollapsedRef.current;
      drawerCollapsedRef.current = false;
      if (event.detail?.focus) {
        drawerFocusOriginRef.current = currentFocusOutsideWorkbench();
        if (wasCollapsed) {
          pendingWorkbenchFocusRef.current = true;
        } else {
          window.requestAnimationFrame(() => {
            window.dispatchEvent(new CustomEvent("knowflow:react-workbench-focus"));
          });
        }
      }
      writeStoredBoolean("knowflow.drawerCollapsed", false);
      setDrawerCollapsed(false);
    };
    window.addEventListener("knowflow:react-sidebar-toggle", toggleSidebar);
    window.addEventListener("knowflow:react-sidebar-open", openSidebar);
    window.addEventListener("knowflow:react-drawer-toggle", toggleDrawer);
    window.addEventListener("knowflow:react-drawer-close", closeDrawer);
    window.addEventListener("knowflow:react-drawer-open", openDrawer);
    return () => {
      window.removeEventListener("knowflow:react-sidebar-toggle", toggleSidebar);
      window.removeEventListener("knowflow:react-sidebar-open", openSidebar);
      window.removeEventListener("knowflow:react-drawer-toggle", toggleDrawer);
      window.removeEventListener("knowflow:react-drawer-close", closeDrawer);
      window.removeEventListener("knowflow:react-drawer-open", openDrawer);
    };
  }, []);

  const globalPaletteCommands = useMemo(
    () => composerCommandSuggestions("", paletteRuntime),
    [paletteRuntime],
  );
  const handleGlobalPaletteCommand = (command) => {
    if (!command?.value) return;
    if (!palettePageActions.has(command.action)) {
      window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page: "chat" } }));
    }
    window.dispatchEvent(new CustomEvent("knowflow:react-command-palette-command", {
      detail: { command },
    }));
  };
  const handleGlobalPaletteSession = (session) => {
    const sessionId = String(session?.id || "").trim();
    if (!sessionId) return;
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page: "chat" } }));
    window.dispatchEvent(new CustomEvent("knowflow:react-session-continue", {
      detail: {
        sessionId,
        title: paletteSessionTitle(session),
        chatModelConfigId: session?.chat_model_config_id ?? null,
      },
    }));
  };

  return (
    <>
      <a className="skip-link" href="#main-stage">
        跳到主要内容
      </a>
      <AuthScreen />
      {!shellLocked ? (
        <div className="app-shell" id="app-shell">
          <Sidebar
            activePage={activePage}
            collapsed={sidebarCollapsed}
            onPageIntent={preloadPageModule}
            mobileHistoryOpen={mobileHistoryOpen}
            onMobileHistoryToggle={() => setMobileHistoryOpen((current) => !current)}
            onMobileHistoryClose={() => setMobileHistoryOpen(false)}
            onSessionIndexChange={setPaletteSessions}
          />
          <main className="main-stage" id="main-stage" tabIndex={-1}>
            <ChatPage
              active={activePage === "chat"}
              drawerCollapsed={drawerCollapsed}
            />
            <DeferredPage active={activePage === "knowledge"} visited={visitedPages.has("knowledge")} page={"knowledge"} label={"知识库"}>
              <KnowledgePage active={activePage === "knowledge"} />
            </DeferredPage>
            <DeferredPage active={activePage === "skills"} visited={visitedPages.has("skills")} page={"skills"} label={"Skills"}>
              <SkillsPage active={activePage === "skills"} />
            </DeferredPage>
            <DeferredPage active={activePage === "workspace"} visited={visitedPages.has("workspace")} page={"workspace"} label={"工作区"}>
              <WorkbenchPage
                active={activePage === "workspace"}
                run={workbenchRun}
                messageId={workbenchMessageId}
                onRunChange={setWorkbenchRun}
                onClearRun={() => {
                  setWorkbenchRun(null);
                  setWorkbenchMessageId("");
                }}
              />
            </DeferredPage>
            <DeferredPage active={activePage === "memory"} visited={visitedPages.has("memory")} page={"memory"} label={"记忆"}>
              <MemoryPage active={activePage === "memory"} />
            </DeferredPage>
            <DeferredPage active={activePage === "tools"} visited={visitedPages.has("tools")} page={"tools"} label={"工具与MCP"}>
              <ToolsPage active={activePage === "tools"} />
            </DeferredPage>
            <DeferredPage active={activePage === "settings"} visited={visitedPages.has("settings")} page={"settings"} label={"模型设置"}>
              <SettingsPage active={activePage === "settings"} />
            </DeferredPage>
            <DeferredPage active={activePage === "cli-auth"} visited={visitedPages.has("cli-auth")} page={"cli-auth"} label={"CLI授权"}>
              <CliDeviceAuthPage active={activePage === "cli-auth"} />
            </DeferredPage>
          </main>
        </div>
      ) : null}
      {!shellLocked ? (
        <CommandPalette
          commands={globalPaletteCommands}
          sessions={paletteSessions}
          disabled={paletteRuntime.switching}
          onCommand={handleGlobalPaletteCommand}
          onSessionSelect={handleGlobalPaletteSession}
        />
      ) : null}
      <Toast />
      <AgentWindowFeedback />
      <KnowFlowController />
    </>
  );
}

export default function App() {
  return <WorkbenchShell />;
}
