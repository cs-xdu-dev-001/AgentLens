from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "memory-config.db"
    qdrant_path = ROOT / "data" / "test-memory" / "qdrant"
    history_path = ROOT / "data" / "test-memory" / "history.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_MEMORY_ENABLED"] = "1"
    os.environ["KNOWFLOW_MEMORY_DEFAULT_ENABLED"] = "0"
    os.environ["KNOWFLOW_MEMORY_LLM_API_KEY"] = "memory-test-key"
    os.environ["KNOWFLOW_MEMORY_LLM_MODEL"] = "test-memory-model"
    os.environ["KNOWFLOW_MEMORY_LLM_BASE_URL"] = "https://example.com/v1"
    os.environ["KNOWFLOW_MEMORY_EMBEDDER_API_KEY"] = "embed-test-key"
    os.environ["KNOWFLOW_MEMORY_EMBEDDER_MODEL"] = "test-embed-model"
    os.environ["KNOWFLOW_MEMORY_EMBEDDER_BASE_URL"] = "https://embed.example.com/v1"
    os.environ["KNOWFLOW_MEMORY_EMBEDDING_DIMS"] = "768"
    os.environ["KNOWFLOW_MEMORY_QDRANT_PATH"] = str(qdrant_path)
    os.environ["KNOWFLOW_MEMORY_HISTORY_DB"] = str(history_path)
    sys.path.insert(0, str(BACKEND))

    from knowflow.config import (
        MEMORY_DEFAULT_ENABLED,
        MEMORY_ENABLED,
        MEMORY_HISTORY_DB,
        MEMORY_QDRANT_PATH,
        build_mem0_config,
    )
    from knowflow.database import CURRENT_SCHEMA_VERSION, Database

    assert MEMORY_ENABLED is True
    assert MEMORY_DEFAULT_ENABLED is False
    assert MEMORY_QDRANT_PATH == qdrant_path
    assert MEMORY_HISTORY_DB == history_path

    config = build_mem0_config()
    assert config["llm"] == {
        "provider": "openai",
        "config": {
            "api_key": "memory-test-key",
            "model": "test-memory-model",
            "openai_base_url": "https://example.com/v1",
            "temperature": 0.1,
        },
    }
    assert config["embedder"] == {
        "provider": "openai",
        "config": {
            "api_key": "embed-test-key",
            "model": "test-embed-model",
            "openai_base_url": "https://embed.example.com/v1",
            "embedding_dims": 768,
        },
    }
    assert config["vector_store"]["provider"] == "qdrant"
    assert config["vector_store"]["config"]["path"] == str(qdrant_path)
    assert config["vector_store"]["config"]["on_disk"] is True
    assert config["history_db_path"] == str(history_path)
    assert "credentials" in config["custom_instructions"].lower()
    assert "same primary language" in config["custom_instructions"].lower()
    assert "simplified chinese" in config["custom_instructions"].lower()
    assert "never translate chinese memories into english" in config[
        "custom_instructions"
    ].lower()

    database = Database(f"sqlite:///{db_path.as_posix()}")
    with database.engine.connect() as conn:
        columns = {
            row["name"]
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(memory_config)"
            ).mappings()
        }
    assert columns == {
        "user_id",
        "enabled",
        "created_at",
        "updated_at",
    }, columns
    assert CURRENT_SCHEMA_VERSION == 14

    requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    assert "mem0ai==2.0.14" in requirements

    print("Mem0 configuration is durable, explicit, and version-pinned")


if __name__ == "__main__":
    main()
