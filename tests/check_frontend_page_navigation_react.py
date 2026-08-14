from pathlib import Path
import re


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


def require_pattern(path: str, pattern: str, label: str) -> None:
    text = read(path)
    if not re.search(pattern, text, re.DOTALL):
        raise AssertionError(f"missing {label} in {path}: {pattern}")


def main() -> None:
    require("frontend/react/src/App.jsx", "activePage", "React shell active page state")
    require("frontend/react/src/App.jsx", "setActivePage", "React shell page setter")
    require("frontend/react/src/App.jsx", "knowflow:react-page-change", "React shell receives page navigation")
    require("frontend/react/src/App.jsx", "knowflow:react-page-activated", "React shell receives controller page activation")
    require("frontend/react/src/App.jsx", "<Sidebar activePage={activePage}", "Sidebar receives active page prop")
    require_pattern(
        "frontend/react/src/App.jsx",
        r'<ChatPage\b[^>]*\bactive=\{activePage === "chat"\}',
        "Chat page active prop",
    )
    require("frontend/react/src/App.jsx", "<KnowledgePage active={activePage === \"knowledge\"}", "Knowledge page active prop")
    require("frontend/react/src/App.jsx", "<SkillsPage active={activePage === \"skills\"}", "Skills page active prop")
    require("frontend/react/src/App.jsx", "<ToolsPage active={activePage === \"tools\"}", "Tools page active prop")
    require("frontend/react/src/App.jsx", "<SettingsPage active={activePage === \"settings\"}", "Settings page active prop")
    require("frontend/react/src/data/navigation.js", 'label: "工具与MCP"', "Tools and MCP navigation entry")
    require("frontend/react/src/data/navigation.js", 'label: "Skills"', "Skills navigation entry")
    require("frontend/react/src/components/Sidebar.jsx", "activePage = \"chat\"", "Sidebar default active page")
    require("frontend/react/src/components/Sidebar.jsx", "activePage === tool.page", "Sidebar active tool class")
    require("frontend/react/src/components/ChatPage.jsx", "active = false", "ChatPage active prop default")
    require("frontend/react/src/components/KnowledgePage.jsx", "active = false", "KnowledgePage active prop default")
    require("frontend/react/src/components/SkillsPage.jsx", "active = false", "SkillsPage active prop default")
    require("frontend/react/src/components/ToolsPage.jsx", "active = false", "ToolsPage active prop default")
    require("frontend/react/src/components/SettingsPage.jsx", "active = false", "SettingsPage active prop default")
    require("frontend/react/src/controller/knowflowController.js", "knowflow:react-page-activated", "controller announces page activation")

    forbid("frontend/react/src/controller/knowflowController.js", '$all(".nav-item, .sidebar-tool")', "legacy nav active DOM toggling")
    forbid("frontend/react/src/controller/knowflowController.js", '$all(".page")', "legacy page active DOM toggling")
    forbid("frontend/react/src/controller/knowflowController.js", "button.dataset.page === page", "legacy nav dataset comparison")
    forbid("frontend/react/src/controller/knowflowController.js", "section.id === `page-${page}`", "legacy page id comparison")

    print("page navigation active state is owned by React")


if __name__ == "__main__":
    main()
