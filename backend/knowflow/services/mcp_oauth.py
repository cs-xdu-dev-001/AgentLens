from __future__ import annotations

import base64
import hashlib
import math
import re
import secrets
from datetime import datetime, timedelta
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .mcp_security import (
    resolve_remote_addresses,
    validate_remote_url,
)


class McpOAuthError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        return_to: str | None = None,
    ):
        self.code = code
        self.return_to = return_to
        super().__init__(message or code)


class _PinnedSyncTransport(httpx.BaseTransport):
    """Resolve, validate, and pin every outbound OAuth request."""

    def __init__(
        self,
        resolver: Callable[..., Any] | None = None,
        allow_private: bool = False,
        delegate: httpx.BaseTransport | None = None,
    ):
        self.resolver = resolver
        self.allow_private = allow_private
        self.delegate = delegate or httpx.HTTPTransport(
            trust_env=False,
            retries=0,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        port = request.url.port or (
            443 if request.url.scheme == "https" else 80
        )
        addresses = resolve_remote_addresses(
            host,
            port,
            self.resolver,
            self.allow_private,
        )
        headers = request.headers.copy()
        if "host" not in headers:
            headers["host"] = request.url.netloc.decode("ascii")
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = host
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=addresses[0]),
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        return self.delegate.handle_request(pinned)

    def close(self) -> None:
        self.delegate.close()


class McpOAuthCoordinator:
    def __init__(
        self,
        *,
        configs,
        base_url: str,
        http_client_factory: Callable[[], Any] | None = None,
        now: Callable[[], datetime] | None = None,
        resolver: Callable[..., Any] | None = None,
        allow_private: bool = False,
        timeout: int = 10,
        max_bytes: int = 1024 * 1024,
    ):
        self.configs = configs
        self.base_url = base_url.rstrip("/")
        self.http_client_factory = http_client_factory
        self.now = now or datetime.utcnow
        self.resolver = resolver
        self.allow_private = allow_private
        self.timeout = timeout
        self.max_bytes = max_bytes

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url}/api/mcp/oauth/callback"

    def _validate_url(self, value: str) -> str:
        try:
            return validate_remote_url(
                value,
                resolver=self.resolver,
                allow_private=self.allow_private,
            )
        except Exception as exc:
            raise McpOAuthError("invalid_remote_url") from exc

    def _client(self):
        if self.http_client_factory:
            return self.http_client_factory()
        return httpx.Client(
            trust_env=False,
            follow_redirects=False,
            timeout=self.timeout,
            transport=_PinnedSyncTransport(
                resolver=self.resolver,
                allow_private=self.allow_private,
            ),
        )

    def _request(self, method: str, url: str, **kwargs):
        self._validate_url(url)
        client = self._client()
        try:
            response = client.request(
                method,
                url,
                timeout=self.timeout,
                **kwargs,
            )
            content = bytes(getattr(response, "content", b""))
            if 300 <= int(response.status_code) < 400:
                raise McpOAuthError("redirect_rejected")
            if len(content) > self.max_bytes:
                raise McpOAuthError("response_too_large")
            return response
        finally:
            try:
                client.close()
            except Exception:
                pass

    @staticmethod
    def _is_success(response) -> bool:
        return 200 <= int(response.status_code) < 300

    @staticmethod
    def _json_object(response) -> dict[str, Any]:
        try:
            value = response.json()
        except Exception as exc:
            raise McpOAuthError("invalid_response") from exc
        if not isinstance(value, dict):
            raise McpOAuthError("invalid_response")
        return value

    @staticmethod
    def _resource_metadata_url(header: str) -> str:
        match = re.search(
            r"resource_metadata\s*=\s*(?:\"([^\"]+)\"|([^,\s]+))",
            header or "",
            flags=re.IGNORECASE,
        )
        if not match:
            raise McpOAuthError("missing_resource_metadata")
        return str(match.group(1) or match.group(2) or "")

    @staticmethod
    def _well_known_url(issuer: str) -> str:
        parsed = urlsplit(issuer)
        suffix = parsed.path.rstrip("/")
        path = "/.well-known/oauth-authorization-server"
        if suffix:
            path += suffix
        return urlunsplit(
            (parsed.scheme, parsed.netloc, path, "", "")
        )

    def discover_metadata(self, resource_url: str) -> dict[str, Any]:
        resource_url = self._validate_url(resource_url)
        resource_response = self._request(
            "GET",
            resource_url,
            headers={"Accept": "application/json"},
        )
        if int(resource_response.status_code) != 401:
            raise McpOAuthError("resource_unauthorized")

        metadata_url = self._resource_metadata_url(
            str(
                getattr(resource_response, "headers", {}).get(
                    "WWW-Authenticate",
                    "",
                )
            )
        )
        metadata_response = self._request("GET", metadata_url)
        if not self._is_success(metadata_response):
            raise McpOAuthError("resource_metadata_failed")
        resource_metadata = self._json_object(metadata_response)

        issuer = ""
        for candidate in (
            resource_metadata.get("authorization_servers") or []
        ):
            if not isinstance(candidate, str):
                continue
            try:
                if urlsplit(candidate).scheme.lower() != "https":
                    continue
                issuer = self._validate_url(candidate).rstrip("/")
                break
            except McpOAuthError:
                continue
        if not issuer:
            raise McpOAuthError("missing_authorization_server")

        server_metadata_response = self._request(
            "GET",
            self._well_known_url(issuer),
        )
        if not self._is_success(server_metadata_response):
            raise McpOAuthError("authorization_metadata_failed")
        server_metadata = self._json_object(server_metadata_response)

        returned_issuer = self._validate_url(
            str(server_metadata.get("issuer") or "")
        ).rstrip("/")
        if returned_issuer != issuer:
            raise McpOAuthError("unsupported_authorization_server")
        if "code" not in (
            server_metadata.get("response_types_supported") or []
        ):
            raise McpOAuthError("unsupported_authorization_server")
        if "S256" not in (
            server_metadata.get("code_challenge_methods_supported") or []
        ):
            raise McpOAuthError("unsupported_authorization_server")

        for required in ("authorization_endpoint", "token_endpoint"):
            if not server_metadata.get(required):
                raise McpOAuthError("unsupported_authorization_server")
        for field in (
            "authorization_endpoint",
            "token_endpoint",
            "registration_endpoint",
            "revocation_endpoint",
        ):
            if server_metadata.get(field):
                server_metadata[field] = self._validate_url(
                    str(server_metadata[field])
                )

        return {
            **resource_metadata,
            **server_metadata,
            "resource": resource_url,
            "resource_metadata_url": metadata_url,
            "issuer": issuer,
        }

    def start_authorization(
        self,
        user_id: int,
        server_id: Any,
        return_to: str = "/",
    ) -> dict[str, str]:
        server = self.configs.secret(user_id, server_id)
        if not server:
            raise McpOAuthError("not_found")
        oauth_now = self.now().replace(microsecond=0)
        oauth_now_str = oauth_now.isoformat(sep=" ")
        self.configs.delete_expired_oauth_sessions(
            user_id,
            now=oauth_now_str,
        )

        credentials = server.get("credentials") or {}
        metadata = self.discover_metadata(server["url"])
        client_id = credentials.get("client_id")
        client_secret = credentials.get("client_secret")

        if not client_id:
            registration_endpoint = metadata.get(
                "registration_endpoint"
            )
            if not registration_endpoint:
                raise McpOAuthError("registration_unavailable")
            registration_response = self._request(
                "POST",
                registration_endpoint,
                json={
                    "client_name": "AgentLens",
                    "redirect_uris": [self.redirect_uri],
                    "grant_types": ["authorization_code"],
                    "response_types": ["code"],
                },
            )
            if not self._is_success(registration_response):
                raise McpOAuthError("registration_failed")
            registration = self._json_object(registration_response)
            client_id = registration.get("client_id")
            client_secret = registration.get("client_secret")
            if not isinstance(client_id, str) or not client_id:
                raise McpOAuthError("registration_failed")

        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(
            state.encode("utf-8")
        ).hexdigest()
        expires_at = (
            oauth_now + timedelta(minutes=10)
        ).isoformat(sep=" ")

        session_payload = {
            "verifier": verifier,
            "metadata": metadata,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        self.configs.create_oauth_session(
            user_id,
            server_id,
            state_hash=state_hash,
            pkce_verifier_cipher=self.configs.encrypt_credentials(
                session_payload
            ),
            return_to=return_to,
            expires_at=expires_at,
            now=oauth_now_str,
        )
        saved_credentials = {
            **credentials,
            "client_id": client_id,
            "metadata": metadata,
        }
        if client_secret:
            saved_credentials["client_secret"] = client_secret
        self.configs.save_credentials(
            user_id,
            server_id,
            saved_credentials,
        )

        authorization_endpoint = urlsplit(
            metadata["authorization_endpoint"]
        )
        query = dict(
            parse_qsl(
                authorization_endpoint.query,
                keep_blank_values=True,
            )
        )
        query.update(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": self.redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "resource": server["url"],
            }
        )
        authorization_url = urlunsplit(
            (
                authorization_endpoint.scheme,
                authorization_endpoint.netloc,
                authorization_endpoint.path,
                urlencode(query),
                "",
            )
        )
        return {
            "authorizationUrl": authorization_url,
            "state": state,
        }

    def _merge_token(
        self,
        previous: dict[str, Any],
        token: dict[str, Any],
    ) -> dict[str, Any]:
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise McpOAuthError("invalid_response")
        merged = {**previous, **token}
        if not token.get("refresh_token") and previous.get(
            "refresh_token"
        ):
            merged["refresh_token"] = previous["refresh_token"]
        if token.get("expires_in") is not None:
            try:
                seconds = float(token["expires_in"])
            except (TypeError, ValueError) as exc:
                raise McpOAuthError("invalid_response") from exc
            if not math.isfinite(seconds) or seconds < 0:
                raise McpOAuthError("invalid_response")
            merged["expires_at"] = self.now().timestamp() + seconds
        else:
            merged.pop("expires_at", None)
        merged["token_type"] = str(
            token.get("token_type")
            or previous.get("token_type")
            or "Bearer"
        )
        return merged

    def complete_authorization(
        self,
        user_id: int,
        state: str,
        code: str | None = None,
        error: str | None = None,
    ):
        if not isinstance(state, str) or not state:
            raise McpOAuthError("invalid_state")
        state_hash = hashlib.sha256(
            state.encode("utf-8")
        ).hexdigest()
        session = self.configs.consume_oauth_session_by_state(
            user_id,
            state_hash,
            now=self.now().replace(microsecond=0).isoformat(sep=" "),
        )
        if not session:
            raise McpOAuthError("invalid_state")
        return_to = session.get("return_to")
        try:
            if error or not code:
                raise McpOAuthError("authorization_denied")

            session_payload = self.configs.decrypt_credentials(
                session["pkce_verifier_cipher"]
            )
            server = self.configs.secret(
                user_id,
                session["server_id"],
            )
            if not server:
                raise McpOAuthError("not_found")
            metadata = session_payload.get("metadata") or {}
            verifier = session_payload.get("verifier")
            client_id = session_payload.get("client_id")
            if not verifier or not client_id or not metadata.get(
                "token_endpoint"
            ):
                raise McpOAuthError("invalid_state")

            form = {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": self.redirect_uri,
                "client_id": client_id,
                "resource": server["url"],
            }
            if session_payload.get("client_secret"):
                form["client_secret"] = session_payload["client_secret"]
            token_response = self._request(
                "POST",
                metadata["token_endpoint"],
                data=form,
            )
            if not self._is_success(token_response):
                raise McpOAuthError("token_exchange_failed")
            token = self._json_object(token_response)
            credentials = self._merge_token(
                server.get("credentials") or {},
                token,
            )
            credentials["metadata"] = metadata
            credentials["client_id"] = client_id
            if session_payload.get("client_secret"):
                credentials["client_secret"] = session_payload[
                    "client_secret"
                ]
            self.configs.save_credentials(
                user_id,
                session["server_id"],
                credentials,
            )
            self.configs.set_status(
                user_id,
                session["server_id"],
                "connected",
            )
            result = self.configs.get_owned(user_id, session["server_id"])
            if result is not None:
                result["returnTo"] = return_to
            return result
        except McpOAuthError as exc:
            if exc.return_to is None:
                exc.return_to = return_to
            raise

    def _server(
        self,
        user_or_server: int | dict[str, Any],
        server_id: Any | None,
    ) -> tuple[int, Any, dict[str, Any]]:
        if isinstance(user_or_server, dict):
            user_id = user_or_server.get(
                "user_id",
                user_or_server.get("userId"),
            )
            resolved_id = user_or_server.get(
                "id",
                user_or_server.get("server_id"),
            )
            if user_id is None or resolved_id is None:
                raise McpOAuthError("not_configured")
            server = self.configs.secret(user_id, resolved_id)
            if not server:
                raise McpOAuthError("not_configured")
            return int(user_id), resolved_id, server
        if server_id is None:
            raise McpOAuthError("not_configured")
        user_id = int(user_or_server)
        server = self.configs.secret(user_id, server_id)
        if not server:
            raise McpOAuthError("not_configured")
        return user_id, server_id, server

    def ensure_access_token(
        self,
        user_or_server: int | dict[str, Any],
        server_id: Any | None = None,
        force_refresh: bool = False,
    ) -> str:
        if isinstance(user_or_server, dict) and isinstance(
            server_id,
            bool,
        ):
            force_refresh = server_id
            server_id = None
        user_id, resolved_id, server = self._server(
            user_or_server,
            server_id,
        )
        credentials = server.get("credentials") or {}
        access_token = credentials.get("access_token")
        expires_at = credentials.get("expires_at")
        valid_expiry = expires_at in (None, "")
        if not valid_expiry:
            try:
                valid_expiry = (
                    float(expires_at)
                    > self.now().timestamp() + 60
                )
            except (TypeError, ValueError):
                valid_expiry = False
        if (
            isinstance(access_token, str)
            and access_token
            and not force_refresh
            and valid_expiry
        ):
            return access_token

        refresh_token = credentials.get("refresh_token")
        metadata = credentials.get("metadata") or {}
        if (
            not isinstance(refresh_token, str)
            or not refresh_token
            or not metadata.get("token_endpoint")
        ):
            raise McpOAuthError("reauthorize")
        form = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": credentials.get("client_id"),
            "resource": server["url"],
        }
        if credentials.get("client_secret"):
            form["client_secret"] = credentials["client_secret"]
        response = self._request(
            "POST",
            metadata["token_endpoint"],
            data=form,
        )
        try:
            value = self._json_object(response)
        except McpOAuthError:
            if not self._is_success(response):
                raise McpOAuthError("token_refresh_failed")
            raise
        if not self._is_success(response):
            if value.get("error") == "invalid_grant":
                self.configs.set_status(
                    user_id,
                    resolved_id,
                    "reauthorize",
                    error_code="invalid_grant",
                )
                raise McpOAuthError("reauthorize")
            raise McpOAuthError("token_refresh_failed")
        merged = self._merge_token(credentials, value)
        self.configs.save_credentials(
            user_id,
            resolved_id,
            merged,
        )
        return str(merged["access_token"])

    def authorization_headers(
        self,
        user_or_server: int | dict[str, Any],
        server_id: Any | None = None,
        force_refresh: bool = False,
    ) -> dict[str, str]:
        token = self.ensure_access_token(
            user_or_server,
            server_id,
            force_refresh,
        )
        return {"Authorization": f"Bearer {token}"}

    def revoke_credentials(
        self,
        user_or_server: int | dict[str, Any],
        server_id: Any | None = None,
    ) -> dict[str, Any]:
        try:
            _, _, server = self._server(
                user_or_server,
                server_id,
            )
        except McpOAuthError as exc:
            return {"ok": False, "code": exc.code}
        credentials = server.get("credentials") or {}
        endpoint = (
            credentials.get("metadata") or {}
        ).get("revocation_endpoint")
        if not endpoint:
            return {"ok": False, "code": "unsupported"}
        token = credentials.get("refresh_token") or credentials.get(
            "access_token"
        )
        if not token:
            return {"ok": False, "code": "not_configured"}
        form = {
            "token": token,
            "client_id": credentials.get("client_id"),
        }
        if credentials.get("client_secret"):
            form["client_secret"] = credentials["client_secret"]
        try:
            response = self._request("POST", endpoint, data=form)
            if not self._is_success(response):
                return {"ok": False, "code": "revoke_failed"}
            return {"ok": True}
        except McpOAuthError as exc:
            return {"ok": False, "code": exc.code}
