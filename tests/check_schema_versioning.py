from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "schema-version.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    from knowflow.database import CURRENT_SCHEMA_VERSION
    from knowflow.runtime import fetch_all, fetch_one

    row = fetch_one("SELECT version, description FROM schema_version ORDER BY version DESC LIMIT 1")
    assert row, "schema_version should contain at least one applied version"
    assert row["version"] == CURRENT_SCHEMA_VERSION, row
    assert CURRENT_SCHEMA_VERSION == 5, CURRENT_SCHEMA_VERSION
    assert "skill" in row["description"].lower(), row
    columns = {item["name"] for item in fetch_all("PRAGMA table_info(tool_config)")}
    assert columns == {
        "id",
        "user_id",
        "tool_name",
        "provider",
        "api_key_cipher",
        "enabled",
        "created_at",
        "updated_at",
    }, columns
    message_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(chat_message)")
    }
    assert "trace_json" in message_columns, message_columns

    print("schema version is recorded during database initialization")


if __name__ == "__main__":
    main()
