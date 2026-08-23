from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_backend() -> str:
    files = [ROOT / "backend" / "main.py", *sorted((ROOT / "backend" / "knowflow").rglob("*.py"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def read_frontend() -> str:
    files = [ROOT / "frontend" / "index.html", *sorted((ROOT / "frontend" / "react" / "src").rglob("*.*"))]
    return "\n".join(path.read_text(encoding="utf-8") for path in files if path.is_file())


def main() -> None:
    backend = read_backend()
    frontend = read_frontend()
    docs = (ROOT / "docs" / "api-debug.md").read_text(encoding="utf-8")

    required_backend_tokens = [
        "openapi_tags=OPENAPI_TAGS",
        'docs_url="/docs"',
        'redoc_url="/redoc"',
        '@app.get("/api/health"',
        '"/api/model-configs"',
        '"/api/knowledge-bases"',
        '"/api/documents/{document_id}"',
        '"/api/retrieval/debug"',
        '"/api/chat"',
        '"/api/sessions"',
    ]
    hidden_frontend_tokens = [
        '"/docs"',
        '"/redoc"',
        '"/openapi.json"',
        '"/api/health"',
    ]
    required_docs_tokens = [
        "# AgentLens",
        "Swagger UI",
        "/api/retrieval/debug",
        "/api/documents/{documentId}/tasks",
        "taskId",
    ]


    for token in required_backend_tokens:
        assert token in backend, f"backend missing {token}"
    for token in hidden_frontend_tokens:
        assert token not in frontend, f"frontend should not expose developer endpoint {token}"
    for token in required_docs_tokens:
        assert token in docs, f"docs missing {token}"


if __name__ == "__main__":
    main()
