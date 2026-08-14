from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from pydantic import BaseModel, Field

from .agent_loop import ToolRegistry
from .web_fetch import WebFetchArguments, WebFetchProvider
from .web_search import WebSearchArguments, WebSearchProvider


class McpToolConfigurationError(RuntimeError):
    code = "mcp_tool_configuration_invalid"


ASK_USER_QUESTION_TOOL = "ask_user_question"


class UserQuestionOption(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    value: str = Field(default="", max_length=120)


class AskUserQuestionArguments(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    header: str = Field(default="需要确认", max_length=40)
    options: list[UserQuestionOption] = Field(
        default_factory=list,
        min_length=2,
        max_length=4,
    )
    allow_custom: bool = True


def register_user_question_tool(registry: ToolRegistry) -> None:
    """Expose LangGraph's user-input interrupt as a model tool."""

    def unreachable(_args: AskUserQuestionArguments) -> dict[str, Any]:
        raise RuntimeError(
            "ask_user_question must be handled by the LangGraph runtime."
        )

    registry.register(
        name=ASK_USER_QUESTION_TOOL,
        description=(
            "Pause and ask the user one concise multiple-choice question when "
            "a consequential requirement is genuinely missing. Prefer making "
            "safe progress without asking. Do not use for routine updates."
        ),
        arguments_model=AskUserQuestionArguments,
        handler=unreachable,
        read_only=True,
        engine_names={"langgraph"},
        trace_kind="question",
        risk="read",
        internal=True,
        concurrency_safe=False,
        interrupt_behavior="block",
        always_load=True,
    )


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


def register_web_fetch_tool(
    registry: ToolRegistry,
    *,
    provider: WebFetchProvider,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    def run_web_fetch(args: WebFetchArguments):
        if cancel_check and cancel_check():
            raise RuntimeError("Agent run was cancelled.")
        result = provider.fetch(args.url, max_chars=args.max_chars)
        if cancel_check and cancel_check():
            raise RuntimeError("Agent run was cancelled.")
        return result

    registry.register(
        name="web_fetch",
        description=(
            "Open a specific public HTTP or HTTPS URL and return its "
            "readable page content. Use this for URLs supplied by the user "
            "or URLs discovered with web_search. A fetch failure is not "
            "evidence that the page is unindexed, unavailable, or low quality."
        ),
        arguments_model=WebFetchArguments,
        handler=run_web_fetch,
        read_only=True,
        engine_names={"langgraph"},
        concurrency_safe=True,
        interrupt_behavior="cancel",
        search_hint="open read fetch public URL webpage content",
        always_load=True,
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
