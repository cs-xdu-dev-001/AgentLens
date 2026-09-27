from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(source: str, needle: str, label: str) -> None:
    if needle not in source:
        raise AssertionError(f"missing {label}: {needle}")


def main() -> None:
    messages = read("frontend/react/src/components/ChatMessages.jsx")
    for needle, label in (
        ("WELCOME_ACTIONS", "welcome action model"),
        ('label: "梳理项目结构"', "project overview action"),
        ('label: "检查当前改动"', "workspace review action"),
        ('label: "运行测试并修复"', "test action"),
        ('label: "继续最近的工作"', "continuation action"),
        ('detail: { focus: true, question: prompt }', "composer handoff"),
        ('aria-label={"常用起始任务"}', "action navigation label"),
    ):
        if needle not in messages:
            raise AssertionError(f"missing {label}: {needle}")

    for stylesheet in (
        "frontend/refinement.css",
        "frontend/react/src/refinement.css",
    ):
        source = read(stylesheet)
        require(
            source,
            "/* AgentLens refinement: aligned empty composer */",
            "empty composer alignment contract",
        )
        require(
            source,
            "/* AgentLens refinement: Codex composer surface */",
            "Codex composer contract",
        )
        require(
            source,
            "background: var(--workspace-bg) !important;",
            "themed chat surface",
        )
        require(
            source,
            "background: var(--control-bg) !important;",
            "themed composer surface",
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
            "border: 0 !important;",
            "quiet model trigger",
        )
        require(
            source,
            "outline: 2px solid var(--kf-focus-ring) !important;",
            "keyboard focus visibility",
        )
        require(
            source,
            "/* Actionable project start surface. */",
            "actionable start surface contract",
        )
        require(
            source,
            "grid-template-columns: repeat(2, minmax(0, 1fr));",
            "desktop starter grid",
        )
        require(
            source,
            "animation: welcome-surface-enter 220ms",
            "welcome entrance motion",
        )
        require(
            source,
            "@media (prefers-reduced-motion: reduce)",
            "reduced motion contract",
        )

    # chat-polish.css owns the final layout. Legacy absolute offsets above are
    # not the runtime contract; browser geometry verifies the actual cascade.
    polish = read("frontend/react/src/chat-polish.css")
    desktop = polish.split("@media (min-width: 761px)", 1)[1].split(
        "@media (max-width: 760px)", 1
    )[0]
    for needle, label in (
        ("display: flex !important;", "flow-based empty panel"),
        ("position: static !important;", "in-flow launcher"),
        ("flex: 0 1 auto !important;", "shrinkable launcher"),
        ("overflow-y: auto !important;", "short-screen launcher scrolling"),
        ("width: min(720px, 100%) !important;", "desktop welcome content axis"),
        ("width: min(720px, calc(100% - 48px)) !important;", "matching composer axis"),
        ("margin: 0 auto auto !important;", "content-sized group centering"),
        ("transform: none !important;", "no absolute composer translation"),
    ):
        require(desktop, needle, label)
    print("empty welcome and composer share one calm visual axis")


if __name__ == "__main__":
    main()
