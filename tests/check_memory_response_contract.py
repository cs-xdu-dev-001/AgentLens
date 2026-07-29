from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

os.environ.setdefault(
    "KNOWFLOW_SECRET_KEY",
    "memory-response-contract-test-secret",
)

from knowflow.runtime import build_messages  # noqa: E402


def main() -> None:
    enabled = build_messages(
        "请记住我喜欢Python",
        [],
        [],
        memories=[],
    )[0]["content"]
    assert "Memory persistence happens only after this response" in enabled
    assert "Never claim that a memory was saved" in enabled

    disabled = build_messages(
        "请记住我喜欢Python",
        [],
        [],
        memories=None,
    )[0]["content"]
    assert "Memory persistence happens only after this response" not in disabled

    chat_source = (
        BACKEND / "knowflow" / "routers" / "chat.py"
    ).read_text(encoding="utf-8")
    extension_source = (
        BACKEND / "knowflow" / "routers" / "extensions.py"
    ).read_text(encoding="utf-8")
    assert "memories=memories if memory_active else None" in chat_source
    assert "memories=memories if memory_active else None" in extension_source

    print("memory-enabled answers do not claim an unverified write")


if __name__ == "__main__":
    main()
