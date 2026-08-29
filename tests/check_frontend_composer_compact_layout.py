from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(f"missing {label} in {path}: {needle}")


def main() -> None:
    for stylesheet in ("frontend/styles.css", "frontend/react/src/styles.css"):
        require(
            stylesheet,
            "/* Compact composer chrome. */",
            "compact composer contract",
        )
        require(
            stylesheet,
            "grid-template-rows: minmax(24px, auto) 36px",
            "two-row layout",
        )
        require(
            stylesheet,
            "display: contents !important",
            "input stack grid lift",
        )
        require(stylesheet, "grid-row: 2 !important", "toolbar row")
        require(stylesheet, "width: 36px !important", "compact action size")
        require(
            stylesheet,
            "border-radius: 18px !important",
            "compact shell radius",
        )
        require(
            stylesheet,
            ":has(.selected-skill-pill)",
            "selected Skill expansion",
        )
        require(stylesheet, "@media (max-width: 520px)", "mobile contract")
    for stylesheet in ("frontend/refinement.css", "frontend/react/src/refinement.css"):
        require(
            stylesheet,
            "/* AgentLens refinement: agent client parity */",
            "agent client refinement contract",
        )
        require(
            stylesheet,
            "grid-template-columns: 36px minmax(0, 1fr) auto auto 36px",
            "non-overlapping composer columns",
        )
        require(stylesheet, ".composer-permission-picker", "permission picker column")
        require(stylesheet, "grid-column: 3 !important", "permission picker placement")
        require(stylesheet, ".composer-model-picker", "model picker column")
        require(stylesheet, "grid-column: 4 !important", "model picker placement")
        require(stylesheet, "grid-column: 5 !important", "send button placement")
        require(stylesheet, ".sidebar #runtime-box", "mobile runtime compaction")
    require(
        "frontend/react/src/components/ChatComposerForm.jsx",
        "输入任务，/选择命令或Skill，@引用文件",
        "compact composer prompt",
    )
    print("composer chrome is compact and aligned")


if __name__ == "__main__":
    main()
