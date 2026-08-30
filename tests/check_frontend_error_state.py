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
    require("frontend/react/src/api/errors.js", 'BACKEND_UNAVAILABLE_MESSAGE = "\u670d\u52a1\u6682\u4e0d\u53ef\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"', "clear Chinese backend unavailable message")
    require("frontend/react/src/api/errors.js", "export function normalizeErrorMessage", "shared error normalizer")
    require("frontend/react/src/api/errors.js", "export function isBackendUnavailableError", "backend unavailable classifier")
    require("frontend/react/src/api/client.js", "BACKEND_UNAVAILABLE_MESSAGE", "API client uses shared backend message")
    require("frontend/react/src/api/client.js", "normalizeErrorMessage", "API client normalizes server errors")
    forbid("frontend/react/src/api/client.js", "Internal Server Error", "raw internal server error leak")
    forbid("frontend/react/src/api/client.js", "鍚", "mojibake backend error text")

    require("frontend/react/src/components/errorFeedback.js", "export function notifyToast", "shared toast dispatcher")
    require("frontend/react/src/components/errorFeedback.js", "export function notifyError", "shared error dispatcher")
    require("frontend/react/src/components/errorFeedback.js", "normalizeErrorMessage", "shared UI error normalization")
    require("frontend/react/src/components/Toast.jsx", "tone", "toast tone state")
    require("frontend/react/src/components/Toast.jsx", "toast error", "error toast class")
    require("frontend/styles.css", ".toast.error", "error toast styling")

    for component in [
        "KnowledgeDocuments.jsx",
        "KnowledgeModals.jsx",
        "KnowledgeRail.jsx",
        "KnowledgeRetrievalDrawer.jsx",
        "SettingsPage.jsx",
        "Sidebar.jsx",
    ]:
        path = f"frontend/react/src/components/{component}"
        require(path, 'from "./errorFeedback.js"', f"{component} imports shared feedback")
        forbid(path, "function toast(message)", f"{component} local toast helper")

    require("frontend/react/src/components/AuthScreen.jsx", "normalizeErrorMessage", "auth screen normalizes auth failures")
    require("frontend/react/src/components/AuthScreen.jsx", "BACKEND_UNAVAILABLE_MESSAGE", "auth screen keeps clear backend unavailable fallback")
    require("frontend/react/src/components/AppErrorBoundary.jsx", "export class AppErrorBoundary", "React render error boundary")
    require("frontend/react/src/components/AppErrorBoundary.jsx", 'role={"alert"}', "fatal error is announced")
    require("frontend/react/src/components/AppErrorBoundary.jsx", 'aria-labelledby={"app-fatal-title"}', "fatal error has an accessible title")
    require("frontend/react/src/components/AppErrorBoundary.jsx", "如果问题仍然存在", "fatal error offers a recovery alternative")
    forbid("frontend/react/src/components/AppErrorBoundary.jsx", "this.state.error?.message", "raw render error leak")
    forbid("frontend/react/src/components/AppErrorBoundary.jsx", "<code>{message}</code>", "raw render error details")
    require("frontend/react/src/main.jsx", "<AppErrorBoundary>", "React root wrapped by error boundary")
    require("frontend/styles.css", ".app-fatal-screen", "error boundary fallback styling")


if __name__ == "__main__":
    main()
