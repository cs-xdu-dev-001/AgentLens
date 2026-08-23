import base64
import hashlib
import json
import sqlite3
import sys
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.mcp_config import McpConfigService
from knowflow.services.mcp_oauth import (
    McpOAuthCoordinator,
    McpOAuthError,
    _PinnedSyncTransport,
)


NOW = datetime(2026, 7, 24, 12, 0, 0)
NOW_STR = "2026-07-24 12:00:00"
RESOURCE_URL = "https://mcp.example.com/mcp"
RESOURCE_METADATA_URL = (
    "https://mcp.example.com/.well-known/oauth-protected-resource"
)
ISSUER = "https://auth.example.com/tenant"
AS_METADATA_URL = (
    "https://auth.example.com/"
    ".well-known/oauth-authorization-server/tenant"
)
AUTHORIZATION_URL = "https://auth.example.com/authorize?existing=1"
TOKEN_URL = "https://auth.example.com/token"
REGISTER_URL = "https://auth.example.com/register"
REVOKE_URL = "https://auth.example.com/revoke"


class Cipher:
    def __init__(self):
        self.fernet = Fernet(Fernet.generate_key())

    def encrypt(self, value):
        return self.fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value):
        try:
            return self.fernet.decrypt(
                (value or "").encode("ascii")
            ).decode("utf-8")
        except Exception:
            return ""


class FakeResponse:
    def __init__(self, status=200, data=None, headers=None, raw=None):
        self.status_code = status
        self._data = data
        self.headers = headers or {}
        self.content = (
            raw
            if raw is not None
            else (
                json.dumps(data).encode("utf-8")
                if data is not None
                else b""
            )
        )
        self.text = self.content.decode("utf-8", errors="replace")

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


class FakeHttp:
    def __init__(self):
        self.routes = {}
        self.calls = []
        self.clients = []

    def queue(self, method, url, response):
        self.routes.setdefault((method.upper(), url), []).append(response)

    def factory(self):
        client = FakeClient(self)
        self.clients.append(client)
        return client


class FakeClient:
    def __init__(self, router):
        self.router = router
        self.closed = False

    def request(self, method, url, **kwargs):
        key = (method.upper(), url)
        self.router.calls.append(
            {"method": key[0], "url": url, **kwargs}
        )
        queued = self.router.routes.get(key) or []
        if not queued:
            raise AssertionError(f"Unexpected request: {key}")
        return queued.pop(0)

    def close(self):
        self.closed = True


class RecordingTransport(httpx.BaseTransport):
    def __init__(self):
        self.requests = []
        self.closed = 0

    def handle_request(self, request):
        self.requests.append(request)
        return httpx.Response(200, content=b"ok", request=request)

    def close(self):
        self.closed += 1


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE mcp_server (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                slug TEXT NOT NULL,
                url TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'disconnected',
                credentials_cipher TEXT,
                tools_json TEXT,
                enabled_tools_json TEXT,
                last_error_code TEXT,
                last_connected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, slug)
            );
            CREATE TABLE mcp_oauth_session (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                server_id INTEGER NOT NULL,
                state_hash TEXT NOT NULL UNIQUE,
                pkce_verifier_cipher TEXT NOT NULL,
                return_to TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.cipher = Cipher()

        def fetch_all(sql, params=None):
            return [
                dict(row)
                for row in self.db.execute(sql, params or {}).fetchall()
            ]

        def fetch_one(sql, params=None):
            row = self.db.execute(sql, params or {}).fetchone()
            return dict(row) if row else None

        def execute(sql, params=None):
            cursor = self.db.execute(sql, params or {})
            self.db.commit()
            return cursor.lastrowid

        def execute_rowcount(sql, params=None):
            cursor = self.db.execute(sql, params or {})
            self.db.commit()
            return cursor.rowcount

        self.fetch_one = fetch_one
        self.configs = McpConfigService(
            fetch_one=fetch_one,
            fetch_all=fetch_all,
            execute=execute,
            execute_rowcount=execute_rowcount,
            cipher=self.cipher,
            now_str=lambda: NOW_STR,
        )
        self.server = self.configs.create_server(
            1,
            name="Example",
            slug="example",
            url=RESOURCE_URL,
            auth_type="oauth",
        )
        self.other = self.configs.create_server(
            2,
            name="Example",
            slug="example",
            url=RESOURCE_URL,
            auth_type="oauth",
        )
        self.http = FakeHttp()
        self.oauth = McpOAuthCoordinator(
            configs=self.configs,
            base_url="https://app.example.com",
            http_client_factory=self.http.factory,
            now=lambda: NOW,
            resolver=lambda host, port: ["93.184.216.34"],
        )

    def tearDown(self):
        self.db.close()

    @staticmethod
    def server_metadata(**overrides):
        value = {
            "issuer": ISSUER,
            "authorization_endpoint": AUTHORIZATION_URL,
            "token_endpoint": TOKEN_URL,
            "registration_endpoint": REGISTER_URL,
            "revocation_endpoint": REVOKE_URL,
            "response_types_supported": ["code"],
            "code_challenge_methods_supported": ["S256"],
        }
        value.update(overrides)
        return value

    def queue_discovery(self, authorization_servers=None, metadata=None):
        self.http.queue(
            "GET",
            RESOURCE_URL,
            FakeResponse(
                401,
                headers={
                    "WWW-Authenticate": (
                        "Bearer resource_metadata="
                        f'"{RESOURCE_METADATA_URL}"'
                    )
                },
            ),
        )
        self.http.queue(
            "GET",
            RESOURCE_METADATA_URL,
            FakeResponse(
                200,
                {
                    "authorization_servers": (
                        authorization_servers or [ISSUER]
                    )
                },
            ),
        )
        self.http.queue(
            "GET",
            AS_METADATA_URL,
            FakeResponse(
                200,
                metadata or self.server_metadata(),
            ),
        )

    def start_dynamic(self):
        self.queue_discovery()
        self.http.queue(
            "POST",
            REGISTER_URL,
            FakeResponse(
                201,
                {
                    "client_id": "dynamic-client",
                    "client_secret": "dynamic-secret",
                },
            ),
        )
        return self.oauth.start_authorization(
            1,
            self.server["id"],
            "https://app.example.com/settings/tools",
        )

    def test_dynamic_start_uses_pkce_and_only_persists_hash(self):
        self.configs.create_oauth_session(
            1,
            self.server["id"],
            state_hash="old-state",
            pkce_verifier_cipher=self.configs.encrypt_credentials(
                {"verifier": "old-verifier"}
            ),
            return_to="/",
            expires_at="2020-01-01 00:00:00",
        )
        started = self.start_dynamic()
        query = parse_qs(urlsplit(started["authorizationUrl"]).query)
        self.assertEqual(query["existing"], ["1"])
        self.assertEqual(query["response_type"], ["code"])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["resource"], [RESOURCE_URL])
        self.assertEqual(query["state"], [started["state"]])

        rows = self.db.execute(
            "SELECT * FROM mcp_oauth_session"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        row = dict(rows[0])
        self.assertEqual(
            row["state_hash"],
            hashlib.sha256(
                started["state"].encode("utf-8")
            ).hexdigest(),
        )
        self.assertNotIn(started["state"], row["state_hash"])
        payload = self.configs.decrypt_credentials(
            row["pkce_verifier_cipher"]
        )
        self.assertNotIn(
            payload["verifier"],
            row["pkce_verifier_cipher"],
        )
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(
                payload["verifier"].encode("ascii")
            ).digest()
        ).rstrip(b"=").decode("ascii")
        self.assertEqual(query["code_challenge"], [expected])
        self.assertTrue(all(client.closed for client in self.http.clients))

    def test_manual_client_id_skips_dynamic_registration(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {
                "client_id": "manual-client",
                "client_secret": "manual-secret",
            },
        )
        self.queue_discovery()
        started = self.oauth.start_authorization(
            1,
            self.server["id"],
        )
        query = parse_qs(urlsplit(started["authorizationUrl"]).query)
        self.assertEqual(query["client_id"], ["manual-client"])
        self.assertNotIn(
            ("POST", REGISTER_URL),
            [(call["method"], call["url"]) for call in self.http.calls],
        )

    def test_discovery_skips_non_https_issuer(self):
        self.queue_discovery(
            authorization_servers=[
                "http://unsafe.example.com",
                ISSUER,
            ]
        )
        value = self.oauth.discover_metadata(RESOURCE_URL)
        self.assertEqual(value["issuer"], ISSUER)

    def test_discovery_rejects_missing_s256_and_private_metadata(self):
        self.queue_discovery(
            metadata=self.server_metadata(
                code_challenge_methods_supported=[]
            )
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.discover_metadata(RESOURCE_URL)
        self.assertEqual(
            caught.exception.code,
            "unsupported_authorization_server",
        )

        private_http = FakeHttp()
        private_http.queue(
            "GET",
            RESOURCE_URL,
            FakeResponse(
                401,
                headers={
                    "WWW-Authenticate": (
                        'Bearer resource_metadata="'
                        'https://127.0.0.1/metadata"'
                    )
                },
            ),
        )
        private = McpOAuthCoordinator(
            configs=self.configs,
            base_url="https://app.example.com",
            http_client_factory=private_http.factory,
            now=lambda: NOW,
            resolver=lambda host, port: ["93.184.216.34"],
        )
        with self.assertRaises(McpOAuthError) as caught:
            private.discover_metadata(RESOURCE_URL)
        self.assertEqual(caught.exception.code, "invalid_remote_url")

    def test_metadata_and_registration_http_errors_are_rejected(self):
        self.http.queue(
            "GET",
            RESOURCE_URL,
            FakeResponse(
                401,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer resource_metadata="{RESOURCE_METADATA_URL}"'
                    )
                },
            ),
        )
        self.http.queue(
            "GET",
            RESOURCE_METADATA_URL,
            FakeResponse(500, {"error": "down"}),
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.discover_metadata(RESOURCE_URL)
        self.assertEqual(caught.exception.code, "resource_metadata_failed")

        self.queue_discovery()
        self.http.queue(
            "POST",
            REGISTER_URL,
            FakeResponse(400, {"error": "invalid_client_metadata"}),
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.start_authorization(1, self.server["id"])
        self.assertEqual(caught.exception.code, "registration_failed")

    def test_complete_exchanges_code_once_and_sets_expiry(self):
        started = self.start_dynamic()
        session = dict(
            self.db.execute(
                "SELECT * FROM mcp_oauth_session"
            ).fetchone()
        )
        payload = self.configs.decrypt_credentials(
            session["pkce_verifier_cipher"]
        )
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(
                200,
                {
                    "access_token": "access-one",
                    "refresh_token": "refresh-one",
                    "expires_in": 3600,
                },
            ),
        )
        result = self.oauth.complete_authorization(
            1,
            started["state"],
            code="authorization-code",
        )
        self.assertEqual(result["status"], "connected")
        token_call = self.http.calls[-1]
        self.assertEqual(
            token_call["data"]["code_verifier"],
            payload["verifier"],
        )
        self.assertEqual(token_call["data"]["resource"], RESOURCE_URL)
        credentials = self.configs.secret(
            1,
            self.server["id"],
        )["credentials"]
        self.assertEqual(credentials["access_token"], "access-one")
        self.assertEqual(
            credentials["expires_at"],
            NOW.timestamp() + 3600,
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                1,
                started["state"],
                code="authorization-code",
            )
        self.assertEqual(caught.exception.code, "invalid_state")

    def test_oauth_state_uses_one_clock_across_server_timezones(self):
        self.configs.now_str = lambda: "2026-07-24 20:00:00"
        started = self.start_dynamic()
        session = dict(
            self.db.execute(
                "SELECT * FROM mcp_oauth_session"
            ).fetchone()
        )
        self.assertEqual(session["created_at"], NOW_STR)
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(
                200,
                {
                    "access_token": "timezone-access",
                    "expires_in": 3600,
                },
            ),
        )

        result = self.oauth.complete_authorization(
            1,
            started["state"],
            code="timezone-code",
        )

        self.assertEqual(result["status"], "connected")

    def test_denial_cross_user_and_expired_state_fail_safely(self):
        started = self.start_dynamic()
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                2,
                started["state"],
                code="wrong-user-code",
            )
        self.assertEqual(caught.exception.code, "invalid_state")
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                1,
                started["state"],
                error="access_denied",
            )
        self.assertEqual(caught.exception.code, "authorization_denied")
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                1,
                started["state"],
                code="cannot-reuse",
            )
        self.assertEqual(caught.exception.code, "invalid_state")

        self.configs.create_oauth_session(
            1,
            self.server["id"],
            state_hash=hashlib.sha256(b"expired").hexdigest(),
            pkce_verifier_cipher=self.configs.encrypt_credentials(
                {"verifier": "v"}
            ),
            return_to="/",
            expires_at="2020-01-01 00:00:00",
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                1,
                "expired",
                code="code",
            )
        self.assertEqual(caught.exception.code, "invalid_state")

    def test_token_exchange_http_error_does_not_save_token(self):
        started = self.start_dynamic()
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(400, {"error": "invalid_grant"}),
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.complete_authorization(
                1,
                started["state"],
                code="bad-code",
            )
        self.assertEqual(caught.exception.code, "token_exchange_failed")
        credentials = self.configs.secret(
            1,
            self.server["id"],
        )["credentials"]
        self.assertNotIn("access_token", credentials)

    def test_refreshes_expiring_token_and_preserves_refresh_token(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {
                "client_id": "client",
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expires_at": NOW.timestamp() + 30,
                "metadata": {"token_endpoint": TOKEN_URL},
            },
        )
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(
                200,
                {"access_token": "new-access", "expires_in": 600},
            ),
        )
        token = self.oauth.ensure_access_token(1, self.server["id"])
        self.assertEqual(token, "new-access")
        saved = self.configs.secret(
            1,
            self.server["id"],
        )["credentials"]
        self.assertEqual(saved["refresh_token"], "old-refresh")
        self.assertEqual(saved["expires_at"], NOW.timestamp() + 600)

    def test_force_refresh_rotates_refresh_token_and_supports_server_dict(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {
                "client_id": "client",
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "expires_at": NOW.timestamp() + 3600,
                "metadata": {"token_endpoint": TOKEN_URL},
            },
        )
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(
                200,
                {
                    "access_token": "forced-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 300,
                },
            ),
        )
        server = self.configs.secret(1, self.server["id"])
        headers = self.oauth.authorization_headers(
            server,
            force_refresh=True,
        )
        self.assertEqual(
            headers,
            {"Authorization": "Bearer forced-access"},
        )
        saved = self.configs.secret(
            1,
            self.server["id"],
        )["credentials"]
        self.assertEqual(
            saved["refresh_token"],
            "rotated-refresh",
        )

    def test_server_dict_is_reloaded_instead_of_trusting_credentials(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {"access_token": "stored-access"},
        )
        forged = {
            "id": self.server["id"],
            "user_id": 1,
            "url": "https://attacker.invalid/mcp",
            "credentials": {"access_token": "forged-access"},
        }
        self.assertEqual(
            self.oauth.authorization_headers(forged),
            {"Authorization": "Bearer stored-access"},
        )
        forged["user_id"] = 2
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.authorization_headers(forged)
        self.assertEqual(caught.exception.code, "not_configured")

    def test_access_token_without_expiry_is_valid_until_forced(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {"access_token": "no-expiry"},
        )
        self.assertEqual(
            self.oauth.ensure_access_token(1, self.server["id"]),
            "no-expiry",
        )

    def test_invalid_grant_sets_reauthorize(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {
                "client_id": "client",
                "access_token": "old",
                "refresh_token": "invalid-refresh",
                "expires_at": 0,
                "metadata": {"token_endpoint": TOKEN_URL},
            },
        )
        self.http.queue(
            "POST",
            TOKEN_URL,
            FakeResponse(400, {"error": "invalid_grant"}),
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.ensure_access_token(1, self.server["id"])
        self.assertEqual(caught.exception.code, "reauthorize")
        owned = self.configs.get_owned(1, self.server["id"])
        self.assertEqual(owned["status"], "reauthorize")
        self.assertEqual(owned["lastErrorCode"], "invalid_grant")

    def test_revoke_is_best_effort(self):
        self.configs.save_credentials(
            1,
            self.server["id"],
            {
                "client_id": "client",
                "access_token": "access",
                "refresh_token": "refresh",
                "metadata": {"revocation_endpoint": REVOKE_URL},
            },
        )
        self.http.queue(
            "POST",
            REVOKE_URL,
            FakeResponse(503, {"error": "unavailable"}),
        )
        self.assertEqual(
            self.oauth.revoke_credentials(1, self.server["id"]),
            {"ok": False, "code": "revoke_failed"},
        )
        self.http.queue(
            "POST",
            REVOKE_URL,
            FakeResponse(200, {}),
        )
        self.assertEqual(
            self.oauth.revoke_credentials(1, self.server["id"]),
            {"ok": True},
        )

    def test_redirect_is_rejected(self):
        self.http.queue(
            "GET",
            RESOURCE_URL,
            FakeResponse(302, headers={"Location": "https://other.example"}),
        )
        with self.assertRaises(McpOAuthError) as caught:
            self.oauth.discover_metadata(RESOURCE_URL)
        self.assertEqual(caught.exception.code, "redirect_rejected")

    def test_pinned_transport_preserves_authority_and_rechecks_dns(self):
        delegate = RecordingTransport()
        answers = iter(
            [["93.184.216.34"], ["10.0.0.1"]]
        )
        transport = _PinnedSyncTransport(
            resolver=lambda host, port: next(answers),
            delegate=delegate,
        )
        request = httpx.Request(
            "POST",
            "https://auth.example.com:8443/token",
            content=b"payload",
        )
        response = transport.handle_request(request)
        self.assertEqual(response.status_code, 200)
        pinned = delegate.requests[0]
        self.assertEqual(pinned.url.host, "93.184.216.34")
        self.assertEqual(
            pinned.headers["host"],
            "auth.example.com:8443",
        )
        self.assertEqual(
            pinned.extensions["sni_hostname"],
            "auth.example.com",
        )
        self.assertEqual(request.url.host, "auth.example.com")
        with self.assertRaises(ValueError):
            transport.handle_request(request)
        self.assertEqual(len(delegate.requests), 1)
        transport.close()
        self.assertEqual(delegate.closed, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
