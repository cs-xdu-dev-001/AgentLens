from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    requirements = (ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / "backend" / ".env.example").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "mem0ai==2.0.14" in requirements
    for key in [
        "KNOWFLOW_MEMORY_ENABLED",
        "KNOWFLOW_MEMORY_DEFAULT_ENABLED",
        "KNOWFLOW_MEMORY_LLM_API_KEY",
        "KNOWFLOW_MEMORY_LLM_MODEL",
        "KNOWFLOW_MEMORY_LLM_BASE_URL",
        "KNOWFLOW_MEMORY_EMBEDDER_API_KEY",
        "KNOWFLOW_MEMORY_EMBEDDER_MODEL",
        "KNOWFLOW_MEMORY_EMBEDDER_BASE_URL",
        "KNOWFLOW_MEMORY_EMBEDDING_DIMS",
        "KNOWFLOW_MEMORY_QDRANT_PATH",
        "KNOWFLOW_MEMORY_HISTORY_DB",
        "KNOWFLOW_MEMORY_TOP_K",
        "KNOWFLOW_MEMORY_SEARCH_THRESHOLD",
    ]:
        assert f"{key}=" in env_example, key

    assert "MEM0_TELEMETRY=False" in env_example
    assert "### 长期记忆（Mem0）" in readme
    assert "不会接管Agent循环" in readme
    assert "ADD-only" in readme
    assert "data/mem0" in readme
    assert "Token、Key、密码" in readme
    assert "data/mem0/" in gitignore

    print("Mem0 configuration, privacy, and deployment are documented")


if __name__ == "__main__":
    main()
