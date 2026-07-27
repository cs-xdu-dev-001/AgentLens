"""API router registry."""

from .auth import router as auth_router
from .model_configs import router as model_config_router
from .tool_configs import router as tool_config_router
from .knowledge import router as knowledge_router
from .chat import router as chat_router
from .extensions import router as extension_router
from .mcp import router as mcp_router
from .approvals import router as approval_router
from .skills import router as skill_router

routers = [
    auth_router,
    model_config_router,
    tool_config_router,
    knowledge_router,
    chat_router,
    extension_router,
    mcp_router,
    approval_router,
    skill_router,
]
