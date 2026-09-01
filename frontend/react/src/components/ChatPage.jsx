import { useCallback, useEffect, useRef, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";
import { ChatComposerForm } from "./ChatComposerForm.jsx";
import { ChatContextToolbar } from "./ChatContextToolbar.jsx";
import { ChatEvidenceDrawer } from "./ChatEvidenceDrawer.jsx";
import { ChatMessages } from "./ChatMessages.jsx";
import { ChatTopbar } from "./ChatTopbar.jsx";
import { ThemeToggle } from "./ThemeToggle.jsx";

const CHAT_LAYOUT_STORAGE_KEY = "agentlens.chatWorkbenchLayout.v1";
const DEFAULT_CHAT_LAYOUT = Object.freeze({
  "chat-panel": 68,
  "evidence-panel": 32,
});

function readChatLayout() {
  if (typeof window === "undefined") return DEFAULT_CHAT_LAYOUT;
  try {
    const value = JSON.parse(window.localStorage.getItem(CHAT_LAYOUT_STORAGE_KEY) || "null");
    const chat = Number(value?.["chat-panel"]);
    const evidence = Number(value?.["evidence-panel"]);
    if (
      !Number.isFinite(chat)
      || !Number.isFinite(evidence)
      || chat < 50
      || evidence < 24
      || Math.abs(chat + evidence - 100) > 1
    ) {
      return DEFAULT_CHAT_LAYOUT;
    }
    return { "chat-panel": chat, "evidence-panel": evidence };
  } catch {
    return DEFAULT_CHAT_LAYOUT;
  }
}

function ChatPanelSurface({ active, drawerCollapsed }) {
  return (
    <section className={"chat-panel"}>
      <ThemeToggle className={"chat-theme-toggle"} />
      <ChatTopbar drawerCollapsed={drawerCollapsed} />
      <ChatContextToolbar />
      <ChatMessages />
      <ChatComposerForm active={active} />
    </section>
  );
}

export function ChatPage({ active = false, drawerCollapsed = true }) {
  const [defaultLayout] = useState(readChatLayout);
  const evidencePanelRef = useRef(null);
  const handleLayoutChanged = useCallback((layout, meta) => {
    if (!meta?.isUserInteraction || typeof window === "undefined") return;
    const chat = Number(layout?.["chat-panel"]);
    const evidence = Number(layout?.["evidence-panel"]);
    if (
      !Number.isFinite(chat)
      || !Number.isFinite(evidence)
      || Math.abs(chat + evidence - 100) > 1
    ) return;
    if (evidence <= 0.1) {
      window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close", {
        detail: { restoreFocus: true },
      }));
      return;
    }
    try {
      window.localStorage.setItem(
        CHAT_LAYOUT_STORAGE_KEY,
        JSON.stringify({ "chat-panel": chat, "evidence-panel": evidence }),
      );
    } catch {
      // Layout persistence is best effort; resizing remains available in memory.
    }
  }, []);

  useEffect(() => {
    const panel = evidencePanelRef.current;
    if (!panel) return;
    if (drawerCollapsed) panel.collapse();
    else panel.expand();
  }, [drawerCollapsed]);

  return (
    <section className={active ? "page active" : "page"} id={"page-chat"}>
      <Group
        className={"chat-layout chat-layout-resizable"}
        data-drawer-collapsed={drawerCollapsed ? "true" : "false"}
        defaultLayout={defaultLayout}
        id={"chat-workbench-layout"}
        onLayoutChanged={handleLayoutChanged}
        orientation={"horizontal"}
        resizeTargetMinimumSize={{ coarse: 24, fine: 12 }}
      >
        <Panel
          className={"chat-workbench-panel-content"}
          defaultSize={`${defaultLayout["chat-panel"]}%`}
          groupResizeBehavior={"preserve-relative-size"}
          id={"chat-panel"}
          minSize={"520px"}
        >
          <ChatPanelSurface active={active} drawerCollapsed={drawerCollapsed} />
        </Panel>
        {!drawerCollapsed ? (
          <Separator
            aria-label={"调整运行面板宽度"}
            className={"chat-workbench-resize"}
            id={"chat-workbench-resize"}
          />
        ) : null}
        <Panel
          className={"chat-workbench-panel-content"}
          collapsedSize={"0%"}
          collapsible={true}
          defaultSize={`${defaultLayout["evidence-panel"]}%`}
          disabled={drawerCollapsed}
          groupResizeBehavior={"preserve-relative-size"}
          id={"evidence-panel"}
          maxSize={"50%"}
          minSize={"320px"}
          panelRef={evidencePanelRef}
        >
          <ChatEvidenceDrawer />
        </Panel>
      </Group>
    </section>
  );
}
