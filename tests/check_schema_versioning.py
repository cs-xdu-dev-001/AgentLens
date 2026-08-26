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
    assert CURRENT_SCHEMA_VERSION == 15, CURRENT_SCHEMA_VERSION
    assert "archived chat sessions" in row["description"].lower(), row
    model_columns = {item["name"] for item in fetch_all("PRAGMA table_info(model_config)")}
    assert "api_mode" in model_columns, model_columns
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
    session_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(chat_session)")
    }
    assert {
        "is_pinned",
        "is_archived",
        "context_summary",
        "context_summary_metadata_json",
        "context_summary_up_to_message_id",
    }.issubset(session_columns), session_columns
    run_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(agent_run)")
    }
    assert {
        "id",
        "user_id",
        "session_id",
        "status",
        "trace_json",
        "version",
    }.issubset(run_columns), run_columns
    step_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(agent_run_step)")
    }
    assert {
        "id",
        "run_id",
        "position",
        "title",
        "status",
    }.issubset(step_columns), step_columns
    event_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(agent_run_event)")
    }
    assert {
        "id",
        "run_id",
        "event_sequence",
        "event_name",
        "payload_json",
        "occurred_at",
    }.issubset(event_columns), event_columns
    tool_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(agent_tool_call)")
    }
    assert {"run_id", "run_step_id"}.issubset(tool_columns), tool_columns
    tool_operation_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(agent_tool_operation)")
    }
    assert {
        "id",
        "user_id",
        "run_id",
        "tool_call_id",
        "status",
        "decision",
        "execution_json",
        "expires_at",
    }.issubset(tool_operation_columns), tool_operation_columns
    memory_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(memory_config)")
    }
    assert memory_columns == {
        "user_id",
        "enabled",
        "created_at",
        "updated_at",
    }, memory_columns
    operation_columns = {
        item["name"]
        for item in fetch_all("PRAGMA table_info(memory_operation)")
    }
    assert {
        "id",
        "user_id",
        "session_id",
        "message_id",
        "kind",
        "status",
        "attempt_count",
        "result_json",
    }.issubset(operation_columns), operation_columns

    print("schema version is recorded during database initialization")


if __name__ == "__main__":
    main()
