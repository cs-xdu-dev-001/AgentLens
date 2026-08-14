export function ChatTopbar({ drawerCollapsed = true }) {
  const handleRefresh = () => window.dispatchEvent(new CustomEvent("knowflow:react-refresh"));
  const handleDrawerToggle = () => window.dispatchEvent(new CustomEvent("knowflow:react-drawer-toggle", {
    detail: {
      focus: drawerCollapsed,
      restoreFocus: !drawerCollapsed,
    },
  }));
  return (
    <header className={"chat-topbar"}>
      <div>
        <h1>{"问答"}</h1>
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
