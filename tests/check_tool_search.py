from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from langgraph_test_helper import run_langgraph_agent


EMPTY_SCHEMA = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def call(name: str, call_id: str, arguments: dict | None = None) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments or {}),
        },
    }


class ToolSearchGateway:
    def __init__(self) -> None:
        self.round = 0

    def complete(self, messages, config, *, tools=None, tool_choice=None):
        self.round += 1
        names = {
            item["function"]["name"]
            for item in (tools or [])
        }
        if self.round == 1:
            assert "tool_search" in names
            assert "web_search" in names
            assert "mcp__notion__search" not in names
            assert "mcp__github__issues" not in names
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    call(
                        "tool_search",
                        "call-tool-search",
                        {"tool_names": ["mcp__notion__search"]},
                    )
                ],
            }
        if self.round == 2:
            assert "mcp__notion__search" in names
            assert "mcp__github__issues" not in names
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    call("mcp__notion__search", "call-notion")
                ],
            }
        assert messages[-1]["name"] == "mcp__notion__search"
        return {
            "role": "assistant",
            "content": "The Notion search completed.",
        }


def main() -> None:
    registry = ToolRegistry()
    registry.register(
        name="web_search",
        description="Search the public web.",
        input_schema=EMPTY_SCHEMA,
        handler=lambda _args: {"results": []},
        read_only=True,
        always_load=True,
    )
    for name, description in (
        ("mcp__notion__search", "Search pages in Notion."),
        ("mcp__github__issues", "Search GitHub issues."),
        ("mcp__slack__messages", "Search Slack messages."),
    ):
        registry.register(
            name=name,
            description=description,
            input_schema=EMPTY_SCHEMA,
            handler=lambda _args, tool=name: {"tool": tool},
            read_only=True,
            should_defer=True,
            search_hint=description,
        )

    assert registry.enable_tool_search(threshold=2) is True
    initial_names = registry.eligible_names("langgraph")
    assert "tool_search" in initial_names
    assert "web_search" in initial_names
    assert "mcp__notion__search" not in initial_names

    blocked = registry.prepare(
        call("mcp__notion__search", "call-too-early"),
        allowed_names=set(initial_names),
        engine_name="langgraph",
    )
    assert blocked.error is not None
    assert blocked.error.error_code == "unknown_tool"

    result = run_langgraph_agent(
        gateway=ToolSearchGateway(),
        messages=[
            {"role": "user", "content": "Search my Notion workspace."}
        ],
        config={"model_name": "fake"},
        registry=registry,
    )
    assert result.answer == "The Notion search completed."
    assert [item.tool_name for item in result.executions] == [
        "tool_search",
        "mcp__notion__search",
    ]
    assert "mcp__github__issues" not in registry.eligible_names(
        "langgraph"
    )

    small_registry = ToolRegistry()
    small_registry.register(
        name="one_deferred_tool",
        description="One tool does not justify ToolSearch.",
        input_schema=EMPTY_SCHEMA,
        handler=lambda _args: {},
        should_defer=True,
    )
    assert small_registry.enable_tool_search(threshold=2) is False
    assert "one_deferred_tool" in small_registry.eligible_names(
        "langgraph"
    )

    print("ToolSearch loads only relevant deferred tool schemas")


if __name__ == "__main__":
    main()
