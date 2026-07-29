from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
FRONTEND_BUILD_DIR = FRONTEND_DIR / "dist"
FRONTEND_STATIC_DIR = FRONTEND_BUILD_DIR if FRONTEND_BUILD_DIR.exists() else FRONTEND_DIR
FRONTEND_ASSETS_DIR = FRONTEND_STATIC_DIR / "assets" if FRONTEND_BUILD_DIR.exists() else FRONTEND_DIR
FRONTEND_VENDOR_DIR = FRONTEND_STATIC_DIR / "vendor" if FRONTEND_BUILD_DIR.exists() else FRONTEND_DIR / "react" / "public" / "vendor"
DATA_DIR = PROJECT_DIR / "data"

load_dotenv(BACKEND_DIR / ".env")

UPLOAD_DIR = Path(os.getenv("KNOWFLOW_UPLOAD_DIR", str(DATA_DIR / "uploads"))).expanduser()
if not UPLOAD_DIR.is_absolute():
    UPLOAD_DIR = (PROJECT_DIR / UPLOAD_DIR).resolve()

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, env_int(name, default)))


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def normalize_sqlite_db_url(raw_url: str) -> str:
    if not raw_url.startswith("sqlite:///"):
        return raw_url

    raw_path = raw_url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return raw_url

    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (PROJECT_DIR / raw_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


DB_URL = normalize_sqlite_db_url(os.getenv("KNOWFLOW_DB_URL", f"sqlite:///{(DATA_DIR / 'knowflow.db').as_posix()}"))
SKILL_DIR = Path(os.getenv("KNOWFLOW_SKILL_DIR", str(DATA_DIR / "skills"))).expanduser()
if not SKILL_DIR.is_absolute():
    SKILL_DIR = (PROJECT_DIR / SKILL_DIR).resolve()
SKILL_IMPORT_DIR = DATA_DIR / "skill-imports"
SKILL_MAX_ARCHIVE_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES",
    5 * 1024 * 1024,
    1024,
    20 * 1024 * 1024,
)
SKILL_MAX_EXTRACTED_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_EXTRACTED_BYTES",
    20 * 1024 * 1024,
    1024,
    100 * 1024 * 1024,
)
SKILL_MAX_FILES = bounded_env_int("KNOWFLOW_SKILL_MAX_FILES", 200, 1, 1000)
SKILL_MAX_FILE_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_FILE_BYTES",
    2 * 1024 * 1024,
    1024,
    10 * 1024 * 1024,
)
SKILL_MAX_DEPTH = bounded_env_int("KNOWFLOW_SKILL_MAX_DEPTH", 8, 1, 16)
SKILL_MAX_BODY_CHARS = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_BODY_CHARS",
    50_000,
    1000,
    200_000,
)
SKILL_IMPORT_TTL = bounded_env_int("KNOWFLOW_SKILL_IMPORT_TTL", 900, 60, 3600)
SKILL_GITHUB_TIMEOUT = bounded_env_int(
    "KNOWFLOW_SKILL_GITHUB_TIMEOUT",
    15,
    1,
    60,
)
SKILL_DIR.mkdir(parents=True, exist_ok=True)
SKILL_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_BACKEND = os.getenv("KNOWFLOW_VECTOR_BACKEND", "local").lower()
CHROMA_DIR = Path(os.getenv("KNOWFLOW_CHROMA_DIR", str(DATA_DIR / "chroma")))
SECRET_KEY = os.getenv("KNOWFLOW_SECRET_KEY", "change-this-dev-secret")
BASE_URL = os.getenv("KNOWFLOW_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
OAUTH_RETURN_ORIGINS = tuple(
    origin.strip().rstrip("/")
    for origin in os.getenv(
        "KNOWFLOW_OAUTH_RETURN_ORIGINS",
        "http://127.0.0.1:5173,http://localhost:5173",
    ).split(",")
    if origin.strip()
)
GITHUB_CLIENT_ID = os.getenv("KNOWFLOW_GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("KNOWFLOW_GITHUB_CLIENT_SECRET", "")
SESSION_COOKIE_NAME = "knowflow_session"
AUTH_SESSION_TTL_SECONDS = env_int("KNOWFLOW_AUTH_SESSION_TTL", 7 * 24 * 60 * 60)
COOKIE_SECURE = os.getenv("KNOWFLOW_COOKIE_SECURE", "0") == "1"
ADOPT_LEGACY_DATA = os.getenv("KNOWFLOW_ADOPT_LEGACY_DATA", "0") == "1"
CHUNK_SIZE = env_int("KNOWFLOW_CHUNK_SIZE", 800)
CHUNK_OVERLAP = env_int("KNOWFLOW_CHUNK_OVERLAP", 120)
DEFAULT_TOP_K = env_int("KNOWFLOW_TOP_K", 5)
RETRIEVAL_SCORE_THRESHOLD = env_float("KNOWFLOW_RAG_SCORE_THRESHOLD", 0.25)
MODEL_REQUEST_TIMEOUT = env_int("KNOWFLOW_MODEL_REQUEST_TIMEOUT", 45)
MODEL_TRUST_ENV = os.getenv("KNOWFLOW_MODEL_TRUST_ENV", "0") == "1"
WEB_SEARCH_TIMEOUT = max(1, env_int("KNOWFLOW_WEB_SEARCH_TIMEOUT", 15))
WEB_SEARCH_MAX_RESULTS = max(
    1,
    min(10, env_int("KNOWFLOW_WEB_SEARCH_MAX_RESULTS", 5)),
)
MCP_CONNECT_TIMEOUT = max(1, env_int("KNOWFLOW_MCP_CONNECT_TIMEOUT", 10))
MCP_REQUEST_TIMEOUT = max(1, env_int("KNOWFLOW_MCP_REQUEST_TIMEOUT", 30))
MCP_APPROVAL_TIMEOUT = max(10, env_int("KNOWFLOW_MCP_APPROVAL_TIMEOUT", 300))
MCP_MAX_RESPONSE_BYTES = max(4096, env_int("KNOWFLOW_MCP_MAX_RESPONSE_BYTES", 1024 * 1024))
MCP_MAX_EXPOSED_TOOLS = max(1, env_int("KNOWFLOW_MCP_MAX_EXPOSED_TOOLS", 32))
MCP_ALLOW_PRIVATE_NETWORKS = os.getenv("KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS", "0") == "1"
MEMORY_ENABLED = os.getenv("KNOWFLOW_MEMORY_ENABLED", "0") == "1"
MEMORY_DEFAULT_ENABLED = (
    os.getenv("KNOWFLOW_MEMORY_DEFAULT_ENABLED", "0") == "1"
)
MEMORY_TOP_K = bounded_env_int("KNOWFLOW_MEMORY_TOP_K", 5, 1, 20)
MEMORY_LIST_LIMIT = bounded_env_int(
    "KNOWFLOW_MEMORY_LIST_LIMIT",
    100,
    1,
    500,
)
MEMORY_SEARCH_THRESHOLD = max(
    0.0,
    min(1.0, env_float("KNOWFLOW_MEMORY_SEARCH_THRESHOLD", 0.2)),
)
MEMORY_LLM_API_KEY = os.getenv("KNOWFLOW_MEMORY_LLM_API_KEY", "")
MEMORY_LLM_MODEL = os.getenv(
    "KNOWFLOW_MEMORY_LLM_MODEL",
    "gpt-5-mini",
)
MEMORY_LLM_BASE_URL = os.getenv(
    "KNOWFLOW_MEMORY_LLM_BASE_URL",
    "https://api.openai.com/v1",
).rstrip("/")
MEMORY_EMBEDDER_API_KEY = os.getenv(
    "KNOWFLOW_MEMORY_EMBEDDER_API_KEY",
    MEMORY_LLM_API_KEY,
)
MEMORY_EMBEDDER_MODEL = os.getenv(
    "KNOWFLOW_MEMORY_EMBEDDER_MODEL",
    "text-embedding-3-small",
)
MEMORY_EMBEDDER_BASE_URL = os.getenv(
    "KNOWFLOW_MEMORY_EMBEDDER_BASE_URL",
    MEMORY_LLM_BASE_URL,
).rstrip("/")
MEMORY_EMBEDDING_DIMS = bounded_env_int(
    "KNOWFLOW_MEMORY_EMBEDDING_DIMS",
    1536,
    1,
    65536,
)
MEMORY_QDRANT_PATH = Path(
    os.getenv(
        "KNOWFLOW_MEMORY_QDRANT_PATH",
        str(DATA_DIR / "mem0" / "qdrant"),
    )
).expanduser()
if not MEMORY_QDRANT_PATH.is_absolute():
    MEMORY_QDRANT_PATH = (PROJECT_DIR / MEMORY_QDRANT_PATH).resolve()
MEMORY_HISTORY_DB = Path(
    os.getenv(
        "KNOWFLOW_MEMORY_HISTORY_DB",
        str(DATA_DIR / "mem0" / "history.db"),
    )
).expanduser()
if not MEMORY_HISTORY_DB.is_absolute():
    MEMORY_HISTORY_DB = (PROJECT_DIR / MEMORY_HISTORY_DB).resolve()


def memory_backend_configured() -> bool:
    return bool(
        MEMORY_ENABLED
        and MEMORY_LLM_API_KEY.strip()
        and MEMORY_EMBEDDER_API_KEY.strip()
    )


def build_mem0_config() -> dict[str, object]:
    return {
        "llm": {
            "provider": "openai",
            "config": {
                "api_key": MEMORY_LLM_API_KEY,
                "model": MEMORY_LLM_MODEL,
                "openai_base_url": MEMORY_LLM_BASE_URL,
                "temperature": 0.1,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": MEMORY_EMBEDDER_API_KEY,
                "model": MEMORY_EMBEDDER_MODEL,
                "openai_base_url": MEMORY_EMBEDDER_BASE_URL,
                "embedding_dims": MEMORY_EMBEDDING_DIMS,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "knowflow_memories",
                "embedding_model_dims": MEMORY_EMBEDDING_DIMS,
                "path": str(MEMORY_QDRANT_PATH),
                "on_disk": True,
            },
        },
        "history_db_path": str(MEMORY_HISTORY_DB),
        "custom_instructions": (
            "Only retain durable user facts, preferences, goals, decisions, "
            "and explicit corrections. Ignore transient requests, tool output, "
            "credentials, passwords, tokens, API keys, and unsupported guesses. "
            "Preserve each extracted memory in the same primary language as the "
            "user's original statement. For Chinese input, store the memory in "
            "concise Simplified Chinese. Never translate Chinese memories into English."
        ),
    }
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
IMAGE_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}
MAX_UPLOAD_FILE_SIZE = env_int("KNOWFLOW_MAX_UPLOAD_FILE_SIZE", 25 * 1024 * 1024)
ALLOWED_UPLOAD_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".log",
    ".yaml",
    ".yml",
    ".xml",
    ".json",
    ".csv",
    ".tsv",
    ".html",
    ".htm",
    ".rtf",
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    *IMAGE_SUFFIXES,
}
