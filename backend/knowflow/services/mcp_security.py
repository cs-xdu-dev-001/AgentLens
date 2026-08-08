"""Network and header policy for remote MCP servers."""
from __future__ import annotations

import ipaddress
import re
import socket
from typing import Callable, Iterable
from urllib.parse import urlsplit

import httpx

_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
_BLOCKED = _HOP_BY_HOP | {"host", "cookie", "mcp-session-id"}

def _addresses(host: str, port: int, resolver: Callable | None) -> list[str]:
    fn = resolver or socket.getaddrinfo
    raw = fn(host, port)
    # Accept one getaddrinfo 5-tuple as well as its usual list of tuples.
    if isinstance(raw, tuple) and len(raw) >= 5 and isinstance(raw[4], tuple):
        raw = [raw]
    if isinstance(raw, (str, bytes)):
        raw = [raw]
    out = []
    for item in raw:
        value = item[4][0] if isinstance(item, tuple) and len(item) >= 5 and isinstance(item[4], tuple) else item
        out.append(str(value))
    return out

def resolve_remote_addresses(host: str, port: int, resolver: Callable | None = None, allow_private: bool = False) -> list[str]:
    if not isinstance(host, str) or not host or not isinstance(port, int) or not (1 <= port <= 65535):
        raise ValueError("invalid_address")
    try:
        addrs = _addresses(host, port, resolver)
    except Exception as exc:
        raise ValueError("dns_failure") from exc
    if not addrs:
        raise ValueError("dns_failure")
    result=[]
    for raw in addrs:
        try: addr=ipaddress.ip_address(str(raw).split('%',1)[0])
        except ValueError as exc: raise ValueError("invalid_address") from exc
        if not allow_private and not addr.is_global: raise ValueError("private_address")
        result.append(str(raw))
    return result

def _validate_url(
    url: str,
    *,
    allowed_schemes: tuple[str, ...],
    resolver: Callable | None = None,
    allow_private: bool = False,
) -> str:
    if not isinstance(url, str) or "\r" in url or "\n" in url:
        raise ValueError("invalid_url")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except (ValueError, UnicodeError) as exc:
        raise ValueError("invalid_url") from exc
    if parts.scheme.lower() not in allowed_schemes:
        raise ValueError("insecure_scheme")
    if not hostname or parts.username is not None or parts.password is not None or parts.fragment:
        raise ValueError("invalid_url")
    host = hostname.rstrip(".").lower()
    if not host or "%" in host:
        raise ValueError("invalid_url")
    try:
        host = host.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError) as exc:
        raise ValueError("invalid_url") from exc
    if host in {"localhost", "metadata.google.internal", "metadata.google.com", "instance-data.ec2.internal"}:
        if not allow_private: raise ValueError("private_address")
    try:
        literal = ipaddress.ip_address(host)
        if not allow_private and not literal.is_global:
            raise ValueError("private_address")
    except ValueError as exc:
        if str(exc) == "private_address":
            raise
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise ValueError("invalid_port") from exc
    resolve_remote_addresses(host, port, resolver, allow_private)
    return url


def validate_remote_url(url: str, *, resolver: Callable | None = None, allow_private: bool = False) -> str:
    return _validate_url(
        url,
        allowed_schemes=("http", "https") if allow_private else ("https",),
        resolver=resolver,
        allow_private=allow_private,
    )


def validate_public_url(url: str, *, resolver: Callable | None = None) -> str:
    """Validate an HTTP(S) URL whose destination must stay on the public internet."""
    return _validate_url(
        url,
        allowed_schemes=("http", "https"),
        resolver=resolver,
        allow_private=False,
    )


class PinnedTransport(httpx.BaseTransport):
    """Resolve and validate the address used by the actual HTTP connection."""

    def __init__(
        self,
        delegate: httpx.BaseTransport,
        resolver: Callable | None = None,
        allow_private: bool = False,
    ) -> None:
        self.delegate = delegate
        self.resolver = resolver
        self.allow_private = allow_private

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if not host:
            raise httpx.InvalidURL("URL is missing a host.")
        port = request.url.port or (
            443 if request.url.scheme == "https" else 80
        )
        ip = resolve_remote_addresses(
            host,
            port,
            self.resolver,
            self.allow_private,
        )[0]
        headers = request.headers.copy()
        if "host" not in headers:
            headers["host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method,
            request.url,
            headers=headers,
            stream=request.stream,
            extensions=dict(request.extensions),
        )
        pinned.url = pinned.url.copy_with(host=ip)
        pinned.extensions["sni_hostname"] = host
        return self.delegate.handle_request(pinned)

    def close(self) -> None:
        self.delegate.close()


class PinnedAsyncTransport(httpx.AsyncBaseTransport):
    """Async counterpart used by remote MCP connections."""

    def __init__(
        self,
        delegate: httpx.AsyncBaseTransport,
        resolver: Callable | None = None,
        allow_private: bool = False,
    ) -> None:
        self.delegate = delegate
        self.resolver = resolver
        self.allow_private = allow_private

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        host = request.url.host
        if not host:
            raise httpx.InvalidURL("URL is missing a host.")
        port = request.url.port or (
            443 if request.url.scheme == "https" else 80
        )
        ip = resolve_remote_addresses(
            host,
            port,
            self.resolver,
            self.allow_private,
        )[0]
        headers = request.headers.copy()
        if "host" not in headers:
            headers["host"] = request.url.netloc.decode("ascii")
        pinned = httpx.Request(
            request.method,
            request.url,
            headers=headers,
            stream=request.stream,
            extensions=dict(request.extensions),
        )
        pinned.url = pinned.url.copy_with(host=ip)
        pinned.extensions["sni_hostname"] = host
        return await self.delegate.handle_async_request(pinned)

    async def aclose(self) -> None:
        await self.delegate.aclose()

def validate_static_headers(headers: dict) -> dict[str, str]:
    if not isinstance(headers, dict): raise ValueError("invalid_headers")
    result: dict[str, str] = {}
    seen: set[str] = set()
    token = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
    for key, value in headers.items():
        name, text = str(key), str(value)
        if not token.fullmatch(name):
            raise ValueError("invalid_header")
        lower = name.lower()
        if lower in seen or lower in _BLOCKED or "\r" in text or "\n" in text or len(text.encode("utf-8")) > 8192:
            raise ValueError("invalid_header")
        seen.add(lower)
        result[name] = text
    return result
