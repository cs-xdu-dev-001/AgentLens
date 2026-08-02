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


def main() -> None:
    sidebar = read("frontend/react/src/components/Sidebar.jsx")
    require(sidebar, 'className={"sidebar-search-row"}', "compact search row")
    require(sidebar, 'className={"sidebar-refresh-button"}', "session refresh action")
    require(sidebar, 'aria-label={"刷新会话"}', "refresh action label")
    forbid(sidebar, 'className={"sidebar-heading-row"}', "redundant history heading")

    for stylesheet in (
        "frontend/refinement.css",
        "frontend/react/src/refinement.css",
    ):
        source = read(stylesheet)
        require(
            source,
            "/* KnowFlow refinement: Codex white sidebar and knowledge */",
            "white sidebar and knowledge contract",
        )
        require(source, "--sidebar-width: 252px;", "expanded sidebar width")
        require(source, "--sidebar-collapsed-width: 56px;", "collapsed sidebar width")
        require(source, "background: #fff !important;", "pure white surfaces")
        require(source, "background: #f5f5f5 !important;", "neutral hover state")
        require(source, "background: #ececec !important;", "neutral selected state")
        require(source, "border-color: #e7e7e7 !important;", "neutral separators")
        require(source, ".sidebar-search-row", "search and refresh layout")
        require(source, "#page-knowledge .knowledge-rail", "white knowledge rail")
        require(source, "#page-knowledge .knowledge-tab.active", "quiet active tab")

    print("sidebar and knowledge surfaces are white, compact, and accessible")


if __name__ == "__main__":
    main()
