from __future__ import annotations

from pathlib import Path
import sys

import httpx


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.runtime import build_messages  # noqa: E402
from knowflow.services.agent_loop import ToolRegistry  # noqa: E402
from knowflow.services.agent_tooling import (  # noqa: E402
    register_web_fetch_tool,
)
from knowflow.services.local_cli_runtime import (  # noqa: E402
    LocalAgentRuntime,
)
from knowflow.services.web_fetch import (  # noqa: E402
    PublicWebFetcher,
    WebFetchError,
)


PUBLIC_IP = "93.184.216.34"


def public_resolver(_host: str, _port: int):
    return [PUBLIC_IP]


def expect_error(fetcher: PublicWebFetcher, url: str, code: str) -> None:
    try:
        fetcher.fetch(url)
    except WebFetchError as exc:
        assert exc.code == code, (exc.code, code)
    else:
        raise AssertionError(f"Expected {code}: {url}")


def exercise_html_and_redirect() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("host", "")))
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://www.example.com/article?token=redirect-secret"
                        "&lang=zh"
                    )
                },
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=(
                "<html><head><title>Example article</title>"
                '<meta name="description" content="Useful summary">'
                "<script>secretScript()</script></head><body>"
                "<nav>Navigation</nav><main><h1>Example article</h1>"
                "<p>Evidence from the page.</p>"
                '<a href="/source?api_key=page-secret&amp;lang=zh#part">'
                "Source</a></main></body></html>"
            ).encode(),
        )

    fetcher = PublicWebFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(handler),
    )
    result = fetcher.fetch("https://example.com/start")
    assert result["url"] == "https://example.com/start"
    assert result["final_url"] == (
        "https://www.example.com/article?token=%5Bredacted%5D&lang=zh"
    )
    assert result["status_code"] == 200
    assert result["content_type"] == "text/html"
    assert result["title"] == "Example article"
    assert result["description"] == "Useful summary"
    assert "Evidence from the page." in result["content"]
    assert "secretScript" not in result["content"]
    assert "Navigation" not in result["content"]
    assert result["links"] == [
        {
            "text": "Source",
            "url": (
                "https://www.example.com/source?api_key=%5Bredacted%5D&lang=zh"
            ),
        }
    ]
    assert result["truncated"] is False
    assert calls == [
        (f"https://{PUBLIC_IP}/start", "example.com"),
        (
            f"https://{PUBLIC_IP}/article?token=redirect-secret&lang=zh",
            "www.example.com",
        ),
    ]


def exercise_limits_and_policy() -> None:
    blocked = PublicWebFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"unused",
            )
        ),
    )
    for url in (
        "file:///etc/passwd",
        "https://localhost/private",
        "https://127.0.0.1/private",
        "https://169.254.169.254/latest/meta-data",
        "https://user:pass@example.com/private",
    ):
        expect_error(blocked, url, "web_fetch_forbidden_target")

    answers = iter([[PUBLIC_IP], ["127.0.0.1"]])
    rebinding = PublicWebFetcher(
        resolver=lambda _host, _port: next(answers),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"must not be reached",
            )
        ),
    )
    expect_error(
        rebinding,
        "https://example.com/private",
        "web_fetch_forbidden_target",
    )

    downgrade = PublicWebFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                302,
                headers={"location": "http://example.com/plain"},
            )
        ),
    )
    expect_error(
        downgrade,
        "https://example.com/start",
        "web_fetch_redirect_error",
    )

    oversized = PublicWebFetcher(
        resolver=public_resolver,
        max_response_bytes=4,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"12345",
            )
        ),
    )
    expect_error(
        oversized,
        "https://example.com/large",
        "web_fetch_response_too_large",
    )

    unsupported = PublicWebFetcher(
        resolver=public_resolver,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"png",
            )
        ),
    )
    expect_error(
        unsupported,
        "https://example.com/image",
        "web_fetch_unsupported_content",
    )


def exercise_tool_and_grounding_contract() -> None:
    class Provider:
        def fetch(self, url: str, *, max_chars: int):
            return {"url": url, "content": "evidence", "max": max_chars}

    registry = ToolRegistry()
    register_web_fetch_tool(registry, provider=Provider())
    definition = registry.definition("web_fetch")
    assert definition is not None
    assert definition.read_only is True
    assert definition.always_load is True
    prepared = registry.prepare(
        {
            "id": "call-fetch",
            "type": "function",
            "function": {
                "name": "web_fetch",
                "arguments": '{"url":"https://example.com/page"}',
            },
        },
        engine_name="langgraph",
    )
    execution = registry.invoke(prepared)
    assert execution.status == "success"
    assert execution.output["content"] == "evidence"

    web_prompt = build_messages(
        "Read https://example.com/page",
        [],
        [],
        agent_mode=True,
    )[0]["content"]
    assert "For a specific URL, use web_fetch" in web_prompt
    assert "does not prove" in web_prompt

    cli_prompt = LocalAgentRuntime._system_message(Path("/workspace"))["content"]
    assert "Use web_fetch for a specific URL" in cli_prompt
    assert "unsupported claims" in cli_prompt


def main() -> None:
    exercise_html_and_redirect()
    exercise_limits_and_policy()
    exercise_tool_and_grounding_contract()
    print("web fetch is public-only, bounded, grounded, and registered")


if __name__ == "__main__":
    main()
