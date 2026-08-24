from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text

from .db_schema import MYSQL_SCHEMA, SQLITE_SCHEMA

CURRENT_SCHEMA_VERSION = 13


class Database:
    def __init__(self, url: str):
        self.url = url
        self.engine = create_engine(url, future=True, pool_pre_ping=True)
        self.dialect = self.engine.dialect.name
        self.init_schema()

    @property
    def is_mysql(self) -> bool:
        return self.dialect.startswith("mysql")

    def init_schema(self) -> None:
        if self.is_mysql:
            ddl = MYSQL_SCHEMA
        else:
            ddl = SQLITE_SCHEMA
        with self.engine.begin() as conn:
            for statement in ddl.split(";"):
                statement = statement.strip()
                if statement:
                    conn.execute(text(statement))
            self.migrate_schema(conn)
            self.record_schema_version(conn)

    def table_columns(self, conn: Any, table: str) -> set[str]:
        if self.is_mysql:
            rows = conn.execute(text(f"SHOW COLUMNS FROM {table}")).mappings().all()
            return {str(row["Field"]) for row in rows}
        rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
        return {str(row["name"]) for row in rows}

    def add_column_if_missing(self, conn: Any, table: str, column: str, definition: str) -> None:
        if column not in self.table_columns(conn, table):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))

    def migrate_schema(self, conn: Any) -> None:
        id_type = "BIGINT" if self.is_mysql else "INTEGER"
        for table in ["model_config", "knowledge_base", "document", "chat_session", "sync_task"]:
            self.add_column_if_missing(conn, table, "user_id", id_type)
        self.add_column_if_missing(conn, "model_config", "api_mode", "VARCHAR(30) NOT NULL DEFAULT 'chat_completions'" if self.is_mysql else "TEXT NOT NULL DEFAULT 'chat_completions'")
        trace_type = "LONGTEXT" if self.is_mysql else "TEXT"
        self.add_column_if_missing(
            conn,
            "chat_message",
            "trace_json",
            trace_type,
        )
        snapshot_columns = {
            "skill_id": id_type,
            "skill_slug": "VARCHAR(255)" if self.is_mysql else "TEXT",
            "skill_version": "VARCHAR(100)" if self.is_mysql else "TEXT",
            "skill_content_hash": "VARCHAR(128)" if self.is_mysql else "TEXT",
        }
        for table in ["chat_message", "agent_tool_call"]:
            for column, definition in snapshot_columns.items():
                self.add_column_if_missing(conn, table, column, definition)
        run_id_type = "VARCHAR(64)" if self.is_mysql else "TEXT"
        self.add_column_if_missing(
            conn,
            "agent_tool_call",
            "run_id",
            run_id_type,
        )
        self.add_column_if_missing(
            conn,
            "agent_tool_call",
            "run_step_id",
            run_id_type,
        )
        self.add_column_if_missing(
            conn,
            "agent_run",
            "request_json",
            "LONGTEXT" if self.is_mysql else "TEXT",
        )
        summary_type = "LONGTEXT" if self.is_mysql else "TEXT"
        self.add_column_if_missing(
            conn,
            "chat_session",
            "context_summary",
            summary_type,
        )
        self.add_column_if_missing(
            conn,
            "chat_session",
            "context_summary_metadata_json",
            summary_type,
        )
        self.add_column_if_missing(
            conn,
            "chat_session",
            "context_summary_up_to_message_id",
            id_type,
        )

    def record_schema_version(self, conn: Any) -> None:
        if self.is_mysql:
            insert_sql = """
                INSERT INTO schema_version(version, description)
                VALUES (:version, :description)
                ON DUPLICATE KEY UPDATE version = VALUES(version)
            """
        else:
            insert_sql = """
                INSERT INTO schema_version(version, description)
                VALUES (:version, :description)
                ON CONFLICT(version) DO NOTHING
            """
        conn.execute(
            text(insert_sql),
            {
                "version": CURRENT_SCHEMA_VERSION,
                "description": (
                    "Persist session context compaction boundaries."
                ),
            },
        )
