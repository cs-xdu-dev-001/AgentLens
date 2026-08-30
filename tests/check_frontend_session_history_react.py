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
    require("frontend/react/src/api/client.js", "sessionApi", "session API helper")
    require("frontend/react/src/components/Sidebar.jsx", "sessionApi", "sidebar owns session API calls")
    require("frontend/react/src/components/Sidebar.jsx", "loadSessions", "React session loader")
    require("frontend/react/src/components/Sidebar.jsx", "handleSessionRename", "React session rename handler")
    require("frontend/react/src/components/Sidebar.jsx", "handleSessionDelete", "React session delete handler")
    require("frontend/react/src/components/Sidebar.jsx", "SessionDeleteDialog", "focused permanent-delete confirmation")
    require("frontend/react/src/components/Sidebar.jsx", 'role={"alertdialog"}', "accessible destructive confirmation role")
    require("frontend/react/src/components/Sidebar.jsx", "deleteTargetSessionId", "explicit delete target state")
    require("frontend/react/src/components/Sidebar.jsx", "只想隐藏时，请改用归档", "archive-safe alternative copy")
    require("frontend/react/src/components/Sidebar.jsx", "handleSessionPin", "React session pin handler")
    require("frontend/react/src/components/Sidebar.jsx", "handleSessionArchive", "React session archive handler")
    require("frontend/react/src/components/Sidebar.jsx", "sessionApi.update", "React rename uses session API")
    require("frontend/react/src/components/Sidebar.jsx", "sessionApi.delete", "React delete uses session API")
    require("frontend/react/src/components/Sidebar.jsx", "sessionApi.setPinned", "React pinning uses session API")
    require("frontend/react/src/components/Sidebar.jsx", "sessionApi.setArchived", "React archiving uses session API")
    require("frontend/react/src/components/Sidebar.jsx", "session-scope-tabs", "active and archived task filter")
    require("frontend/react/src/components/Sidebar.jsx", "sessionRequestRef.current", "stale session requests cannot overwrite the current scope")
    require("frontend/react/src/components/Sidebar.jsx", "sessionScopeRef.current", "session refreshes use the latest selected scope")
    require("frontend/react/src/components/Sidebar.jsx", '"pinned", "已置顶"', "pinned session group")
    require("frontend/react/src/components/Sidebar.jsx", "editingSessionId", "inline session rename state")
    require("frontend/react/src/components/Sidebar.jsx", "renameDraft", "inline session rename draft")
    require("frontend/react/src/components/Sidebar.jsx", "session-rename-input", "inline session rename input")
    require("frontend/react/src/components/Sidebar.jsx", "handleSessionRenameKeyDown", "keyboard handling for inline rename")
    require("frontend/react/src/components/Sidebar.jsx", "setSessions", "React owns visible session state")
    require("frontend/react/src/components/Sidebar.jsx", "filteredSessions", "React owns session filtering")
    require("frontend/react/src/components/Sidebar.jsx", "knowflow:react-session-continue", "continue still delegates current chat session activation")
    require("frontend/react/src/controller/bridgeBindings.js", "knowflow:react-session-continue", "bridge module keeps session activation bridge")
    require("frontend/react/src/components/Sidebar.jsx", "knowflow:react-sessions-refresh-request", "React reloads sessions on refresh request")
    require("frontend/react/src/controller/knowflowController.js", "knowflow:react-sessions-refresh-request", "controller asks React to refresh session list")
    require("frontend/react/src/controller/sessionPersistence.js", "agentlens.activeSessionId.v1", "per-user active session persistence")
    require("frontend/react/src/controller/sessionPersistence.js", "selectSessionToRestore", "restored session selection policy")
    require("frontend/react/src/controller/knowflowController.js", "restoreActiveSession", "authenticated workspace restore")
    require("frontend/react/src/controller/knowflowController.js", 'request("/api/sessions")', "restore validates sessions for current user")
    require("frontend/react/src/controller/chatFlow.js", "rememberActiveSession(nextSessionId)", "opened sessions are persisted")
    require("frontend/react/src/controller/chatFlow.js", 'rememberActiveSession("")', "explicit new chat is persisted")
    require("frontend/react/src/controller/chatFlow.js", "ownerUserId !== String(state.currentUser?.id", "session response is bound to its authenticated owner")
    require("frontend/react/src/controller/chatFlow.js", "abortChatActivity", "logout aborts local chat activity")
    require("frontend/react/src/components/Sidebar.jsx", "sessionLoadSequenceRef", "stale session lists cannot cross account boundaries")
    require("frontend/react/src/controller/knowflowController.js", "resolveChatModelConfigId", "restored model selection is validated")

    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:react-session-search-change", "legacy session search bridge")
    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:react-session-rename", "legacy session rename bridge")
    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:react-session-delete", "legacy session delete bridge")
    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:react-history-refresh", "legacy history refresh bridge")
    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:legacy-sessions-updated", "legacy session list data event")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-session-search-change", "legacy session search listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-session-rename", "legacy session rename listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-session-delete", "legacy session delete listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-history-refresh", "legacy history refresh listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-sessions-updated", "legacy session list broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "function filterSessions", "legacy DOM session filter")
    forbid("frontend/react/src/controller/knowflowController.js", "function renderHistorySession", "legacy DOM session row renderer")
    forbid("frontend/react/src/controller/knowflowController.js", "function toggleSessionMenu", "legacy DOM session menu")
    forbid("frontend/react/src/controller/knowflowController.js", "function renameSession", "legacy controller rename action")
    forbid("frontend/react/src/controller/knowflowController.js", "function deleteSession", "legacy controller delete action")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactSessionListEnabled", "dead session-list ownership flag")
    forbid("frontend/react/src/controller/knowflowController.js", "window.deleteSession", "legacy global delete session export")
    forbid("frontend/react/src/controller/knowflowController.js", "window.toggleSessionMenu", "legacy global session menu export")
    forbid("frontend/react/src/controller/knowflowController.js", "window.renameSession", "legacy global rename session export")
    forbid("frontend/react/src/components/Sidebar.jsx", "window.prompt", "browser prompt session rename")
    forbid("frontend/react/src/components/Sidebar.jsx", "window.confirm", "native browser delete confirmation")

    print("session history refresh, search, rename, and delete are owned by React")


if __name__ == "__main__":
    main()
