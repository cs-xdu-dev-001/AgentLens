from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import (
    parse_qsl,
    urldefrag,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from .mcp_security import PinnedTransport, validate_public_url


DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_CONTENT_CHARS = 16_000
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/xhtml+xml",
    "application/xml",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SENSITIVE_QUERY_KEY = re.compile(
    r"(?:^|[_-])(?:access[_-]?token|api[_-]?key|auth|code|credential|jwt|key|pass(?:word|wd)?|secret|session|sig(?:nature)?|token)(?:$|[_-])",
    re.IGNORECASE,
)


class WebFetchArguments(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    max_chars: int = Field(
        default=DEFAULT_MAX_CONTENT_CHARS,
        ge=500,
        le=30_000,
    )


class WebFetchError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class WebFetchProvider(Protocol):
    def fetch(
        self,
        url: str,
        *,
        max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    ) -> dict[str, Any]:
        ...


def _clean_text(value: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw in value.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line == previous:
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def _public_url(value: str) -> str:
    """Redact credential-like query values before exposing URLs to the model."""
    parts = urlsplit(value)
    if not parts.query:
        return value
    query = urlencode(
        [
            (key, "[redacted]" if SENSITIVE_QUERY_KEY.search(key) else item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ],
        doseq=True,
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query, parts.fragment)
    )


def _meta_content(soup: BeautifulSoup, *names: str) -> str:
    expected = {name.lower() for name in names}
    for tag in soup.find_all("meta"):
        key = str(tag.get("name") or tag.get("property") or "").lower()
        if key in expected:
            return str(tag.get("content") or "").strip()[:500]
    return ""


def _extract_html(
    html: str,
    *,
    base_url: str,
    max_chars: int,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = (
        soup.title.get_text(" ", strip=True)[:300]
        if soup.title is not None
        else ""
    )
    description = _meta_content(
        soup,
        "description",
        "og:description",
        "twitter:description",
    )
    for tag in soup.find_all(
        ["script", "style", "noscript", "template", "svg", "canvas"]
    ):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    content = _clean_text(root.get_text("\n", strip=True))
    truncated = len(content) > max_chars
    content = content[:max_chars]

    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in root.find_all("a", href=True):
        resolved, _fragment = urldefrag(
            urljoin(base_url, str(tag.get("href") or ""))
        )
        parsed = urlsplit(resolved)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or resolved in seen
        ):
            continue
        seen.add(resolved)
        links.append(
            {
                "text": _clean_text(tag.get_text(" ", strip=True))[:200],
                "url": _public_url(resolved)[:2048],
            }
        )
        if len(links) >= 30:
            break
    return {
        "title": title,
        "description": description,
        "content": content,
        "links": links,
        "truncated": truncated,
    }


class PublicWebFetcher:
    def __init__(
        self,
        *,
        resolver: Callable | None = None,
        transport: httpx.BaseTransport | None = None,
        connect_timeout: float = 5,
        request_timeout: float = 20,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        cancel_check: Callable[[], bool] | None = None,
    ) -> None:
        self.resolver = resolver
        self.transport = transport
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self.max_response_bytes = max(1, int(max_response_bytes))
        self.max_redirects = max(0, int(max_redirects))
        self.cancel_check = cancel_check

    def _cancelled(self) -> None:
        if self.cancel_check and self.cancel_check():
            raise WebFetchError(
                "web_fetch_cancelled",
                "Web fetch was cancelled.",
            )

    def _validated(self, url: str) -> str:
        normalized = str(url or "").strip()
        try:
            return validate_public_url(
                normalized,
                resolver=self.resolver,
            )
        except ValueError as exc:
            raise WebFetchError(
                "web_fetch_forbidden_target",
                "The URL is invalid or does not resolve to a public address.",
            ) from exc

    def fetch(
        self,
        url: str,
        *,
        max_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    ) -> dict[str, Any]:
        requested_url = self._validated(url)
        current_url = requested_url
        text_limit = max(500, min(30_000, int(max_chars)))
        delegate = self.transport or httpx.HTTPTransport(trust_env=False)
        transport = PinnedTransport(delegate, self.resolver, False)
        timeout = httpx.Timeout(
            self.request_timeout,
            connect=self.connect_timeout,
        )
        headers = {
            "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.8,*/*;q=0.1",
            "User-Agent": "KnowFlow-WebFetch/1.0",
        }
        try:
            with httpx.Client(
                transport=transport,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                headers=headers,
            ) as client:
                for redirect_count in range(self.max_redirects + 1):
                    self._cancelled()
                    with client.stream("GET", current_url) as response:
                        if response.status_code in REDIRECT_STATUSES:
                            location = response.headers.get("location")
                            if (
                                not location
                                or len(location) > 4096
                                or redirect_count >= self.max_redirects
                            ):
                                raise WebFetchError(
                                    "web_fetch_redirect_error",
                                    "The page redirected too many times or returned an invalid redirect.",
                                )
                            next_url, _fragment = urldefrag(
                                urljoin(current_url, location)
                            )
                            if (
                                urlsplit(current_url).scheme.lower() == "https"
                                and urlsplit(next_url).scheme.lower() == "http"
                            ):
                                raise WebFetchError(
                                    "web_fetch_redirect_error",
                                    "HTTPS redirects to HTTP are not allowed.",
                                )
                            current_url = self._validated(next_url)
                            continue
                        if response.status_code >= 400:
                            raise WebFetchError(
                                "web_fetch_http_error",
                                f"The page returned HTTP {response.status_code}.",
                            )
                        content_type = response.headers.get(
                            "content-type",
                            "",
                        ).split(";", 1)[0].strip().lower()
                        if content_type not in ALLOWED_CONTENT_TYPES:
                            raise WebFetchError(
                                "web_fetch_unsupported_content",
                                "The page content type is not supported.",
                            )
                        length = response.headers.get("content-length")
                        if length:
                            try:
                                if int(length) > self.max_response_bytes:
                                    raise WebFetchError(
                                        "web_fetch_response_too_large",
                                        "The page is larger than the fetch limit.",
                                    )
                            except ValueError:
                                pass
                        body = bytearray()
                        for chunk in response.iter_bytes():
                            self._cancelled()
                            body.extend(chunk)
                            if len(body) > self.max_response_bytes:
                                raise WebFetchError(
                                    "web_fetch_response_too_large",
                                    "The page is larger than the fetch limit.",
                                )
                        encoding = response.charset_encoding or "utf-8"
                        try:
                            decoded = bytes(body).decode(
                                encoding,
                                errors="replace",
                            )
                        except LookupError:
                            decoded = bytes(body).decode(
                                "utf-8",
                                errors="replace",
                            )
                        if content_type in {
                            "text/html",
                            "application/xhtml+xml",
                        }:
                            extracted = _extract_html(
                                decoded,
                                base_url=current_url,
                                max_chars=text_limit,
                            )
                        else:
                            content = _clean_text(decoded)
                            extracted = {
                                "title": "",
                                "description": "",
                                "content": content[:text_limit],
                                "links": [],
                                "truncated": len(content) > text_limit,
                            }
                        return {
                            "url": _public_url(requested_url),
                            "final_url": _public_url(current_url),
                            "status_code": response.status_code,
                            "content_type": content_type,
                            **extracted,
                        }
        except WebFetchError:
            raise
        except httpx.TimeoutException as exc:
            raise WebFetchError(
                "web_fetch_timeout",
                "Web fetch timed out.",
            ) from exc
        except ValueError as exc:
            raise WebFetchError(
                "web_fetch_forbidden_target",
                "The URL is invalid or does not resolve to a public address.",
            ) from exc
        except (httpx.RequestError, UnicodeError) as exc:
            raise WebFetchError(
                "web_fetch_failed",
                "Web fetch failed.",
            ) from exc
        raise WebFetchError(
            "web_fetch_failed",
            "Web fetch failed.",
        )
