from datetime import timedelta

from .runtime import *

OPENAPI_TAGS = [
    {"name": "System", "description": "Runtime status, health checks, and debug entry points."},
    {"name": "Authentication", "description": "Local account sessions and optional GitHub OAuth login."},
    {"name": "Model Configuration", "description": "Manage chat, embedding, and rerank model service settings."},
    {"name": "Knowledge Bases", "description": "Create, read, update, and delete knowledge workspaces."},
    {"name": "Documents", "description": "Upload, parse, chunk, embed, reindex, and delete documents."},
    {"name": "RAG Debug", "description": "Inspect retrieval results, matched terms, scores, and vector backend details."},
    {"name": "Chat", "description": "Chat, RAG answers, streaming output, and answer references."},
    {"name": "Sessions", "description": "Session history, messages, rename, and delete operations."},
    {"name": "Memory", "description": "Manage per-user Mem0 long-term memories and recall settings."},
    {"name": "Extensions", "description": "Reserved integration endpoints outside the first core workflow."},
    {"name": "Skills", "description": "Inspect, install, and manage per-user Skills."},
]


app = FastAPI(
    title="AgentLens API",
    version="0.31.0",
    description=(
        "AgentLens API for a personal knowledge workspace. "
        "Core workflows include model configuration, document ingestion, RAG retrieval debugging, chat, and session management."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=OPENAPI_TAGS,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content=normalize_api_error_detail(exc.detail, exc.status_code))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    first_error = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(item) for item in first_error.get("loc", []) if item not in {"body", "query", "path"})
    reason = first_error.get("msg") or "Invalid parameter"
    message = f"{field} parameter error: {reason}" if field else f"Parameter error: {reason}"
    return JSONResponse(status_code=422, content=api_error_payload(42200, message, {"errors": exc.errors()}))


if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")


@app.get("/vendor/{asset_path:path}", include_in_schema=False)
def vendor_asset(asset_path: str) -> FileResponse:
    if not asset_path or Path(asset_path).name != asset_path:
        raise HTTPException(status_code=404, detail="Vendor asset not found.")
    for vendor_dir in (FRONTEND_BUILD_DIR / "vendor", FRONTEND_DIR / "react" / "public" / "vendor"):
        asset = vendor_dir / asset_path
        if asset.exists() and asset.is_file():
            return FileResponse(asset)
    raise HTTPException(status_code=404, detail="Vendor asset not found.")


if FRONTEND_VENDOR_DIR.exists():
    app.mount("/vendor", StaticFiles(directory=FRONTEND_VENDOR_DIR), name="vendor")


@app.get("/favicon.svg", include_in_schema=False)
@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    for asset in (FRONTEND_STATIC_DIR / "favicon.svg", FRONTEND_DIR / "react" / "public" / "favicon.svg"):
        if asset.exists() and asset.is_file():
            return FileResponse(asset, media_type="image/svg+xml")
    raise HTTPException(status_code=404, detail="Favicon not found.")


PUBLIC_API_PATHS = {
    "/api/health",
    "/api/runtime",
    "/api/auth/me",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/cli/device",
    "/api/auth/cli/device/token",
    "/api/mcp/oauth/callback",
}
PUBLIC_PREFIXES = ("/assets", "/vendor", "/docs", "/redoc", "/openapi.json", "/api/auth/oauth/", "/favicon.ico", "/favicon.svg")


def is_public_path(path: str) -> bool:
    return path == "/" or path in PUBLIC_API_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.method == "OPTIONS" or is_public_path(request.url.path):
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        user = get_current_user(request)
        if not user:
            return JSONResponse(status_code=401, content={"code": 40101, "message": "Please sign in first.", "data": None})
        request.state.current_user = user
        if ADOPT_LEGACY_DATA:
            adopt_legacy_data_for_user(int(user["id"]))
    return await call_next(request)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(FRONTEND_STATIC_DIR / "index.html")


@app.get("/api/health", tags=["System"], summary="Health check")
def health_check() -> dict[str, Any]:
    return api_success(
        {
            "status": "ok",
            "time": now_str(),
            "database": db.dialect,
            "vectorBackend": vector_store.backend,
        }
    )


@app.get("/api/runtime", tags=["System"], summary="Runtime information")
def runtime_info() -> dict[str, Any]:
    return api_success(
        {
            "database": db.dialect,
            "vectorBackend": vector_store.backend,
        }
    )


from .routers import routers
from .routers.approvals import approval_runner

for api_router in routers:
    app.include_router(api_router)


@app.on_event("startup")
def interrupt_stale_agent_runs() -> None:
    runtime_directories = [
        ("data", DATA_DIR),
        ("uploads", UPLOAD_DIR),
        ("skills", SKILL_DIR),
        ("skill_imports", SKILL_IMPORT_DIR),
        ("tool_results", TOOL_RESULT_DIR),
    ]
    if WORKSPACE_ENABLED:
        runtime_directories.append(("workspaces", WORKSPACE_DIR))
    require_runtime_paths(
        directories=runtime_directories,
        files=(("langgraph_checkpoint", LANGGRAPH_CHECKPOINT_DB),),
    )
    if SANDBOX_ENABLED:
        require_linux_sandbox(
            SANDBOX_COMMAND,
            SANDBOX_SHELL,
            SANDBOX_LIMIT_COMMAND,
        )
    agent_runs.interrupt_stale_runs()
    memory_operation_store.recover_interrupted(
        stale_before=datetime.now(),
    )
    memory_operation_store.purge_expired(
        before=datetime.now() - timedelta(days=30),
    )
    memory_operation_runner.start()
    approval_runner.start()


@app.on_event("shutdown")
def close_memory_runtime() -> None:
    approval_runner.stop()
    memory_operation_runner.stop()
    memory_manager.close()
