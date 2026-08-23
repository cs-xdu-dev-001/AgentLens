import { useEffect, useState } from "react";
import { safeAgentText } from "../controller/agentEvents.js";

function cleanSessionTitle(value) {
  return safeAgentText(value, 160);
}

export function ChatTopbar({ drawerCollapsed = true }) {
  const [sessionTitle, setSessionTitle] = useState("");
  const [pendingTitle, setPendingTitle] = useState("");
  const [switching, setSwitching] = useState(false);

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

  const handleRefresh = () => window.dispatchEvent(new CustomEvent("knowflow:react-refresh"));
  const handleDrawerToggle = () => window.dispatchEvent(new CustomEvent("knowflow:react-drawer-toggle", {
    detail: {
      focus: drawerCollapsed,
      restoreFocus: !drawerCollapsed,
    },
  }));
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
          id={"inspector-toggle"}
          type={"button"}
          aria-controls={"evidence-drawer"}
          aria-expanded={!drawerCollapsed}
          aria-keyshortcuts={"Alt+T"}
          title={"运行详情（Alt+T）"}
          onClick={handleDrawerToggle}
        >
          {"运行"}
        </button>
        <button id={"refresh-btn"} type={"button"} onClick={handleRefresh}>{"刷新"}</button>
      </div>
    </header>
  );
}
