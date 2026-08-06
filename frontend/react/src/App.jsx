import { useEffect, useState } from "react";
import { AuthScreen } from "./components/AuthScreen.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import { ChatPage } from "./components/ChatPage.jsx";
import { KnowledgePage } from "./components/KnowledgePage.jsx";
import { SkillsPage } from "./components/SkillsPage.jsx";
import { MemoryPage } from "./components/MemoryPage.jsx";
import { ToolsPage } from "./components/ToolsPage.jsx";
import { SettingsPage } from "./components/SettingsPage.jsx";
import { WorkbenchPage } from "./components/WorkbenchPage.jsx";
import { CliDeviceAuthPage } from "./components/CliDeviceAuthPage.jsx";
import { Toast } from "./components/Toast.jsx";
import { KnowFlowController } from "./components/KnowFlowController.jsx";
import { useAuth } from "./auth/AuthProvider.jsx";

const pageKeys = new Set(["chat", "knowledge", "skills", "workspace", "memory", "tools", "settings", "cli-auth"]);
const SIDEBAR_LAYOUT_VERSION = "20260522-chatgpt-sidebar";

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

function WorkbenchShell() {
  const { authenticated, loading } = useAuth();
  const [activePage, setActivePage] = useState(readInitialPage);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readInitialSidebarCollapsed);
  const [drawerCollapsed, setDrawerCollapsed] = useState(() => readStoredBoolean("knowflow.drawerCollapsed", true));
  const shellLocked = loading || !authenticated;

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
    document.body.classList.toggle("sidebar-collapsed", sidebarCollapsed);
    return () => document.body.classList.remove("sidebar-collapsed");
  }, [sidebarCollapsed]);

  useEffect(() => {
    document.body.classList.toggle("drawer-collapsed", drawerCollapsed);
    return () => document.body.classList.remove("drawer-collapsed");
  }, [drawerCollapsed]);

  useEffect(() => {
    const toggleSidebar = () => {
      setSidebarCollapsed((current) => {
        const next = !current;
        writeStoredBoolean("knowflow.sidebarCollapsed", next);
        return next;
      });
    };
    const toggleDrawer = () => {
      setDrawerCollapsed((current) => {
        const next = !current;
        writeStoredBoolean("knowflow.drawerCollapsed", next);
        return next;
      });
    };
    const closeDrawer = () => {
      writeStoredBoolean("knowflow.drawerCollapsed", true);
      setDrawerCollapsed(true);
    };
    const openDrawer = () => {
      writeStoredBoolean("knowflow.drawerCollapsed", false);
      setDrawerCollapsed(false);
    };
    window.addEventListener("knowflow:react-sidebar-toggle", toggleSidebar);
    window.addEventListener("knowflow:react-drawer-toggle", toggleDrawer);
    window.addEventListener("knowflow:react-drawer-close", closeDrawer);
    window.addEventListener("knowflow:react-drawer-open", openDrawer);
    return () => {
      window.removeEventListener("knowflow:react-sidebar-toggle", toggleSidebar);
      window.removeEventListener("knowflow:react-drawer-toggle", toggleDrawer);
      window.removeEventListener("knowflow:react-drawer-close", closeDrawer);
      window.removeEventListener("knowflow:react-drawer-open", openDrawer);
    };
  }, []);

  return (
    <>
      <a className="skip-link" href="#main-stage">
        跳到主要内容
      </a>
      <AuthScreen />
      {!shellLocked ? (
        <div className="app-shell" id="app-shell">
          <Sidebar activePage={activePage} collapsed={sidebarCollapsed} />
          <main className="main-stage" id="main-stage" tabIndex={-1}>
            <ChatPage active={activePage === "chat"} />
            <KnowledgePage active={activePage === "knowledge"} />
            <SkillsPage active={activePage === "skills"} />
            <WorkbenchPage active={activePage === "workspace"} />
            <MemoryPage active={activePage === "memory"} />
            <ToolsPage active={activePage === "tools"} />
            <SettingsPage active={activePage === "settings"} />
            <CliDeviceAuthPage active={activePage === "cli-auth"} />
          </main>
        </div>
      ) : null}
      <Toast />
      <KnowFlowController />
    </>
  );
}

export default function App() {
  return <WorkbenchShell />;
}
