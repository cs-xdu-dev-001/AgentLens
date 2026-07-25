from __future__ import annotations

import json
import secrets
from typing import Any

MCP_MAX_EXPOSED_TOOLS = 32


class McpConfigService:
    def __init__(self, *, fetch_one, fetch_all, execute, execute_rowcount, cipher, now_str):
        self.fetch_one, self.fetch_all = fetch_one, fetch_all
        self.execute, self.execute_rowcount = execute, execute_rowcount
        self.cipher, self.now_str = cipher, now_str

    def encrypt_credentials(self, value: dict[str, Any]) -> str:
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    def decrypt_credentials(self, value: str | None) -> dict[str, Any]:
        try:
            raw = self.cipher.decrypt(value)
            if not raw: return {}
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def normalize(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"id": row["id"], "userId": row["user_id"], "name": row["name"], "slug": row["slug"], "url": row["url"], "authType": row["auth_type"], "enabled": bool(row.get("enabled", 1)), "status": row.get("status") or "disconnected", "configured": bool(self.decrypt_credentials(row.get("credentials_cipher"))), "tools": self._json(row.get("tools_json"), []), "enabledTools": self._json(row.get("enabled_tools_json"), []), "lastErrorCode": row.get("last_error_code"), "lastConnectedAt": row.get("last_connected_at"), "createdAt": str(row.get("created_at", "")), "updatedAt": str(row.get("updated_at", ""))}

    @staticmethod
    def _json(value, default):
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
            return parsed if parsed is not None else default
        except Exception:
            return default

    def _row(self, user_id, server_id):
        return self.fetch_one("SELECT * FROM mcp_server WHERE id=:id AND user_id=:user_id", {"id": server_id, "user_id": user_id})

    def list_for_user(self, user_id):
        return [self.normalize(r) for r in self.fetch_all("SELECT * FROM mcp_server WHERE user_id=:user_id ORDER BY name", {"user_id": user_id})]

    def get_owned(self, user_id, server_id):
        r = self._row(user_id, server_id)
        return self.normalize(r) if r else None

    def create_server(self, user_id, *, name, slug, url, auth_type, enabled=True):
        now = self.now_str(); self.execute("INSERT INTO mcp_server(user_id,name,slug,url,auth_type,enabled,status,created_at,updated_at) VALUES (:user_id,:name,:slug,:url,:auth_type,:enabled,'disconnected',:created_at,:updated_at)", {"user_id": user_id, "name": name, "slug": slug, "url": url, "auth_type": auth_type, "enabled": int(enabled), "created_at": now, "updated_at": now})
        return self.get_owned(user_id, self.fetch_one("SELECT * FROM mcp_server WHERE user_id=:user_id AND slug=:slug", {"user_id": user_id, "slug": slug})["id"])

    def update_server(self, user_id, server_id, **fields):
        allowed = {"name", "slug", "url", "auth_type", "enabled"}; vals = {k: v for k, v in fields.items() if k in allowed}
        if vals:
            vals.update({"id": server_id, "user_id": user_id, "updated_at": self.now_str()}); self.execute("UPDATE mcp_server SET " + ", ".join(f"{k}=:{k}" for k in vals if k not in {"id", "user_id"}) + " WHERE id=:id AND user_id=:user_id", vals)
        return self.get_owned(user_id, server_id)

    def delete_server(self, user_id, server_id):
        self.execute("DELETE FROM mcp_oauth_session WHERE server_id=:server_id AND user_id=:user_id", {"server_id": server_id, "user_id": user_id}); self.execute("DELETE FROM mcp_server WHERE id=:id AND user_id=:user_id", {"id": server_id, "user_id": user_id})

    def save_credentials(self, user_id, server_id, credentials):
        self.execute("UPDATE mcp_server SET credentials_cipher=:credentials_cipher, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"credentials_cipher": self.encrypt_credentials(credentials), "updated_at": self.now_str(), "id": server_id, "user_id": user_id}); return self.get_owned(user_id, server_id)

    def clear_credentials(self, user_id, server_id):
        self.execute("UPDATE mcp_server SET credentials_cipher=NULL, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"updated_at": self.now_str(), "id": server_id, "user_id": user_id})
        return self.get_owned(user_id, server_id)

    def set_enabled_tools(self, user_id, server_id, enabled_tools):
        vals = list(dict.fromkeys(enabled_tools or []))
        if len(vals) > MCP_MAX_EXPOSED_TOOLS: raise ValueError("too many enabled tools")
        self.execute("UPDATE mcp_server SET enabled_tools_json=:enabled_tools_json, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"enabled_tools_json": json.dumps(vals, ensure_ascii=False), "updated_at": self.now_str(), "id": server_id, "user_id": user_id})
        return self.get_owned(user_id, server_id)

    def secret(self, user_id, server_id):
        r = self._row(user_id, server_id)
        if not r:
            return None
        result = {k: v for k, v in r.items() if k != "credentials_cipher"}
        result["credentials"] = self.decrypt_credentials(r.get("credentials_cipher"))
        return result

    def save_tool_snapshot(self, user_id, server_id, tools):
        r = self._row(user_id, server_id); old = self._json(r.get("enabled_tools_json"), None) if r else None; names = [t.get("name", t) if isinstance(t, dict) else t for t in tools]; enabled = old if old is not None else (names if len(names) <= MCP_MAX_EXPOSED_TOOLS else []); enabled = [n for n in enabled if n in names]
        self.execute("UPDATE mcp_server SET tools_json=:tools_json, enabled_tools_json=:enabled_tools_json, updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"tools_json": json.dumps(tools, ensure_ascii=False), "enabled_tools_json": json.dumps(enabled, ensure_ascii=False), "updated_at": self.now_str(), "id": server_id, "user_id": user_id}); return self.get_owned(user_id, server_id)

    def set_status(self, user_id, server_id, status, *, error_code=None):
        self.execute("UPDATE mcp_server SET status=:status,last_error_code=:error_code,updated_at=:updated_at WHERE id=:id AND user_id=:user_id", {"status": status, "error_code": error_code, "updated_at": self.now_str(), "id": server_id, "user_id": user_id}); return self.get_owned(user_id, server_id)

    def create_oauth_session(self, user_id, server_id, *, state_hash, pkce_verifier_cipher, return_to, expires_at, now=None):
        if not self._row(user_id, server_id):
            raise ValueError("MCP server does not belong to user")
        now = now or self.now_str()
        session_id = secrets.token_urlsafe(32)
        self.execute(
            "INSERT INTO mcp_oauth_session(id,user_id,server_id,state_hash,pkce_verifier_cipher,return_to,expires_at,created_at) VALUES (:id,:user_id,:server_id,:state_hash,:pkce_verifier_cipher,:return_to,:expires_at,:created_at)",
            {
                "id": session_id,
                "user_id": user_id,
                "server_id": server_id,
                "state_hash": state_hash,
                "pkce_verifier_cipher": pkce_verifier_cipher,
                "return_to": return_to,
                "expires_at": expires_at,
                "created_at": now,
            },
        )
        return self.fetch_one("SELECT * FROM mcp_oauth_session WHERE id=:id", {"id": session_id})

    def consume_oauth_session(self, user_id, session_id, state_hash):
        now = self.now_str()
        params = {"id":session_id,"user_id":user_id,"state_hash":state_hash,"now":now}
        row=self.fetch_one("SELECT * FROM mcp_oauth_session WHERE id=:id AND user_id=:user_id AND state_hash=:state_hash AND expires_at > :now", params)
        if not row: return None
        return row if self.execute_rowcount("DELETE FROM mcp_oauth_session WHERE id=:id AND user_id=:user_id AND state_hash=:state_hash AND expires_at > :now", params) == 1 else None

    def consume_oauth_session_by_state(self, user_id, state_hash, now=None):
        now = now or self.now_str(); params = {"user_id": user_id, "state_hash": state_hash, "now": now}
        row = self.fetch_one("SELECT * FROM mcp_oauth_session WHERE user_id=:user_id AND state_hash=:state_hash AND expires_at > :now", params)
        if not row: return None
        return row if self.execute_rowcount("DELETE FROM mcp_oauth_session WHERE id=:id AND user_id=:user_id AND state_hash=:state_hash AND expires_at > :now", {**params, "id": row["id"]}) == 1 else None

    def delete_expired_oauth_sessions(self, user_id, now=None):
        return self.execute_rowcount("DELETE FROM mcp_oauth_session WHERE user_id=:user_id AND expires_at <= :now", {"user_id": user_id, "now": now or self.now_str()})
