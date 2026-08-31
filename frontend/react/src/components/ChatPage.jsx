import { ChatComposerForm } from "./ChatComposerForm.jsx";
import { ChatContextToolbar } from "./ChatContextToolbar.jsx";
import { ChatEvidenceDrawer } from "./ChatEvidenceDrawer.jsx";
import { ChatMessages } from "./ChatMessages.jsx";
import { ChatTopbar } from "./ChatTopbar.jsx";
import { ThemeToggle } from "./ThemeToggle.jsx";

export function ChatPage({ active = false, drawerCollapsed = true }) {
  return (
    <section className={active ? "page active" : "page"} id={"page-chat"}>
      <div className={"chat-layout"}>
        <section className={"chat-panel"}>
          <ThemeToggle className={"chat-theme-toggle"} />
          <ChatTopbar drawerCollapsed={drawerCollapsed} />
          <ChatContextToolbar />
          <ChatMessages />
          <ChatComposerForm active={active} />
        </section>
        <ChatEvidenceDrawer />
      </div>
    </section>
  );
}
