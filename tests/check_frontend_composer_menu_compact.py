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
    component = read("frontend/react/src/components/ChatComposerForm.jsx")
    require(component, 'className={"menu-item-label"}>{"上传文件"}', "compact upload action")
    require(component, 'className={"menu-item-current"}', "inline knowledge selection")
    require(component, 'className={"menu-select-chevron"}', "knowledge selection affordance")
    forbid(component, 'className={"menu-section-title"}', "nested knowledge heading")
    forbid(component, 'className={"composer-menu-summary"}', "redundant knowledge summary")

    for stylesheet in (
        "frontend/refinement.css",
        "frontend/react/src/refinement.css",
    ):
        source = read(stylesheet)
        require(
            source,
            "/* AgentLens refinement: compact composer menu */",
            "compact composer menu contract",
        )
        require(
            source,
            "width: min(288px, calc(100vw - 24px)) !important;",
            "viewport-safe compact width",
        )
        require(
            source,
            "grid-template-columns: 32px auto minmax(0, 1fr) 16px;",
            "single-row knowledge selection",
        )
        require(
            source,
            "transform: none !important;",
            "stable plus icon",
        )
        require(
            source,
            "box-shadow: 0 14px 36px rgba(0, 0, 0, 0.12) !important;",
            "quiet popover elevation",
        )

    print("composer menu is compact, flat, and Codex-aligned")


if __name__ == "__main__":
    main()
