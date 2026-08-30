from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def forbid(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle in text:
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def main() -> None:
    require("frontend/react/src/App.jsx", "sidebarCollapsed", "React shell sidebar collapse state")
    require("frontend/react/src/App.jsx", "drawerCollapsed", "React shell drawer collapse state")
    require("frontend/react/src/App.jsx", "knowflow:react-sidebar-toggle", "React shell receives sidebar toggle")
    require("frontend/react/src/App.jsx", "knowflow:react-drawer-toggle", "React shell receives drawer toggle")
    require("frontend/react/src/App.jsx", "knowflow:react-drawer-close", "React shell receives drawer close")
    require("frontend/react/src/App.jsx", "handleWorkbenchShortcut", "React shell owns the run workbench shortcut")
    require("frontend/react/src/App.jsx", 'event.altKey && ["t", "e", "g"].includes(key)', "Web workbench shortcuts")
    require("frontend/react/src/App.jsx", 'event.ctrlKey && ["t", "e", "g"].includes(key)', "desktop workbench shortcuts")
    require("frontend/react/src/App.jsx", 'key === "g" ? "artifacts" : "trace"', "shortcut-specific workbench tab")
    require("frontend/react/src/App.jsx", "dataset.artifactCount", "file changes shortcut availability guard")
    require("frontend/react/src/App.jsx", "knowflow:react-workbench-focus", "workbench shortcut requests active tab focus")
    require("frontend/react/src/App.jsx", "pendingWorkbenchFocusRef", "workbench focus waits for the drawer state to render")
    require("frontend/react/src/App.jsx", 'setActivePage("chat")', "workbench shortcut returns to chat")
    require("frontend/react/src/App.jsx", "if (event.repeat) return", "workbench shortcut ignores key repeat")
    require("frontend/react/src/App.jsx", "hasWorkbenchContent", "workbench shortcut avoids an empty panel")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", "handleWorkbenchFocus", "drawer receives workbench focus requests")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", "handleDrawerKeyDown", "drawer handles keyboard return to chat")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", 'detail: { restoreFocus: true }', "drawer close requests origin focus restoration")
    require("frontend/react/src/App.jsx", "drawerFocusOriginRef", "React shell remembers the drawer opener")
    require("frontend/react/src/App.jsx", "currentFocusOutsideWorkbench", "React shell captures focus outside the workbench")
    require("frontend/react/src/App.jsx", "restoreWorkbenchOrigin", "React shell restores the original keyboard target")
    require("frontend/react/src/App.jsx", "knowflow:react-composer-focus", "missing drawer origins fall back to the composer")
    require("frontend/react/src/components/ChatComposerForm.jsx", "handleComposerFocus", "composer receives focus restoration")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", "data-has-run={hasWorkbenchContent}", "drawer publishes whether a run is available")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", "data-artifact-count={artifacts.length}", "drawer publishes whether file changes are available")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", "knowflow:react-workbench-select-tab", "drawer supports direct shortcut tab selection")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", 'aria-keyshortcuts={"Alt+E 1"}', "trace tab advertises its global shortcut")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", 'aria-keyshortcuts={"Alt+G 4"}', "artifact tab advertises its global shortcut")
    require("frontend/react/src/components/ChatEvidenceDrawer.jsx", 'querySelector(\'[role="tab"][aria-selected="true"]\')', "drawer focuses the selected workbench tab")
    require("frontend/react/src/components/ChatTopbar.jsx", 'aria-keyshortcuts={"Alt+T"}', "run button advertises its Web shortcut")
    require("frontend/react/src/components/ChatTopbar.jsx", 'aria-controls={"evidence-drawer"}', "run button names its controlled panel")
    require("frontend/react/src/components/ChatTopbar.jsx", "aria-expanded={!drawerCollapsed}", "run button exposes the drawer state")
    require("frontend/react/src/components/ChatTopbar.jsx", "focus: drawerCollapsed", "run button transfers keyboard focus when opening")
    require("frontend/react/src/components/ChatPage.jsx", "drawerCollapsed={drawerCollapsed}", "chat shell passes the drawer state to its topbar")
    require("frontend/react/src/App.jsx", "document.body.classList.toggle(\"sidebar-collapsed\"", "React shell syncs sidebar body class")
    require("frontend/react/src/App.jsx", "document.body.classList.toggle(\"drawer-collapsed\"", "React shell syncs drawer body class")
    require("frontend/react/src/App.jsx", "knowflow.sidebarCollapsed", "React shell persists sidebar layout")
    require("frontend/react/src/App.jsx", "knowflow.drawerCollapsed", "React shell persists drawer layout")
    require("frontend/react/src/App.jsx", "activePage={activePage}", "Sidebar receives active page prop")
    require("frontend/react/src/App.jsx", "collapsed={sidebarCollapsed}", "Sidebar receives collapsed prop")
    require("frontend/react/src/App.jsx", "onPageIntent={preloadPageModule}", "Sidebar receives page prefetch intent")
    require("frontend/react/src/components/Sidebar.jsx", "collapsed = false", "Sidebar collapsed prop default")
    require("frontend/react/src/components/Sidebar.jsx", "sidebarClassName", "Sidebar renders collapsed class from React")
    require("frontend/react/src/components/Sidebar.jsx", "sidebarToggleLabel", "Sidebar renders toggle label from React")
    require("frontend/react/src/components/Sidebar.jsx", "function SidebarToolIcon", "Sidebar renders real tool icons")
    require("frontend/react/src/components/Sidebar.jsx", "<svg", "Sidebar tool icons are SVG")
    require("frontend/styles.css", ".sidebar-tool .nav-icon svg", "Sidebar SVG icon style")

    css = read("frontend/styles.css")
    desktop_shell_index = css.rfind("/* ChatGPT-aligned shell pass")
    mobile_guard_index = css.rfind("/* Final mobile shell guard")
    if desktop_shell_index < 0:
        raise AssertionError("missing late desktop shell layout marker")
    if mobile_guard_index <= desktop_shell_index:
        raise AssertionError("final mobile shell guard must come after late desktop shell overrides")
    mobile_guard = css[mobile_guard_index:]
    for needle, label in [
        ("grid-template-columns: minmax(0, 1fr) !important;", "single-column mobile app shell"),
        ("grid-template-rows: 64px minmax(0, 1fr) !important;", "viewport-filling mobile shell rows"),
        ("height: 100dvh;", "mobile shell viewport height"),
        ("width: 100% !important;", "full-width mobile sidebar"),
        ("#page-chat .chat-panel", "mobile chat panel height override"),
    ]:
        if needle not in mobile_guard:
            raise AssertionError(f"missing {label} after desktop shell overrides: {needle}")

    refinement = read("frontend/refinement.css")
    responsive_marker = "/* AgentLens refinement: responsive */"
    responsive_index = refinement.find(responsive_marker)
    if responsive_index < 0:
        raise AssertionError("missing AgentLens responsive refinement marker")
    responsive = refinement[responsive_index:]
    for needle, label in [
        (".evidence-drawer {\n    position: absolute;", "floating run workbench below 1180px"),
        ("body.drawer-collapsed .evidence-drawer {\n    display: grid;", "animated hidden workbench state"),
        ("visibility: hidden;", "collapsed workbench removed from interaction"),
        ("@media (max-width: 1180px), (pointer: coarse)", "touch-aware control sizing"),
        (".evidence-drawer button,", "44px run workbench targets"),
        ("#page-chat .message-actions button", "responsive message action targets"),
        ("left: 8px;", "full-width mobile run workbench"),
    ]:
        if needle not in responsive:
            raise AssertionError(f"missing {label} in responsive refinement: {needle}")

    final_mobile_index = refinement.rfind("@media (max-width: 760px)")
    if final_mobile_index < responsive_index:
        raise AssertionError("missing final mobile interaction pass")
    final_mobile = refinement[final_mobile_index:]
    for needle, label in [
        ("grid-template-columns: 44px minmax(0, 1fr) 44px minmax(72px, auto) 44px !important;", "mobile composer touch columns"),
        ("body.sidebar-collapsed .sidebar .user-menu-button {\n    width: 44px !important;", "mobile sidebar touch controls"),
        ("#chat-form.composer .composer-input-stack textarea {\n    min-height: 44px !important;", "mobile composer input target"),
        ("#page-chat .chat-topbar #inspector-toggle", "mobile workbench toggle target"),
    ]:
        if needle not in final_mobile:
            raise AssertionError(f"missing {label} in final mobile pass: {needle}")

    for needle, label in [
        ('icon: "KB"', "letter knowledge icon"),
        ('icon: "SET"', "letter settings icon"),
        ('icon: "API"', "letter API icon"),
    ]:
        forbid("frontend/react/src/data/navigation.js", needle, label)

    for needle, label in [
        ('collapsed ? ">" : "<"', "raw sidebar toggle text"),
        ('{"+"}', "raw new-chat plus text"),
    ]:
        forbid("frontend/react/src/components/Sidebar.jsx", needle, label)

    for needle, label in [
        ("function toggleSidebar", "legacy sidebar toggle function"),
        ("function applySidebarState", "legacy sidebar DOM state function"),
        ("function toggleDrawer", "legacy drawer toggle function"),
        ("function initLayout", "legacy layout bootstrap function"),
        ("sidebar.classList.toggle(\"collapsed\"", "legacy sidebar class toggle"),
        ("document.body.classList.toggle(\"sidebar-collapsed\"", "legacy sidebar body class toggle"),
        ("document.body.classList.toggle(\"drawer-collapsed\"", "legacy drawer body class toggle"),
        ("#sidebar-toggle", "legacy sidebar toggle DOM lookup"),
    ]:
        forbid("frontend/react/src/controller/knowflowController.js", needle, label)

    print("shell layout collapse state is owned by React")


if __name__ == "__main__":
    main()
