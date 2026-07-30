from __future__ import annotations

import inspect
import os
import re
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


def normalized_sql(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


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

    assert CURRENT_SCHEMA_VERSION == 9, CURRENT_SCHEMA_VERSION
    version_row = fetch_one(
        "SELECT description FROM schema_version WHERE version=:version",
        {"version": CURRENT_SCHEMA_VERSION},
    )
    assert version_row == {
        "description": "Add selectable chat model API protocol."
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
    mysql_table_ddls = {}
    for table, expected_columns in expected_table_columns.items():
        marker = f"create table if not exists {table} ("
        start = mysql_schema_lower.index(marker)
        end = mysql_schema_lower.index(") engine=innodb", start)
        table_ddl = mysql_schema_lower[start:end]
        mysql_table_ddls[table] = normalized_sql(table_ddl)
        for column in expected_columns:
            assert f"\n  {column} " in table_ddl, (table, column)
    for column in skill_snapshot_columns:
        assert column in mysql_schema_lower
    expected_mysql_fragments = {
        "skill_package": {
            "id bigint primary key auto_increment",
            "owner_user_id bigint not null",
            "slug varchar(255) not null",
            "version varchar(100) not null",
            "content_hash varchar(128) not null",
            "package_path varchar(1000) not null",
            "manifest_json longtext not null",
            (
                "unique key uk_skill_package_owner_slug_hash "
                "(owner_user_id, slug, content_hash)"
            ),
        },
        "user_skill": {
            "id bigint primary key auto_increment",
            "user_id bigint not null",
            "skill_package_id bigint not null",
            "skill_slug varchar(255) not null",
            "enabled tinyint default 1",
            "unique key uk_user_skill_user_slug (user_id, skill_slug)",
        },
        "skill_import": {
            "id varchar(128) primary key",
            "user_id bigint not null",
            "source_kind varchar(30) not null",
            "staged_path varchar(1000) not null",
            "content_hash varchar(128) not null",
            "preview_json longtext not null",
            "expires_at datetime not null",
        },
    }
    for table, fragments in expected_mysql_fragments.items():
        for fragment in fragments:
            assert fragment in mysql_table_ddls[table], (table, fragment)

    version_writer_source = normalized_sql(
        inspect.getsource(Database.record_schema_version)
    )
    assert "where not exists" not in version_writer_source
    assert "on conflict(version) do nothing" in version_writer_source
    assert "on duplicate key update" in version_writer_source
    assert "insert or ignore" not in version_writer_source
    assert "insert ignore" not in version_writer_source

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
        CREATE TABLE schema_version (
          version INTEGER PRIMARY KEY,
          description TEXT,
          applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO schema_version(version, description)
        VALUES (
          4,
          'Add per-user remote MCP servers, encrypted credentials, and OAuth sessions.'
        );
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

    def assert_stable_current_migration() -> None:
        with legacy_db.engine.begin() as conn:
            version_rows = conn.exec_driver_sql(
                """
                SELECT version, COUNT(*) AS count
                FROM schema_version
                GROUP BY version
                ORDER BY version
                """
            ).mappings().all()
            chat_columns = [
                row["name"]
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info(chat_message)"
                ).mappings().all()
            ]
            tool_columns = [
                row["name"]
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info(agent_tool_call)"
                ).mappings().all()
            ]
        assert [(row["version"], row["count"]) for row in version_rows] == [
            (4, 1),
            (8, 1),
        ], version_rows
        assert len(chat_columns) == len(set(chat_columns))
        assert len(tool_columns) == len(set(tool_columns))
        assert skill_snapshot_columns <= set(chat_columns)
        assert skill_snapshot_columns <= set(tool_columns)

    assert_stable_current_migration()
    legacy_db.init_schema()
    assert_stable_current_migration()

    with legacy_db.engine.begin() as conn:
        legacy_db.record_schema_version(conn)
        legacy_db.record_schema_version(conn)
    assert_stable_current_migration()
    legacy_db.engine.dispose()

    print("skill schema and configuration checks passed")


if __name__ == "__main__":
    main()
