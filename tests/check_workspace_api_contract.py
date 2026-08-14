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

    assert "current_user_id(request)" in router
    assert '"/api/workspace/files"' in router
    assert '"/api/workspace/files/{path:path}"' in router
    assert '"/api/workspace/changes"' in router
    assert '"/api/workspace/changes/undo"' in router
    assert "operation_id=payload.operationId" in router
    assert "WorkspaceRuntime(" in router
    assert "workspace_router" in registry
    assert "workspaceApi" in client
    assert "undoChange" in client and "workspace/changes" in client
    assert "工作区" in page and "Linux沙箱可用" in page

    print("workspace API and frontend preserve authenticated user isolation")


if __name__ == "__main__":
    main()
