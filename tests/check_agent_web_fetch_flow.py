from __future__ import annotations

import json
import os
from pathlib import Path
import sys


os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry  # noqa: E402
from knowflow.services.agent_tooling import (  # noqa: E402
    register_web_fetch_tool,
)
from langgraph_test_helper import run_langgraph_agent  # noqa: E402


class Provider:
    def fetch(self, url: str, *, max_chars: int):
        assert url == "https://example.com/article"
        assert max_chars == 16000
        return {
            "url": url,
            "final_url": url,
            "status_code": 200,
            "content_type": "text/html",
            "title": "Verified article",
            "description": "",
            "content": "Evidence read from the requested page.",
            "links": [],
            "truncated": False,
        }


class Gateway:
    def __init__(self) -> None:
        self.round = 0

    def complete(self, messages, config, *, tools=None, tool_choice=None):
        self.round += 1
        names = {
            item["function"]["name"]
            for item in (tools or [])
        }
        assert "web_fetch" in names
        if self.round == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-web-fetch",
                        "type": "function",
                        "function": {
                            "name": "web_fetch",
                            "arguments": json.dumps(
                                {"url": "https://example.com/article"}
                            ),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["name"] == "web_fetch"
        assert "Evidence read from the requested page" in messages[-1]["content"]
        return {
            "role": "assistant",
            "content": (
                "The page was read successfully. "
                "[Source](https://example.com/article)"
            ),
        }


def main() -> None:
    registry = ToolRegistry()
    register_web_fetch_tool(registry, provider=Provider())
    result = run_langgraph_agent(
        gateway=Gateway(),
        messages=[
            {
                "role": "user",
                "content": "Read https://example.com/article",
            }
        ],
        config={"model_name": "fake"},
        registry=registry,
    )
    assert result.answer.startswith("The page was read successfully")
    assert [item.tool_name for item in result.executions] == ["web_fetch"]
    print("agent opens a supplied URL with web_fetch and cites the source")


if __name__ == "__main__":
    main()
