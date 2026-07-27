from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.skill_store import (  # noqa: E402
    SkillStoreError,
    download_github_archive,
    parse_github_source,
)


class FakeResponse:
    def __init__(
        self,
        body: bytes = b"",
        *,
        status_code: int = 200,
        content_length: int | None = None,
    ):
        self.body = body
        self.status_code = status_code
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)

    def iter_content(self, chunk_size: int):
        assert 1 <= chunk_size <= 1024 * 1024
        for offset in range(0, len(self.body), 3):
            yield self.body[offset : offset + 3]

    def close(self):
        pass


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.trust_env = True
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response

    def close(self):
        self.closed = True


def expect_source_rejected(url: str, ref: str = "main", subpath: str = "") -> None:
    try:
        parse_github_source(url, ref=ref, subpath=subpath)
    except SkillStoreError as exc:
        assert exc.code == "skill_invalid_source"
        assert "http" not in str(exc).lower()
    else:
        raise AssertionError((url, ref, subpath))


def expect_download_rejected(response: FakeResponse, code: str) -> None:
    session = FakeSession(response)
    source = parse_github_source("https://github.com/openai/example", ref="v1")
    try:
        download_github_archive(
            source,
            max_bytes=8,
            timeout=7,
            session_factory=lambda: session,
        )
    except SkillStoreError as exc:
        assert exc.code == code, (exc.code, code)
        assert "codeload" not in str(exc).lower()
        assert "github.com" not in str(exc).lower()
    else:
        raise AssertionError(code)


def main() -> None:
    source = parse_github_source(
        "https://github.com/OpenAI/example.git",
        ref="release/v1",
        subpath="skills/research",
    )
    assert source.owner == "OpenAI"
    assert source.repo == "example"
    assert source.ref == "release/v1"
    assert source.subpath == "skills/research"
    assert source.url == "https://github.com/OpenAI/example"

    invalid_urls = (
        "http://github.com/openai/example",
        "https://user:token@github.com/openai/example",
        "https://github.com:444/openai/example",
        "https://raw.githubusercontent.com/openai/example/main/SKILL.md",
        "https://codeload.github.com/openai/example/zip/main",
        "https://github.com/openai",
        "https://github.com/openai/example/extra",
        "https://github.com/openai/../example",
        "https://github.com/openai/example?token=secret",
        "https://github.com/openai/example#main",
        "https://github.com/.hidden/example",
        "https://github.com/openai/bad repo",
    )
    for value in invalid_urls:
        expect_source_rejected(value)
    for ref in ("", "/main", "../main", "main//next", "main\\next", "main/../next"):
        expect_source_rejected("https://github.com/openai/example", ref=ref)
    for subpath in (
        "/skills/x",
        "../x",
        "skills/../x",
        "skills\\x",
        "./skills",
        "skills//x",
        "skills/C:",
        "skills/NUL.txt",
        "skills/trailing.",
        "skills/trailing ",
        "x" * 501,
    ):
        expect_source_rejected(
            "https://github.com/openai/example",
            subpath=subpath,
        )

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        bundle.writestr("example-v1/SKILL.md", "ok")
    body = stream.getvalue()
    response = FakeResponse(body, content_length=len(body))
    session = FakeSession(response)
    downloaded = download_github_archive(
        source,
        max_bytes=len(body),
        timeout=7,
        session_factory=lambda: session,
    )
    assert downloaded == body
    assert session.trust_env is False
    assert session.closed is True
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == (
        "https://codeload.github.com/OpenAI/example/zip/release%2Fv1"
    )
    assert kwargs == {
        "allow_redirects": False,
        "stream": True,
        "timeout": 7,
    }

    expect_download_rejected(FakeResponse(status_code=302), "skill_download_failed")
    expect_download_rejected(
        FakeResponse(b"x", content_length=9),
        "skill_archive_too_large",
    )
    expect_download_rejected(
        FakeResponse(b"123456789"),
        "skill_archive_too_large",
    )
    print("skill GitHub source and bounded download checks passed")


if __name__ == "__main__":
    main()
