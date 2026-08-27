from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> None:
    visible_surfaces = {
        "frontend/index.html": "<title>AgentLens</title>",
        "frontend/react/src/components/AuthScreen.jsx": "登录AgentLens",
        "frontend/react/src/components/AppErrorBoundary.jsx": '>{"AgentLens"}<',
        "frontend/react/src/components/Sidebar.jsx": "AgentLens",
        "cli-tui/src/app.jsx": "AgentLens",
        "backend/knowflow/cli.py": 'name="agentlens"',
        "backend/knowflow/app.py": 'title="AgentLens API"',
        "backend/knowflow/tui/app.py": 'TITLE = "AgentLens"',
        "README.md": "# AgentLens",
        "README_EN.md": "# AgentLens",
        "frontend/package.json": '"name": "agentlens-frontend"',
        "cli-tui/package.json": '"name": "@agentlens/tui"',
    }
    for relative_path, required in visible_surfaces.items():
        source = read(relative_path)
        assert required in source, f"AgentLens brand missing from {relative_path}: {required!r}"

    assert "knowflow-logo-k" not in read("frontend/react/src/components/KnowFlowLogo.jsx")
    assert "knowflow-logo-lens" in read("frontend/react/src/components/KnowFlowLogo.jsx")
    assert "KNOWFLOW AI" not in read("frontend/react/src/components/AppErrorBoundary.jsx")

    compatibility_surfaces = {
        "backend/pyproject.toml": [
            'name = "knowflow-ai"',
            'agentlens = "knowflow.cli:main"',
            'knowflow = "knowflow.cli:main"',
        ],
        "README.md": ["`agentlens`", "knowflow update", "`KNOWFLOW_*`"],
        "install.sh": ["knowflow-ai", "agentlens configure", "旧版knowflow命令"],
        ".github/workflows/ci.yml": ["agentlens --help", "knowflow --help", "agentlens-linux-${GITHUB_SHA}.tar.gz"],
    }
    for relative_path, required_values in compatibility_surfaces.items():
        source = read(relative_path)
        for required in required_values:
            assert required in source, f"compatibility identifier missing from {relative_path}: {required!r}"

    print("AgentLens branding and compatibility checks passed.")


if __name__ == "__main__":
    main()
