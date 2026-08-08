from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .agent_loop import ToolRegistry
from .web_search import WebSearchArguments, WebSearchProvider


class McpToolConfigurationError(RuntimeError):
    code = "mcp_tool_configuration_invalid"


def mcp_tool_risk(tool: dict[str, Any]) -> str:
    annotations = tool.get("annotations") or {}
    if annotations.get("destructiveHint") is True:
        return "destructive"
    if annotations.get("readOnlyHint") is True:
        return "read"
    if annotations.get("readOnlyHint") is False:
        return "write"
    return "unknown"


def register_web_search_tool(
    registry: ToolRegistry,
    *,
    provider: WebSearchProvider,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    def run_web_search(args: WebSearchArguments):
        if cancel_check and cancel_check():
            raise RuntimeError("Agent run was cancelled.")
        result = provider.search(args.query, args.top_k)
        if cancel_check and cancel_check():
            raise RuntimeError("Agent run was cancelled.")
        return {"results": result}

    registry.register(
        name="web_search",
        description=(
            "Search the public web for current or external information "
            "and return source URLs."
        ),
        arguments_model=WebSearchArguments,
        handler=run_web_search,
        read_only=True,
        engine_names={"langgraph"},
        concurrency_safe=True,
        interrupt_behavior="cancel",
        search_hint="current public web sources",
    )


def register_mcp_tools(
    registry: ToolRegistry,
    *,
    tools: Iterable[dict[str, Any]],
    call_tool: Callable[[dict[str, Any], dict[str, Any], bool], Any],
    max_tools: int,
    registered_names: set[str] | None = None,
    search_threshold: int | None = None,
) -> set[str]:
    enabled_tools = list(tools)
    if len(enabled_tools) > max_tools:
        raise McpToolConfigurationError("Too many MCP tools are enabled.")
    names = registered_names if registered_names is not None else set(registry.names())
    for tool in enabled_tools:
        name = str(tool.get("modelName") or "")
        remote_name = str(tool.get("remoteName") or tool.get("name") or "")
        input_schema = tool.get("inputSchema")
        if not name or not remote_name or not isinstance(input_schema, dict) or name in names:
            raise McpToolConfigurationError("The MCP tool snapshot is invalid.")
        annotations = tool.get("annotations") or {}
        read_only = (
            annotations.get("readOnlyHint") is True
            and annotations.get("destructiveHint") is not True
        )
        destructive = annotations.get("destructiveHint") is True
        registry.register(
            name=name,
            description=str(tool.get("description") or "")[:1000],
            input_schema=input_schema,
            handler=lambda args, item=tool, safe_read=read_only: call_tool(item, args, safe_read),
            read_only=read_only,
            destructive=destructive,
            concurrency_safe=False,
            interrupt_behavior="cancel" if read_only else "block",
            engine_names={"langgraph"},
            trace_kind="mcp",
            risk=mcp_tool_risk(tool),
            server_name=str(tool.get("serverName") or "MCP"),
            search_hint=f"{tool.get('serverName') or 'MCP'} {remote_name}",
            should_defer=True,
        )
        names.add(name)
    if enabled_tools:
        if search_threshold is None:
            registry.enable_tool_search()
        else:
            registry.enable_tool_search(threshold=search_threshold)
    return names
