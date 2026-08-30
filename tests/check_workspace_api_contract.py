from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    router = (
        ROOT / "backend" / "knowflow" / "routers" / "workspaces.py"
    ).read_text(encoding="utf-8")
    registry = (
        ROOT / "backend" / "knowflow" / "routers" / "__init__.py"
    ).read_text(encoding="utf-8")
    client = (
        ROOT / "frontend" / "react" / "src" / "api" / "client.js"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "frontend" / "react" / "src" / "components" / "WorkbenchPage.jsx"
    ).read_text(encoding="utf-8")
    topbar = (
        ROOT / "frontend" / "react" / "src" / "components" / "ChatTopbar.jsx"
    ).read_text(encoding="utf-8")
    git_presentation = (
        ROOT
        / "frontend"
        / "react"
        / "src"
        / "components"
        / "workspaceGitPresentation.js"
    ).read_text(encoding="utf-8")

    assert "current_user_id(request)" in router
    assert '"/api/workspace/files"' in router
    assert '"/api/workspace/files/{path:path}"' in router
    assert '"/api/workspace/changes"' in router
    assert '"/api/workspace/changes/undo"' in router
    assert "operation_id=payload.operationId" in router
    assert "WorkspaceRuntime(" in router
    assert '"itemCount": item_count' in router
    assert '"isolation": "user"' in router
    assert '"scopeLabel"' in router
    assert '"workspaceKind": workspace_kind' in router
    assert '"allowedDirectoryCount": allowed_directory_count' in router
    assert '"cwdLabel": "工作区根目录"' in router
    assert '"projectRoot"' not in router
    assert '"allowedDirectories":' not in router
    assert '"protectedPatterns"' in router
    assert '"symlinkWriteProtected": True' in router
    assert '"projectInstructions": project_instructions' in router
    assert '"git": git_status' in router
    assert "WorkspaceContext(runtime.root).status()" in router
    assert "workspace_router" in registry
    assert "workspaceApi" in client
    assert "undoChange" in client and "workspace/changes" in client
    assert "工作区" in page and "Linux沙箱可用" in page
    assert "隔离工作区已启用" in page and "敏感路径受保护" in page
    assert "workspaceGitPresentation(status)" in page
    assert "workspaceApi.status()" in topbar
    assert "chat-workspace-toggle" in topbar
    assert "隔离工作区" in topbar
    assert "knowflow:react-workspace-updated" in topbar
    assert "projectInstructions" in topbar and "份项目指令" in topbar
    assert "项目指令：" in page and "未发现项目指令" in page
    assert "workspace-boundary-card" in page and "Agent可见范围" in page
    assert "allowedDirectoryCount" in page and "cwdLabel" in page
    assert "workspaceGitPresentation(status)" in topbar
    assert "conflictedFiles" in git_presentation
    assert "stagedFiles" in git_presentation
    assert "untrackedFiles" in git_presentation
    assert "领先" in git_presentation and "落后" in git_presentation

    print("workspace API and frontend preserve authenticated user isolation")


if __name__ == "__main__":
    main()
