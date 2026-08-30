from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"missing {label}: {needle}")


def forbid(source: str, needle: str, label: str) -> None:
    if needle in source:
        raise AssertionError(f"unexpected {label}: {needle}")


def section(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def main() -> None:
    sidebar = read("frontend/react/src/components/Sidebar.jsx")
    require(sidebar, 'className={"sidebar-search-row"}', "compact search row")
    require(
        sidebar,
        'className={loadingSessions ? "sidebar-refresh-button loading" : "sidebar-refresh-button"}',
        "session refresh action and loading state",
    )
    require(sidebar, 'aria-label={"刷新任务"}', "refresh action label")
    require(sidebar, "onClick={loadSessions}", "refresh action behavior")
    forbid(sidebar, 'className={"sidebar-heading-row"}', "redundant history heading")

    canonical = read("frontend/refinement.css")
    generated = read("frontend/react/src/refinement.css")
    if canonical != generated:
        raise AssertionError("React refinement.css is not synced from the canonical stylesheet")

    for source in (canonical, generated):
        require(
            source,
            "/* AgentLens refinement: tokenized sidebar and knowledge */",
            "tokenized sidebar and knowledge contract",
        )
        require(source, "--sidebar-width: 252px;", "expanded sidebar width")
        require(source, "--sidebar-collapsed-width: 56px;", "collapsed sidebar width")
        require(source, "background: var(--rail-bg) !important;", "themed sidebar surface")
        require(source, "background: var(--rail-hover) !important;", "themed sidebar states")
        require(source, "background: var(--panel-bg) !important;", "themed knowledge surface")
        require(source, "background: var(--control-bg-hover) !important;", "themed knowledge states")
        require(source, "border-color: var(--control-border) !important;", "themed separators")
        require(source, ".sidebar-search-row", "search and refresh layout")
        require(source, "#page-knowledge .knowledge-rail", "knowledge rail")
        require(source, "#page-knowledge .knowledge-tab.active", "quiet active tab")

        themed_surfaces = section(
            source,
            "/* AgentLens refinement: tokenized sidebar and knowledge */",
            "/* AgentLens refinement: run drawer */",
        )
        for literal in ("#fff", "#f5f5f5", "#ececec", "#e7e7e7", "#161616"):
            forbid(themed_surfaces, literal, "fixed structural color")

    print("sidebar and knowledge surfaces follow theme tokens and stay accessible")


if __name__ == "__main__":
    main()
