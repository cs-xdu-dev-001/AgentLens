from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Any

from sqlalchemy import text

from ..database import Database


USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


class CliDeviceAuthorizationStore:
    def __init__(
        self,
        database: Database,
        secret_key: str,
        *,
        ttl_seconds: int = 600,
        polling_interval_seconds: int = 3,
    ) -> None:
        self.database = database
        self.secret_key = secret_key.encode("utf-8")
        self.ttl_seconds = ttl_seconds
        self.polling_interval_seconds = polling_interval_seconds

    def _digest(self, namespace: str, value: str) -> str:
        return hmac.new(
            self.secret_key,
            f"{namespace}:{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def normalize_user_code(value: str) -> str:
        return "".join(character for character in value.upper() if character.isalnum())

    def create(self, *, client_name: str = "AgentLens CLI", now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now()
        device_code = secrets.token_urlsafe(32)
        compact_code = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(10))
        user_code = f"{compact_code[:5]}-{compact_code[5:]}"
        authorization_id = f"cliauth_{secrets.token_hex(12)}"
        expires_at = current + timedelta(seconds=self.ttl_seconds)
        with self.database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DELETE FROM cli_device_authorization
                    WHERE expires_at < :retention_cutoff
                    """
                ),
                {"retention_cutoff": _timestamp(current - timedelta(days=1))},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO cli_device_authorization(
                        id, device_code_hash, user_code_hash, user_id, status,
                        client_name, expires_at, created_at
                    ) VALUES (
                        :id, :device_code_hash, :user_code_hash, NULL, 'pending',
                        :client_name, :expires_at, :created_at
                    )
                    """
                ),
                {
                    "id": authorization_id,
                    "device_code_hash": self._digest("device", device_code),
                    "user_code_hash": self._digest("user", compact_code),
                    "client_name": client_name.strip()[:100] or "AgentLens CLI",
                    "expires_at": _timestamp(expires_at),
                    "created_at": _timestamp(current),
                },
            )
        return {
            "deviceCode": device_code,
            "userCode": user_code,
            "expiresIn": self.ttl_seconds,
            "interval": self.polling_interval_seconds,
        }

    def decide(
        self,
        *,
        user_code: str,
        user_id: int,
        decision: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now()
        normalized = self.normalize_user_code(user_code)
        if len(normalized) != 10:
            return {"status": "invalid"}
        status = "approved" if decision == "approve" else "denied"
        with self.database.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE cli_device_authorization
                    SET status=:status, user_id=:user_id, approved_at=:approved_at
                    WHERE user_code_hash=:user_code_hash
                      AND status='pending'
                      AND expires_at > :now
                    """
                ),
                {
                    "status": status,
                    "user_id": user_id,
                    "approved_at": _timestamp(current),
                    "user_code_hash": self._digest("user", normalized),
                    "now": _timestamp(current),
                },
            )
            if result.rowcount == 1:
                return {"status": status}
            row = connection.execute(
                text(
                    """
                    SELECT status, expires_at
                    FROM cli_device_authorization
                    WHERE user_code_hash=:user_code_hash
                    """
                ),
                {"user_code_hash": self._digest("user", normalized)},
            ).mappings().first()
        if not row:
            return {"status": "invalid"}
        if str(row["expires_at"]) <= _timestamp(current):
            return {"status": "expired"}
        return {"status": "already_processed"}

    def consume_with_session(
        self,
        *,
        device_code: str,
        session_expires_at: str,
        user_agent: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now()
        device_code_hash = self._digest("device", device_code)
        with self.database.engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT id, user_id, status, expires_at
                    FROM cli_device_authorization
                    WHERE device_code_hash=:device_code_hash
                    """
                ),
                {"device_code_hash": device_code_hash},
            ).mappings().first()
            if not row:
                return {"status": "invalid"}
            if str(row["expires_at"]) <= _timestamp(current):
                connection.execute(
                    text(
                        """
                        UPDATE cli_device_authorization SET status='expired'
                        WHERE id=:id AND status IN ('pending', 'approved')
                        """
                    ),
                    {"id": row["id"]},
                )
                return {"status": "expired"}
            if row["status"] != "approved":
                return {"status": str(row["status"])}
            user_exists = connection.execute(
                text("SELECT id FROM app_user WHERE id=:id"),
                {"id": row["user_id"]},
            ).first()
            if not user_exists:
                return {"status": "invalid"}
            consumed = connection.execute(
                text(
                    """
                    UPDATE cli_device_authorization
                    SET status='consumed', consumed_at=:consumed_at
                    WHERE id=:id AND status='approved'
                    """
                ),
                {"id": row["id"], "consumed_at": _timestamp(current)},
            )
            if consumed.rowcount != 1:
                return {"status": "consumed"}
            session_token = secrets.token_urlsafe(36)
            connection.execute(
                text(
                    """
                    INSERT INTO auth_session(
                        id, user_id, user_agent, expires_at, created_at, last_seen_at
                    ) VALUES (
                        :id, :user_id, :user_agent, :expires_at, :created_at, :last_seen_at
                    )
                    """
                ),
                {
                    "id": session_token,
                    "user_id": int(row["user_id"]),
                    "user_agent": user_agent[:500],
                    "expires_at": session_expires_at,
                    "created_at": _timestamp(current),
                    "last_seen_at": _timestamp(current),
                },
            )
            return {
                "status": "authorized",
                "userId": int(row["user_id"]),
                "sessionToken": session_token,
            }
