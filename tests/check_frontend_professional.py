from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_frontend_markup() -> str:
    files = [
        ROOT / "frontend" / "index.html",
        ROOT / "frontend" / "react" / "index.html",
        *sorted((ROOT / "frontend" / "react" / "src").rglob("*.jsx")),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files if path.is_file())


def assert_contains(text: str, token: str, label: str) -> None:
    assert token in text, f"missing {label}: {token}"


def main() -> None:
    html = read_frontend_markup()
    css = read_text("frontend/styles.css")
    react_css = read_text("frontend/react/src/styles.css")
    js = "\n".join(
        [
            *[
                path.read_text(encoding="utf-8")
                for path in sorted((ROOT / "frontend" / "react" / "src" / "controller").rglob("*.js"))
            ],
            *[
                path.read_text(encoding="utf-8")
                for path in sorted((ROOT / "frontend" / "react" / "src" / "data").rglob("*.js"))
            ],
            *[
                path.read_text(encoding="utf-8")
                for path in sorted((ROOT / "frontend" / "react" / "src" / "components").rglob("*.jsx"))
            ],
        ]
    )
    combined = "\n".join([html, css, js])
    assert css == react_css, "React Vite stylesheet should stay synced with served fallback stylesheet"

    mojibake_tokens = [
        "\u93c5",
        "\u943d",
        "\u935a",
        "\u7eee",
        "\u6d7c",
        "\u701b",
        "\u6d93",
    ]
    for token in mojibake_tokens:
        assert token not in combined, f"frontend contains mojibake token: {token}"

    required_html = [
        ("app-shell", "app shell"),
        ("sidebar", "professional sidebar"),
        ("page-chat", "chat page"),
        ("page-knowledge", "knowledge page"),
        ("page-settings", "settings page"),
        ("evidence-drawer", "evidence drawer"),
        ("chat-history-shell", "ChatGPT-style chat history shell"),
        ("sidebar-session-search", "sidebar session search"),
        ("sidebar-bottom-tools", "bottom tool settings area"),
        ("knowledge-shell", "knowledge shell"),
        ("knowledge-primary", "knowledge primary workspace"),
        ("open-kb-modal-btn", "knowledge creation modal trigger"),
        ("kb-modal", "knowledge creation modal"),
        ("chunk-modal", "chunk preview modal"),
        ("retrieval-drawer", "retrieval debug drawer"),
        ("open-retrieval-drawer-btn", "retrieval drawer trigger"),
        ('src="/src/main.jsx"', "React Vite entry script"),
        ("data-provider={provider.key}", "custom provider card"),
        ("model-provider", "editable provider identifier"),
        ("\u95ee\u7b54", "chat title"),
        ("\u4e0d\u4f7f\u7528\u77e5\u8bc6\u5e93", "optional knowledge-base selection"),
        ("\u5f15\u7528\u6765\u6e90", "reference panel"),
        ("\u6dfb\u52a0\u6587\u6863", "compact document upload action"),
    ]
    for token, label in required_html:
        assert_contains(html, token, label)
    for token in ["prompt-shelf", "prompt-chip", "Summarize knowledge", "Generate project highlights", "Compare options"]:
        assert token not in html, f"redundant prompt suggestion shelf should not render: {token}"
    for token in ['aria-label={"Close"}', '{"x"}', '{"..."}', '{"+"}', '{"UP"}']:
        assert token not in html, f"icon-only controls should render SVG icons with localized labels, not raw text: {token}"
    for token in ['id={"open-retrieval-drawer-secondary-btn"}', 'className={"panel-title compact-title document-table-title"}']:
        assert token not in html, f"duplicated knowledge workspace heading/action should not render: {token}"

    required_css = [
        ("--sidebar-width", "layout token"),
        (".sidebar.collapsed", "collapsed sidebar style"),
        (".chat-layout", "chat layout"),
        (".message.assistant", "assistant message style"),
        (".provider-grid", "provider cards"),
        (".drawer-collapsed", "drawer collapsed behavior"),
        (".chat-history-shell", "chat history sidebar style"),
        (".session-menu-button", "three-dot session menu style"),
        (".session-popover", "session action popover style"),
        (".sidebar-bottom-tools", "bottom settings tools style"),
        (".knowledge-shell", "knowledge shell style"),
        (".knowledge-primary", "knowledge primary style"),
        ("Knowledge workspace flat layout pass", "flat knowledge workspace polish marker"),
        (".knowledge-hero .hero-actions", "knowledge page action group"),
        ("grid-template-columns: minmax(220px, 1fr) auto !important;", "compact knowledge document toolbar columns"),
        ("Settings workspace flat layout pass", "flat settings workspace polish marker"),
        (".settings-header", "settings page header style"),
        (".kb-row", "knowledge list row style"),
        (".document-table", "compact document table"),
        (".modal-backdrop", "modal shell style"),
        (".modal-actions > button", "stable modal action controls"),
        (".upload-modal-body .upload-zone.upload-zone-compact", "usable upload form geometry"),
        (':root[data-theme="mono-dark"] .upload-queue-summary', "dark upload process surface"),
        (".retrieval-drawer", "retrieval drawer style"),
        (".document-steps", "document processing stepper"),
        (".document-error", "document failure reason panel"),
        (".badge.progress", "in-progress document badge"),
        (".agent-thinking-orb", "assistant thinking animation"),
        (".message-row.thinking-row .message-actions", "hide assistant actions while thinking"),
        (".attachment-pill button svg", "bounded attachment remove icon"),
        ("prefers-reduced-motion: reduce", "reduced-motion thinking state"),
        (".message.assistant pre", "assistant code block rendering"),
        ("Professional surface polish pass 3", "formal workspace polish marker"),
        ("--accent: #0f766e", "mature teal accent token"),
        ("Codex console polish pass", "Codex-inspired console polish marker"),
        ("--console-sidebar: #111315", "dark agent console sidebar token"),
        ("--accent: #10a37f", "Codex-inspired green accent token"),
        (".sidebar .nav-item.active", "Codex-style active sidebar item"),
        (".composer-shell::before", "command-input composer affordance"),
        (".message.assistant", "quiet assistant response surface"),
        ("Codex empty-state pass", "Codex-style empty state polish marker"),
        (".welcome-card", "unframed first-run welcome state"),
        (".sidebar .user-menu-button", "dark sidebar account state"),
        (".evidence-drawer .empty-state", "quiet evidence drawer empty state"),
        ("Mobile console layout pass", "mobile sidebar recovery marker"),
        ("Mobile auth layout pass", "mobile auth screen recovery marker"),
        ("body.sidebar-collapsed .app-shell", "collapsed sidebar mobile override"),
        (".sidebar-tool span:not(.nav-icon)", "mobile icon-only sidebar tools"),
        ("Accessibility polish pass", "keyboard accessibility polish marker"),
        (".skip-link", "skip link style"),
        (":focus-visible", "visible keyboard focus rings"),
        ("@media (prefers-reduced-motion: reduce)", "reduced motion support"),
        ("overflow-x: hidden", "horizontal overflow guard"),
        ("Monochrome theme pass", "black and white theme polish marker"),
        ("Monochrome contrast correction", "monochrome sidebar contrast correction marker"),
        ("Unified app theme pass", "single app-wide theme surface marker"),
        ("Dark surface correction pass", "dark mode surface correction marker"),
        ("Night mode audit pass", "dark mode second-pass audit marker"),
        ("Settings night finish pass", "dark settings finish-pass marker"),
        ("--rail-bg", "sidebar surface token"),
        ("--workspace-bg", "workspace surface token"),
        ("--control-bg", "shared control surface token"),
        ("background: var(--rail-bg)", "sidebar uses theme rail surface"),
        ("background: var(--workspace-bg)", "workspace uses theme surface"),
        ('[data-theme="mono-dark"]', "dark monochrome theme variables"),
        (".theme-toggle", "theme toggle style"),
        ("--mono-control-bg", "monochrome control token"),
        (":root[data-theme=\"mono-dark\"] #composer-menu .composer-settings-panel", "dark composer menu panel override"),
        (":root[data-theme=\"mono-dark\"] .kb-row.active", "dark knowledge active row override"),
        ("background: color-mix(in srgb, var(--panel-bg) 94%, #000)", "dark popover surface mix"),
        (":root[data-theme=\"mono-dark\"] .actions button.danger", "dark danger button override"),
        (":root[data-theme=\"mono-dark\"] .badge.ok", "dark success badge override"),
        (":root[data-theme=\"mono-dark\"] .sidebar button:focus-visible", "dark sidebar focus ring override"),
        (":root[data-theme=\"mono-dark\"] .file-drop.has-file", "dark upload file state override"),
        (":root[data-theme=\"mono-dark\"] .user-popover button:hover", "dark popover hover override"),
        (":root[data-theme=\"mono-dark\"] #page-settings .provider-card.selected", "dark provider selected override"),
        (":root[data-theme=\"mono-dark\"] #model-list .actions button.danger", "dark model danger action override"),
        (":root[data-theme=\"mono-dark\"] #theme-toggle-btn[aria-pressed=\"true\"] .nav-icon", "dark theme toggle icon override"),
        ("font-variant-numeric: tabular-nums", "tabular numeric polish"),
        ("transition-property: transform, background-color, box-shadow", "targeted interaction transitions"),
        ("@media (hover: hover)", "pointer-safe hover states"),
    ]
    for token, label in required_css:
        assert_contains(css, token, label)

    required_react_shell = [
        ('className="skip-link"', "React skip link"),
        ('href="#main-stage"', "skip link target"),
        ('id="main-stage"', "main content landmark id"),
        ("tabIndex={-1}", "focusable main landmark"),
    ]
    app = read_text("frontend/react/src/App.jsx")
    for token, label in required_react_shell:
        assert_contains(app, token, label)

    theme_toggle = read_text("frontend/react/src/components/ThemeToggle.jsx")
    react_index = read_text("frontend/react/index.html")
    navigation = read_text("frontend/react/src/data/navigation.js")
    settings_details = read_text(
        "frontend/react/src/components/ModelConfigDetails.jsx"
    )
    required_theme_toggle = [
        ("function ThemeToggle", "theme toggle component"),
        ("knowflow-theme", "persisted theme key"),
        ("document.documentElement.dataset.theme", "html theme data attribute"),
        ("document.body.dataset.theme", "body theme data attribute"),
        ('id={"theme-toggle-btn"}', "theme toggle button id"),
    ]
    for token, label in required_theme_toggle:
        assert_contains(theme_toggle, token, label)
    for token in ["knowflow-theme", "document.documentElement.dataset.theme"]:
        assert_contains(react_index, token, "pre-render theme bootstrap")
    for token in ['key: "api-docs"', 'label: "API 文档"', 'href: "/docs"']:
        assert token not in navigation, f"developer docs should not be a primary sidebar item: {token}"
    assert "模型详情" in settings_details, "settings should expose selected model details"
    assert "<details" not in settings_details, "developer resources should not render in product settings"
    for token in ["/docs", "/redoc", "/openapi.json", "/api/health", "高级入口", "接口文档"]:
        assert token not in settings_details, f"developer resource should not render in product settings: {token}"
    assert "Waiting for response" not in combined, "thinking state should not render visible waiting copy"
    assert "streaming:empty" not in css, "empty streaming pseudo-copy should not come back"

    required_js = [
        ("export const providerPresets", "provider presets"),
        ("custom: {", "custom provider preset"),
        ("normalizeProvider", "custom provider resolver"),
        ("mimo", "MiMo provider"),
        ("handleProviderSelect", "provider auto-fill"),
        ("useRag: Boolean(knowledgeBaseId)", "automatic RAG behavior"),
        ('useRag: Boolean(knowledgeBaseId)', "knowledge-base toggle drives RAG"),
        ('enableTools: true', "automatic tool routing enabled from simplified composer"),
        ('enabledTools: []', "manual tool list is no longer user-facing"),
        ('autoAgent: true', "automatic agent routing enabled from simplified composer"),
        ("handleSidebarToggle", "sidebar interaction"),
        ("handleDrawerToggle", "drawer interaction"),
        ("sessionApi.list", "React session state"),
        ("groupSessions", "session grouping"),
        ("filteredSessions", "session filtering"),
        ("handleSessionMenuToggle", "three-dot session menu"),
        ("handleSessionRename", "rename session action"),
        ("handleOpenKnowledgeBaseModal", "knowledge creation modal open action"),
        ("handleCloseKnowledgeModal", "knowledge creation modal close action"),
        ("chunkModalOpen", "React chunk modal open state"),
        ("handleCloseChunkModal", "React chunk modal close action"),
        ("handleOpenRetrievalDrawer", "retrieval drawer open action"),
        ("handleCloseRetrievalDrawer", "retrieval drawer close action"),
        ("handleLoadDocumentChunks", "React document chunk action"),
        ("documentSteps", "React document status step definitions"),
        ("isDocumentProcessing", "React document processing polling"),
        ('parse_status: "uploading"', "optimistic upload state"),
        ("document-error", "document error state"),
        ("renderMarkdown", "assistant markdown renderer"),
        ("setMessageContent", "message content rendering helper"),
        ("setMessageThinking", "assistant thinking state helper"),
        ("thinking-row", "thinking row state for action hiding"),
    ]
    for token, label in required_js:
        assert_contains(js, token, label)
    assert ".prompt-chip" not in js, "legacy prompt chip bindings should stay removed"
    for token in ["tool-mode-tabs", "manual-tool-options", "tool-option-grid", "react-tool-mode-change", "react-tool-selection-change"]:
        assert token not in combined, f"redundant manual tool UI should stay removed: {token}"

    forbidden_manual_modes = [
        "Direct Chat",
        "RAG Chat",
        "Agent Chat",
        "\u76f4\u63a5\u5bf9\u8bdd",
        "RAG \u804a\u5929",
        "\u667a\u80fd\u4f53\u804a\u5929",
        'data-page="sessions"',
        'class="document-grid"',
        'class="document-workbench"',
        'class="panel stack-form retrieval-card"',
    ]
    for token in forbidden_manual_modes:
        assert token not in html, f"manual chat mode button should not appear: {token}"


if __name__ == "__main__":
    main()

