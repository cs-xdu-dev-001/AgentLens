from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def forbid(relative_path: str, needle: str, label: str) -> None:
    if needle in read(relative_path):
        raise AssertionError(f"Legacy {label} still present: {needle}")


def main() -> None:
    require("frontend/react/src/api/client.js", "runtimeApi", "runtime API helper")
    require("frontend/react/src/api/client.js", "/api/runtime", "runtime endpoint")
    require("frontend/react/src/components/Sidebar.jsx", "loadRuntime", "React runtime loader")
    require("frontend/react/src/components/Sidebar.jsx", "runtimeApi.get", "React runtime API call")
    require("frontend/react/src/components/Sidebar.jsx", "knowflow:react-refresh", "React runtime refresh event")
    require("frontend/react/src/components/Sidebar.jsx", "setRuntime", "React owns runtime state")
    require("frontend/react/src/components/Sidebar.jsx", "setFailed", "React owns runtime failure state")
    require("frontend/react/src/components/Sidebar.jsx", "在线", "compact connected status copy")
    require("frontend/react/src/components/Sidebar.jsx", "runtime.version", "visible runtime version")
    require("backend/knowflow/app.py", '"version": app.version', "runtime version payload")
    require("frontend/react/src/components/Sidebar.jsx", "连接中", "compact loading status copy")
    require("frontend/react/src/components/Sidebar.jsx", "离线", "compact disconnected status copy")
    forbid("frontend/react/src/components/Sidebar.jsx", "知识库与对话可用", "verbose connected status copy")

    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:legacy-runtime-updated", "legacy runtime data event")
    forbid("frontend/react/src/components/Sidebar.jsx", "knowflow:legacy-runtime-failed", "legacy runtime failure event")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-runtime-updated", "legacy runtime data broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-runtime-failed", "legacy runtime failure broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactRuntimeStatusEnabled", "legacy runtime ownership flag")
    forbid("frontend/react/src/controller/knowflowController.js", "notifyReactRuntimeUpdated", "legacy runtime update notifier")
    forbid("frontend/react/src/controller/knowflowController.js", "notifyReactRuntimeFailed", "legacy runtime failure notifier")
    forbid("frontend/react/src/controller/knowflowController.js", "function renderRuntime", "legacy runtime DOM renderer")
    forbid("frontend/react/src/controller/knowflowController.js", "$(\"#runtime-box\")", "legacy runtime DOM access")
    forbid("frontend/react/src/controller/knowflowController.js", "运行状态读取失败", "legacy runtime failure text")
    forbid("frontend/react/src/components/Sidebar.jsx", "数据库", "engineering database status copy")
    forbid("frontend/react/src/components/Sidebar.jsx", "向量库", "engineering vector status copy")
    forbid("frontend/react/src/components/Sidebar.jsx", "正在读取运行状态", "engineering runtime loading copy")


if __name__ == "__main__":
    main()
