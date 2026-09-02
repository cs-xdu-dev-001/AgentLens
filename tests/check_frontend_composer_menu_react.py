from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def forbid(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle in text:
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def main() -> None:
    require("frontend/react/src/components/ChatComposerForm.jsx", "menuOpen", "React composer menu open state")
    require("frontend/react/src/components/ChatComposerForm.jsx", "setMenuOpen", "React composer menu setter")
    require("frontend/react/src/components/ChatComposerForm.jsx", "composerMenuClassName", "React composer menu class")
    require("frontend/react/src/components/ChatComposerForm.jsx", "composerPlusClassName", "React composer plus class")
    require("frontend/react/src/components/ChatComposerForm.jsx", "knowflow:react-composer-menu-close", "React composer listens for close command")
    require("frontend/react/src/components/ChatComposerForm.jsx", 'event.key === "Escape" && menuOpen', "Escape closes the open composer menu")
    require("frontend/react/src/components/ChatComposerForm.jsx", "setMenuOpen(false)", "composer menu Escape close action")
    require("frontend/react/src/controller/knowflowController.js", "requestComposerMenuClose", "controller asks React to close composer menu")

    for needle, label in [
        ("function toggleComposerMenu", "legacy composer menu toggle function"),
        ("toggleComposerMenu(", "legacy composer menu toggle calls"),
        ("#composer-menu", "legacy composer menu DOM lookup"),
        ("#composer-plus-btn", "legacy composer plus DOM lookup"),
        ("menu.classList.toggle(\"open\"", "legacy composer menu class toggle"),
        ("button.classList.toggle(\"active\"", "legacy composer plus class toggle"),
    ]:
        forbid("frontend/react/src/controller/knowflowController.js", needle, label)

    print("composer menu open state is owned by React")


if __name__ == "__main__":
    main()
