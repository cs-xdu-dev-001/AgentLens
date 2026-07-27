from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def table_columns(fetch_all, table: str) -> set[str]:
    return {
        item["name"]
        for item in fetch_all(f"PRAGMA table_info({table})")
    }


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "skill-schema.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    os.environ["KNOWFLOW_SKILL_DIR"] = "data/test-dbs/skills"
    sys.path.insert(0, str(BACKEND))

    from knowflow import config
    from knowflow.database import CURRENT_SCHEMA_VERSION, Database
    from knowflow.db_schema import MYSQL_SCHEMA
    from knowflow.runtime import fetch_all, fetch_one

    assert CURRENT_SCHEMA_VERSION == 5, CURRENT_SCHEMA_VERSION
    version_row = fetch_one(
        "SELECT description FROM schema_version WHERE version=:version",
        {"version": CURRENT_SCHEMA_VERSION},
    )
    assert version_row == {
        "description": (
            "Add per-user Skill packages, installations, staged imports, and run snapshots."
        )
    }, version_row

    tables = {
        item["name"]
        for item in fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"skill_package", "user_skill", "skill_import"} <= tables, tables
    expected_table_columns = {
        "skill_package": {
            "id",
            "owner_user_id",
            "slug",
            "display_name",
            "description",
            "version",
            "source_kind",
            "source_url",
            "source_ref",
            "source_subpath",
            "content_hash",
            "package_path",
            "manifest_json",
            "created_at",
        },
        "user_skill": {
            "id",
            "user_id",
            "skill_package_id",
            "skill_slug",
            "enabled",
            "installed_at",
            "updated_at",
        },
        "skill_import": {
            "id",
            "user_id",
            "source_kind",
            "staged_path",
            "content_hash",
            "preview_json",
            "expires_at",
            "created_at",
        },
    }
    for table, expected_columns in expected_table_columns.items():
        assert table_columns(fetch_all, table) == expected_columns

    skill_snapshot_columns = {
        "skill_id",
        "skill_slug",
        "skill_version",
        "skill_content_hash",
    }
    assert skill_snapshot_columns <= table_columns(fetch_all, "chat_message")
    assert skill_snapshot_columns <= table_columns(fetch_all, "agent_tool_call")

    mysql_schema_lower = MYSQL_SCHEMA.lower()
    for table, expected_columns in expected_table_columns.items():
        marker = f"create table if not exists {table} ("
        start = mysql_schema_lower.index(marker)
        end = mysql_schema_lower.index(") engine=innodb", start)
        table_ddl = mysql_schema_lower[start:end]
        for column in expected_columns:
            assert f"\n  {column} " in table_ddl, (table, column)
    for column in skill_snapshot_columns:
        assert column in mysql_schema_lower

    os.environ["TEST_BOUNDED_ENV_INT"] = "-5"
    assert config.bounded_env_int("TEST_BOUNDED_ENV_INT", 10, 1, 20) == 1
    os.environ["TEST_BOUNDED_ENV_INT"] = "50"
    assert config.bounded_env_int("TEST_BOUNDED_ENV_INT", 10, 1, 20) == 20
    os.environ["TEST_BOUNDED_ENV_INT"] = "invalid"
    assert config.bounded_env_int("TEST_BOUNDED_ENV_INT", 10, 1, 20) == 10
    assert config.SKILL_DIR == (ROOT / "data/test-dbs/skills").resolve()
    assert config.SKILL_IMPORT_DIR == config.DATA_DIR / "skill-imports"
    assert config.SKILL_DIR.is_dir()
    assert config.SKILL_IMPORT_DIR.is_dir()

    legacy_path = ROOT / "data" / "test-dbs" / "skill-schema-legacy.db"
    if legacy_path.exists():
        legacy_path.unlink()
    legacy_connection = sqlite3.connect(legacy_path)
    legacy_connection.executescript(
        """
        CREATE TABLE chat_message (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          trace_json TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE agent_tool_call (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          message_id INTEGER,
          tool_name TEXT NOT NULL,
          input_json TEXT,
          output_text TEXT,
          status TEXT DEFAULT 'success',
          error_message TEXT,
          latency_ms INTEGER,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    legacy_connection.close()
    legacy_db = Database(f"sqlite:///{legacy_path.as_posix()}")
    with legacy_db.engine.begin() as conn:
        chat_columns = legacy_db.table_columns(conn, "chat_message")
        tool_columns = legacy_db.table_columns(conn, "agent_tool_call")
    assert skill_snapshot_columns <= chat_columns
    assert skill_snapshot_columns <= tool_columns
    legacy_db.engine.dispose()

    print("skill schema and configuration checks passed")


if __name__ == "__main__":
    main()
