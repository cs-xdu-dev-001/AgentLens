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
            "--kf-empty-chat-column: min(860px, calc(100% - 32px));",
            "shared empty-state column",
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
    print("empty welcome and composer share one calm visual axis")


if __name__ == "__main__":
    main()
