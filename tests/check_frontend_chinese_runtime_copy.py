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
    user_visible_files = {
        "frontend/react/src/App.jsx": [
            "Skip to main content",
        ],
        "frontend/react/src/auth/AuthProvider.jsx": [
            "无法获取当前Login状态",
            "useAuth must be used inside AuthProvider",
        ],
        "frontend/react/src/components/AppErrorBoundary.jsx": [
            "Refresh页面",
            "Reload",
        ],
        "frontend/react/src/components/AuthScreen.jsx": [
            ">Login<",
            ">Register<",
            "\n            Login\n",
            "\n            Register\n",
        ],
        "frontend/react/src/components/Sidebar.jsx": [
            "删除 failed",
        ],
        "frontend/react/src/api/client.js": [
            "Request failed",
        ],
        "frontend/react/src/controller/attachmentFlow.js": [
            "Attachment added:",
            "Screenshot paste failed",
        ],
        "frontend/react/src/controller/bridgeBindings.js": [
            "Answer copied",
            "Refresh failed",
            "Copy failed",
            "Retry failed",
            "Open knowledge base failed",
            "Sync knowledge bases failed",
            "Attachment upload failed",
            "Open session failed",
            "Refresh models failed",
            "Send failed",
            "Paste failed",
        ],
        "frontend/react/src/controller/chatFlow.js": [
            "No retryable question yet",
            "Please summarize the uploaded files.",
            "Attachments:",
            "No model output received.",
            "Generation stopped.",
            "Request failed:",
            "Unknown error",
            "Chat request failed",
            "Message component is not ready.",
        ],
        "frontend/react/src/controller/knowflowController.js": [
            "Retrieval run #",
            "Review quality details in the evidence panel.",
            "Startup failed",
        ],
        "frontend/react/src/controller/request.js": [
            "Please sign in first.",
            "Request failed. Please try again.",
        ],
    }
    for path, needles in user_visible_files.items():
        for needle in needles:
            forbid(path, needle, "English or mixed user-facing runtime copy")

    require("frontend/react/src/App.jsx", "跳到主要内容", "Chinese skip-link text")
    require("frontend/react/src/auth/AuthProvider.jsx", "useAuth 必须在 AuthProvider 内使用", "Chinese auth hook error")
    require("frontend/react/src/components/AuthScreen.jsx", "登录", "Chinese login tab")
    require("frontend/react/src/components/AuthScreen.jsx", "注册", "Chinese register tab")
    require("frontend/react/src/components/Sidebar.jsx", "刷新", "Chinese session refresh button")
    require("frontend/react/src/components/AppErrorBoundary.jsx", "刷新页面", "Chinese fatal reload button")
    require("frontend/react/src/controller/attachmentFlow.js", "附件已添加：", "Chinese attachment added toast")
    require("frontend/react/src/controller/bridgeBindings.js", "答案已复制", "Chinese copy success toast")
    require("frontend/react/src/controller/bridgeBindings.js", "复制失败，请重试", "concise Chinese copy failure toast")
    forbid(
        "frontend/react/src/controller/bridgeBindings.js",
        'toast(content || "复制失败"',
        "assistant answer echoed into the copy failure toast",
    )
    require("frontend/react/src/api/errors.js", "请先登录。", "Chinese sign-in fallback")
    require("frontend/react/src/api/client.js", "请求失败", "Chinese API failure fallback")
    require("frontend/react/src/controller/chatFlow.js", "暂无可重试的问题", "Chinese retry fallback")
    require("frontend/react/src/controller/chatFlow.js", "请总结上传的文件。", "Chinese attachment-only prompt")
    require("frontend/react/src/controller/chatFlow.js", "附件：", "Chinese attachment label")
    require("frontend/react/src/controller/chatFlow.js", "模型没有返回内容。", "Chinese empty model output")
    require("frontend/react/src/controller/chatFlow.js", "生成已停止。", "Chinese generation stopped message")
    require("frontend/react/src/controller/chatFlow.js", "请求失败：", "Chinese request failure message")
    require("frontend/react/src/controller/chatFlow.js", "消息组件尚未准备好。", "Chinese message component error")
    require("frontend/react/src/controller/knowflowController.js", "检索记录 #", "Chinese retrieval run toast")
    require("frontend/react/src/controller/knowflowController.js", "启动失败", "Chinese startup failure fallback")
    print("frontend runtime copy is Chinese-first")


if __name__ == "__main__":
    main()
