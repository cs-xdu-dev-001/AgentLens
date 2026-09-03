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
    forbidden_copy = {
        "frontend/react/src/components/ChatTopbar.jsx": [
            "选择知识库即可启用检索上下文；不选择则进行普通模型对话。",
        ],
        "frontend/react/src/components/ChatComposerForm.jsx": [
            "知识库上下文",
            "已启用知识库上下文",
            "普通对话，未使用知识库",
            "文档或截图",
        ],
        "frontend/react/src/components/ChatContextToolbar.jsx": [
            "知识库上下文",
            "当前会话",
            "自动生成",
        ],
        "frontend/react/src/components/AuthScreen.jsx": [
            "继续管理知识库、模型配置和历史对话。",
            "你可以使用本地账号登录，也可以通过 GitHub 授权进入。",
            "GitHub 仅用于登录。",
            "GitHub 登录暂未启用，你可以使用本地账号登录。",
            "开发者配置",
            "GitHub OAuth 回调地址",
        ],
        "frontend/react/src/components/KnowledgeHeader.jsx": [
            "知识库工作台",
            "在同一个工作台完成上传、处理和检索调试。",
        ],
        "frontend/react/src/components/KnowledgeSummary.jsx": [
            "上传、文档处理、对话上下文和检索范围会与选中的知识库保持同步。",
        ],
        "frontend/react/src/components/KnowledgeDocuments.jsx": [
            "上传文件后可跟踪解析、切分和向量化进度，失败的文档也可以直接重试。",
            "文件会先进入处理队列，完成解析、切分和向量化后显示在列表中。",
            "等待中或失败的文件会保留在列表里，直到处理完成或被移除。",
            "可以在每行打开分段，也可以使用检索调试查看匹配结果。",
            "{\"UploadDocuments\"}",
            "{\"Upload\"}",
            "updated ",
            "{\"Remove\"}",
            "{\"Not set\"}",
            "打开检索调试",
            "CHUNKS",
            "暂无分段。",
            "支持 txt、md、pdf、docx、xlsx、pptx、html、json、csv、xml 和 rtf。",
        ],
        "frontend/react/src/components/KnowledgeRail.jsx": [
            "{\"Open\"}",
            "暂无知识库。点击右上角按钮创建一个。",
        ],
        "frontend/react/src/components/KnowledgeRetrievalDrawer.jsx": [
            "检索调试",
            "输入要检索的问题或关键词",
            "返回分段数",
            "开始检索",
            "正在检索分段",
            "运行检索后会显示匹配分段。",
        ],
        "frontend/react/src/components/ChatEvidenceDrawer.jsx": [
            "引用与工具",
            "RAG 质量",
            "低于阈值",
            "工具调用",
            "运行 #",
            "本次回答已记录检索质量。",
            "暂无检索活动。",
        ],
        "frontend/react/src/components/KnowledgePage.jsx": [
            "高频操作集中在这里：选择空间、查看向量模型，并从列表中管理删除。",
            "检索调试",
        ],
        "frontend/react/src/components/KnowledgeModals.jsx": [
            "可选：说明这个Knowledge包含什么",
        ],
        "frontend/react/src/components/ModelConfigForm.jsx": [
            "选择预设会自动填充接口地址和常用模型名；兼容接口也可以手动填写。",
        ],
        "frontend/react/src/components/ModelListPanel.jsx": [
            "测试连接、设置默认模型，或继续编辑已有配置。",
            "暂无模型配置。请先添加 DeepSeek、OpenAI 或其他兼容模型。",
        ],
        "frontend/react/src/components/SettingsHeader.jsx": [
            "管理模型提供商、常用模型、API 密钥和接口文档。",
        ],
        "frontend/react/src/components/ModelConfigDetails.jsx": [
            "FastAPI 会生成交互式文档，方便本地调试接口。",
            "当前产品取舍",
            "第一版聚焦对话、RAG 和文档处理闭环。",
            "上传、去重、切分、检索和引用形成完整闭环。",
            "开发资源",
            "OpenAPI JSON",
        ],
        "frontend/react/src/components/Sidebar.jsx": [
            "8010 端口",
            "API 服务",
            "知识助手",
        ],
    }
    for path, needles in forbidden_copy.items():
        for needle in needles:
            forbid(path, needle, "documentation-style product copy")

    require("frontend/react/src/components/ChatTopbar.jsx", "新任务", "short task title")
    require("frontend/react/src/components/KnowledgeHeader.jsx", "知识库", "short knowledge title")
    require("frontend/react/src/components/SettingsHeader.jsx", "模型配置", "short settings title")
    require("frontend/react/src/components/KnowledgeDocuments.jsx", "添加文档", "short upload action")
    require("frontend/react/src/components/KnowledgeRetrievalDrawer.jsx", "暂无结果", "short retrieval empty state")
    require("frontend/react/src/components/ModelListPanel.jsx", "暂无配置", "short model empty state")
    print("frontend product copy is concise")


if __name__ == "__main__":
    main()
