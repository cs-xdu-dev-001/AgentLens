from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    for stylesheet in (
        "frontend/refinement.css",
        "frontend/react/src/refinement.css",
    ):
        source = read(stylesheet)
        require(
            source,
            "/* KnowFlow refinement: aligned empty composer */",
            "empty composer alignment contract",
        )
        require(
            source,
            "/* KnowFlow refinement: Codex composer surface */",
            "Codex composer contract",
        )
        require(
            source,
            "--kf-empty-chat-column: min(860px, calc(100% - 32px));",
            "shared empty-state column",
        )
        require(
            source,
            "background: #fff !important;",
            "pure white chat surface",
        )
        require(
            source,
            "grid-template-rows: minmax(50px, auto) 36px !important;",
            "large input surface",
        )
        require(
            source,
            "justify-self: end;",
            "right aligned model picker",
        )
        require(
            source,
            "--kf-empty-chat-column: calc(100vw - 24px);",
            "viewport bounded mobile composer",
        )
        require(
            source,
            "transform: none !important;",
            "welcome title transform reset",
        )
        require(
            source,
            "inset: 64px 0 144px !important;",
            "welcome content centering area",
        )
        require(
            source,
            "bottom: 18px !important;",
            "composer bottom anchor",
        )
        require(
            source,
            "border: 0 !important;",
            "quiet model trigger",
        )
        require(
            source,
            "outline: 2px solid var(--kf-focus-ring) !important;",
            "keyboard focus visibility",
        )
    print("empty welcome and composer share one calm visual axis")


if __name__ == "__main__":
    main()
