from fastapi import APIRouter, HTTPException, Request

from ..runtime import (
    ToolConfigUpdate,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_TIMEOUT,
    api_success,
    current_user_id,
    post_model_json,
    tool_configs,
)
from ..services.web_search import TavilyWebSearch, WebSearchError


router = APIRouter()
TOOL_CONFIG_TAGS = ["Tool Configuration"]
SUPPORTED_TOOL_NAMES = {"web_search"}


def require_tool_name(tool_name: str) -> str:
    if tool_name not in SUPPORTED_TOOL_NAMES:
        raise HTTPException(status_code=404, detail="Tool configuration not found.")
    return tool_name


def make_web_search_provider(api_key: str) -> TavilyWebSearch:
    return TavilyWebSearch(
        api_key=api_key,
        post_json=post_model_json,
        timeout=WEB_SEARCH_TIMEOUT,
        max_results=WEB_SEARCH_MAX_RESULTS,
    )


@router.get("/api/tool-configs", tags=TOOL_CONFIG_TAGS, summary="List tool configurations")
def list_tool_configs(request: Request) -> dict:
    return api_success(tool_configs.list_for_user(current_user_id(request)))


@router.put(
    "/api/tool-configs/{tool_name}",
    tags=TOOL_CONFIG_TAGS,
    summary="Save a tool configuration",
)
def save_tool_config(
    tool_name: str,
    payload: ToolConfigUpdate,
    request: Request,
) -> dict:
    require_tool_name(tool_name)
    try:
        data = tool_configs.upsert(
            current_user_id(request),
            tool_name,
            enabled=payload.enabled,
            api_key=payload.apiKey,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return api_success(data)


@router.delete(
    "/api/tool-configs/{tool_name}",
    tags=TOOL_CONFIG_TAGS,
    summary="Delete a tool configuration",
)
def delete_tool_config(tool_name: str, request: Request) -> dict:
    require_tool_name(tool_name)
    tool_configs.delete(current_user_id(request), tool_name)
    return api_success(True)


@router.post(
    "/api/tool-configs/{tool_name}/test",
    tags=TOOL_CONFIG_TAGS,
    summary="Test a tool connection",
)
def test_tool_config(tool_name: str, request: Request) -> dict:
    require_tool_name(tool_name)
    config = tool_configs.secret(
        current_user_id(request),
        tool_name,
        require_enabled=False,
    )
    if not config:
        raise HTTPException(
            status_code=400,
            detail="Save an API key before checking this tool.",
        )
    try:
        results = make_web_search_provider(config["api_key"]).search(
            "AgentLens connectivity check",
            top_k=1,
        )
    except WebSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return api_success(
        {
            "status": "available",
            "resultCount": len(results),
            "message": "Tavily connection check completed. This check used 1 credit.",
        }
    )
