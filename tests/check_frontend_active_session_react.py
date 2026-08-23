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
    require("frontend/react/src/components/Sidebar.jsx", "knowflow:react-active-session-updated", "React sidebar active-session event")
    require("frontend/react/src/components/Sidebar.jsx", "title: sessionTitle(currentSession)", "sidebar publishes the current session title")
    require("frontend/react/src/components/ChatContextToolbar.jsx", "knowflow:react-active-session-updated", "React toolbar active-session event")
    require("frontend/react/src/components/ChatTopbar.jsx", "knowflow:react-active-session-updated", "chat heading follows active-session metadata")
    require("frontend/react/src/components/ChatTopbar.jsx", "knowflow:react-session-switch-state", "chat heading exposes session switching")
    require("frontend/react/src/components/ChatTopbar.jsx", "chat-session-heading", "chat heading renders the current task identity")
    require("frontend/react/src/controller/knowflowController.js", "knowflow:react-active-session-updated", "controller active-session React event")
    require("frontend/react/src/controller/knowflowController.js", "currentSessionTitle", "controller includes the session title")
    require("frontend/react/src/controller/chatFlow.js", "sessionTitleFromQuestion", "first task supplies an immediate session title")
    require("frontend/react/src/controller/chatFlow.js", "safeAgentText(question, 80)", "first-task title is redacted before rendering")
    require("frontend/react/src/components/ChatTopbar.jsx", "safeAgentText(value, 160)", "topbar title is redacted before rendering")
    require("frontend/react/src/components/Sidebar.jsx", "safeAgentText(session.title, 160)", "sidebar title is redacted before rendering")

    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:legacy-active-session-updated", "legacy active-session sidebar listener")
    forbid("frontend/react/src/components/ChatContextToolbar.jsx", "knowflow:legacy-active-session-updated", "legacy active-session toolbar listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-active-session-updated", "legacy active-session broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactActiveSessionEnabled", "dead active-session ownership flag")

    print("active session state is delivered through the React event channel")


if __name__ == "__main__":
    main()
