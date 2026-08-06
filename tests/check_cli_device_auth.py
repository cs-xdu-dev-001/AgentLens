from datetime import datetime, timedelta
from pathlib import Path
import sys
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import Database  # noqa: E402
from knowflow.services.cli_device_auth import CliDeviceAuthorizationStore  # noqa: E402
from sqlalchemy import text  # noqa: E402


def main() -> None:
    with TemporaryDirectory() as folder:
        database = Database(f"sqlite:///{(Path(folder) / 'device.db').as_posix()}")
        store = CliDeviceAuthorizationStore(database, "test-secret", ttl_seconds=600)
        now = datetime(2026, 8, 6, 10, 0, 0)
        with database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO app_user(id, email, username, display_name)
                    VALUES (7, 'device@example.com', 'device-user', 'Device User')
                    """
                )
            )

        created = store.create(client_name="test", now=now)
        assert created["deviceCode"] not in str(database.engine.url)
        poll = lambda code, at=now: store.consume_with_session(
            device_code=code,
            session_expires_at="2026-08-13 10:00:00",
            now=at,
        )
        assert poll("wrong-device")["status"] == "invalid"
        assert store.decide(user_code="BAD-CODE", user_id=1, decision="approve", now=now)["status"] == "invalid"
        assert poll(created["deviceCode"])["status"] == "pending"
        assert store.decide(user_code=created["userCode"], user_id=7, decision="approve", now=now)["status"] == "approved"
        assert store.decide(user_code=created["userCode"], user_id=8, decision="approve", now=now)["status"] == "already_processed"
        consumed = poll(created["deviceCode"])
        assert consumed["status"] == "authorized" and consumed["userId"] == 7, consumed
        assert poll(created["deviceCode"])["status"] == "consumed"

        denied = store.create(now=now)
        assert store.decide(user_code=denied["userCode"], user_id=9, decision="deny", now=now)["status"] == "denied"
        assert poll(denied["deviceCode"])["status"] == "denied"

        expired = store.create(now=now)
        later = now + timedelta(seconds=601)
        assert store.decide(user_code=expired["userCode"], user_id=1, decision="approve", now=later)["status"] == "expired"
        assert poll(expired["deviceCode"], later)["status"] == "expired"

        session_request = store.create(now=now)
        assert store.decide(user_code=session_request["userCode"], user_id=7, decision="approve", now=now)["status"] == "approved"
        session_result = store.consume_with_session(
            device_code=session_request["deviceCode"],
            session_expires_at="2026-08-13 10:00:00",
            user_agent="test-cli",
            now=now,
        )
        assert session_result["status"] == "authorized"
        with database.engine.connect() as connection:
            session_row = connection.execute(
                text("SELECT user_id, user_agent FROM auth_session WHERE id=:id"),
                {"id": session_result["sessionToken"]},
            ).mappings().first()
        assert dict(session_row or {}) == {"user_id": 7, "user_agent": "test-cli"}

        with database.engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT device_code_hash, user_code_hash FROM cli_device_authorization LIMIT 1"
            ).mappings().first()
        assert row
        assert created["deviceCode"] not in row["device_code_hash"]
        assert created["userCode"].replace("-", "") not in row["user_code_hash"]
        database.engine.dispose()

    print("cli device authorization checks passed")


if __name__ == "__main__":
    main()
