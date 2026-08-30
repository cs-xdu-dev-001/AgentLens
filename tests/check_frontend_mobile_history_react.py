from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def main() -> None:
    app = "frontend/react/src/App.jsx"
    sidebar = "frontend/react/src/components/Sidebar.jsx"
    css = "frontend/refinement.css"

    for needle, label in [
        ("mobileHistoryOpen", "mobile history state"),
        ("onMobileHistoryToggle", "mobile history toggle callback"),
        ("onMobileHistoryClose", "mobile history close callback"),
        ('document.body.classList.toggle("mobile-history-open"', "mobile history body lock"),
        ("window.innerWidth > 760", "desktop resize closes mobile history"),
    ]:
        require(app, needle, label)

    for needle, label in [
        ("mobileHistoryFocusable", "mobile history focusable query"),
        ("mobile-history-trigger", "mobile history entry button"),
        ('aria-controls={"session-history"}', "mobile history controlled region"),
        ('aria-expanded={Boolean(mobileHistoryOpen)}', "mobile history expanded state"),
        ("createPortal(", "mobile history portal layer"),
        ('role={mobileOpen ? "dialog" : undefined}', "mobile history dialog semantics"),
        ('aria-modal={mobileOpen ? "true" : undefined}', "mobile history modal semantics"),
        ("mobile-session-history-backdrop", "mobile history backdrop"),
        ("mobileRestoreFocusRef", "mobile history focus restoration"),
        ('event.key === "Escape"', "mobile history escape close"),
        ("onMobileClose?.()", "mobile history close actions"),
    ]:
        require(sidebar, needle, label)

    for needle, label in [
        (".mobile-history-trigger", "mobile history trigger styling"),
        (".mobile-session-history-backdrop", "mobile history backdrop styling"),
        (".chat-history-shell.mobile-history-open", "mobile history drawer styling"),
        ("width: min(360px, calc(100vw - 16px));", "bounded mobile history width"),
        ("overscroll-behavior: contain;", "contained mobile history scrolling"),
        ("@media (max-width: 760px)", "mobile history responsive breakpoint"),
    ]:
        require(css, needle, label)

    print("mobile session history drawer contract is present")


if __name__ == "__main__":
    main()
