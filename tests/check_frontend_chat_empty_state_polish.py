from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(f"missing {label} in {path}: {needle}")


def main() -> None:
    require(
        "frontend/react/src/controller/chatFlow.js",
        'window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close"));',
        "new chat drawer close",
    )
    for stylesheet in ("frontend/styles.css", "frontend/react/src/styles.css"):
        require(
            stylesheet,
            "/* Chat empty state final polish. */",
            "empty state contract",
        )
        require(
            stylesheet,
            "grid-template-rows: minmax(64px, 0.76fr) auto 26px auto minmax(88px, 1.24fr)",
            "compact vertical composition",
        )
        require(
            stylesheet,
            "#page-chat.chat-empty .chat-topbar-actions",
            "empty topbar actions",
        )
        require(stylesheet, "display: none !important", "empty action hiding")
        require(stylesheet, "max-width: 880px !important", "composer width")
        require(stylesheet, "min-height: 66px !important", "composer height")
        require(
            stylesheet,
            ":focus:not(:focus-visible)",
            "mouse focus suppression",
        )
        require(stylesheet, "@media (max-width: 520px)", "mobile contract")
        require(
            stylesheet,
            "grid-template-columns: 14px minmax(0, 1fr) 14px",
            "mobile safe area",
        )
    print("chat empty state is compact, accessible, and drawer-safe")


if __name__ == "__main__":
    main()
