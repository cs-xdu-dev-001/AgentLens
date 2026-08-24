from __future__ import annotations

import os
from importlib import resources
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .memory import Mem0MemoryProvider
from .mcp_client import McpRemoteClient
from .mcp_config import MCP_MAX_EXPOSED_TOOLS
from .mcp_security import validate_remote_url, validate_static_headers
from .skill_manifest import SkillManifest, parse_skill_markdown


LOCAL_SKILL_BODY_LIMIT = 200_000
LOCAL_SKILL_MAX_FILES = 256
LOCAL_SKILL_MAX_FILE_BYTES = 2 * 1024 * 1024
LOCAL_SKILL_MAX_TOTAL_BYTES = 10 * 1024 * 1024


class LocalExtensionError(ValueError):
    pass


def _nested(value: dict[str, Any], key: str) -> dict[str, Any]:
    child = value.get(key)
    if not isinstance(child, dict):
        child = {}
        value[key] = child
    return child


def _safe_slug(value: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else "-"
        for character in str(value or "").strip()
    )
    return "-".join(part for part in normalized.split("-") if part)[:80]


def _validate_api_url(value: Any) -> str:
    clean = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(clean)
    except (ValueError, UnicodeError) as exc:
        raise LocalExtensionError("API地址格式无效。") from exc
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in {"https", "http"} or (
        parsed.scheme == "http" and not loopback
    ):
        raise LocalExtensionError("API地址必须使用HTTPS；仅本机地址允许HTTP。")
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise LocalExtensionError("API地址格式无效。")
    return clean


class LocalExtensionStore:
    """Standalone CLI capability configuration with split public/secrets files."""

    def __init__(self, config_store: Any, data_root: Path) -> None:
        self.config_store = config_store
        self.data_root = Path(data_root).resolve()
        self._memory_provider: Mem0MemoryProvider | None = None
        self._memory_signature: tuple[Any, ...] | None = None

    def _reset_memory_provider(self) -> None:
        if self._memory_provider is not None:
            self._memory_provider.close()
        self._memory_provider = None
        self._memory_signature = None

    def web_search(self) -> dict[str, Any]:
        public = _nested(self.config_store.load_public(), "tools")
        value = public.get("web_search")
        value = value if isinstance(value, dict) else {}
        secret_tools = _nested(self.config_store.load_credentials(), "tools")
        secret = secret_tools.get("web_search")
        secret = secret if isinstance(secret, dict) else {}
        environment_key = os.getenv("KNOWFLOW_TAVILY_API_KEY", "").strip()
        api_key = environment_key or str(secret.get("api_key") or "")
        enabled = bool(value.get("enabled", bool(api_key)))
        return {
            "provider": "tavily",
            "enabled": enabled,
            "configured": bool(api_key),
            "api_key": api_key,
        }

    def save_web_search(self, *, api_key: str, enabled: bool = True) -> None:
        clean_key = str(api_key or "").strip()
        if enabled and not clean_key:
            raise LocalExtensionError("Tavily Key不能为空。")

        def update_public(value: dict[str, Any]) -> None:
            _nested(value, "tools")["web_search"] = {
                "provider": "tavily",
                "enabled": bool(enabled),
            }

        def update_credentials(value: dict[str, Any]) -> None:
            tools = _nested(value, "tools")
            tools["web_search"] = {"api_key": clean_key}

        self.config_store.update_public(update_public)
        self.config_store.update_credentials(update_credentials)

    def set_web_search_enabled(self, enabled: bool) -> None:
        current = self.web_search()
        if enabled and not current["configured"]:
            raise LocalExtensionError("请先配置Tavily Key。")

        def update(value: dict[str, Any]) -> None:
            tools = _nested(value, "tools")
            item = tools.get("web_search")
            item = item if isinstance(item, dict) else {"provider": "tavily"}
            item["enabled"] = bool(enabled)
            tools["web_search"] = item

        self.config_store.update_public(update)

    @staticmethod
    def _server_public(server: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(server.get("id") or ""),
            "name": str(server.get("name") or ""),
            "slug": str(server.get("slug") or ""),
            "url": str(server.get("url") or ""),
            "authType": str(server.get("authType") or "none"),
            "enabled": bool(server.get("enabled", True)),
            "status": str(server.get("status") or "disconnected"),
            "enabledTools": list(server.get("enabledTools") or []),
            "tools": list(server.get("tools") or []),
            "errorCode": server.get("errorCode"),
        }

    def _mcp_public(self) -> dict[str, Any]:
        return _nested(self.config_store.load_public(), "mcp")

    def _mcp_credentials(self) -> dict[str, Any]:
        return _nested(self.config_store.load_credentials(), "mcp")

    def list_mcp(self) -> list[dict[str, Any]]:
        servers = self._mcp_public().get("servers")
        if not isinstance(servers, list):
            return []
        return [self._server_public(item) for item in servers if isinstance(item, dict)]

    def get_owned(self, _user_id: int, server_id: Any) -> dict[str, Any] | None:
        target = str(server_id)
        return next((item for item in self.list_mcp() if item["id"] == target), None)

    def secret(self, _user_id: int, server_id: Any, **_kwargs: Any) -> dict[str, Any] | None:
        server = self.get_owned(1, server_id)
        if server is None:
            return None
        secrets = self._mcp_credentials().get("servers")
        secrets = secrets if isinstance(secrets, dict) else {}
        credentials = secrets.get(str(server_id))
        credentials = dict(credentials) if isinstance(credentials, dict) else {}
        headers = credentials.get("headers")
        headers = dict(headers) if isinstance(headers, dict) else {}
        token = credentials.get("access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        credentials["headers"] = validate_static_headers(headers)
        return {**server, "credentials": credentials}

    def add_mcp(
        self,
        *,
        name: str,
        url: str,
        auth_type: str = "none",
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise LocalExtensionError("MCP名称不能为空。")
        clean_url = validate_remote_url(str(url or "").strip(), allow_private=False)
        clean_auth = str(auth_type or "none").strip().lower()
        if clean_auth not in {"none", "headers", "oauth"}:
            raise LocalExtensionError("认证类型必须是none、headers或oauth。")
        clean_headers = validate_static_headers(headers or {})
        server_id = uuid4().hex[:12]
        slug = _safe_slug(clean_name) or f"mcp-{server_id[:6]}"
        server = {
            "id": server_id,
            "name": clean_name,
            "slug": slug,
            "url": clean_url,
            "authType": clean_auth,
            "enabled": True,
            "status": "disconnected",
            "enabledTools": [],
            "tools": [],
        }

        def update_public(value: dict[str, Any]) -> None:
            mcp = _nested(value, "mcp")
            servers = mcp.get("servers")
            servers = list(servers) if isinstance(servers, list) else []
            servers.append(server)
            mcp["servers"] = servers

        def update_credentials(value: dict[str, Any]) -> None:
            mcp = _nested(value, "mcp")
            servers = mcp.get("servers")
            servers = dict(servers) if isinstance(servers, dict) else {}
            servers[server_id] = {"headers": clean_headers}
            mcp["servers"] = servers

        self.config_store.update_public(update_public)
        self.config_store.update_credentials(update_credentials)
        return self._server_public(server)

    def remove_mcp(self, server_id: str) -> bool:
        target = str(server_id)
        removed = False

        def update_public(value: dict[str, Any]) -> None:
            nonlocal removed
            mcp = _nested(value, "mcp")
            servers = mcp.get("servers")
            servers = list(servers) if isinstance(servers, list) else []
            kept = [item for item in servers if str(item.get("id")) != target]
            removed = len(kept) != len(servers)
            mcp["servers"] = kept

        def update_credentials(value: dict[str, Any]) -> None:
            servers = _nested(_nested(value, "mcp"), "servers")
            servers.pop(target, None)

        self.config_store.update_public(update_public)
        self.config_store.update_credentials(update_credentials)
        return removed

    def _update_server(self, server_id: Any, **changes: Any) -> dict[str, Any]:
        target = str(server_id)
        updated: dict[str, Any] | None = None

        def update(value: dict[str, Any]) -> None:
            nonlocal updated
            mcp = _nested(value, "mcp")
            servers = mcp.get("servers")
            servers = list(servers) if isinstance(servers, list) else []
            for item in servers:
                if isinstance(item, dict) and str(item.get("id")) == target:
                    item.update(changes)
                    updated = dict(item)
                    break
            mcp["servers"] = servers

        self.config_store.update_public(update)
        if updated is None:
            raise LocalExtensionError("MCP服务器不存在。")
        return self._server_public(updated)

    def discover_mcp(self, server_id: str) -> dict[str, Any]:
        server = self.secret(1, server_id)
        if server is None:
            raise LocalExtensionError("MCP服务器不存在。")
        client = McpRemoteClient(
            server_id,
            server["url"],
            headers=(server.get("credentials") or {}).get("headers") or {},
            server_name=server["name"],
            allow_private=False,
        )
        import asyncio

        try:
            tools = asyncio.run(client.discover_tools())
        except Exception:
            self._update_server(server_id, status="error", errorCode="mcp_connect_failed")
            raise
        enabled = [
            str(item.get("modelName") or "")
            for item in tools
            if item.get("modelName")
        ][:MCP_MAX_EXPOSED_TOOLS]
        return self._update_server(
            server_id,
            status="connected",
            errorCode=None,
            tools=tools,
            enabledTools=enabled,
        )

    def set_status(
        self,
        _user_id: int,
        server_id: Any,
        status: str,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        return self._update_server(server_id, status=status, errorCode=error_code)

    def save_credentials(self, _user_id: int, server_id: Any, credentials: dict[str, Any]) -> None:
        target = str(server_id)

        def update(value: dict[str, Any]) -> None:
            servers = _nested(_nested(value, "mcp"), "servers")
            servers[target] = dict(credentials)

        self.config_store.update_credentials(update)

    @staticmethod
    def encrypt_credentials(value: dict[str, Any]) -> dict[str, Any]:
        return dict(value)

    @staticmethod
    def decrypt_credentials(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def create_oauth_session(self, _user_id: int, server_id: Any, **payload: Any) -> None:
        record = {"server_id": str(server_id), **payload}

        def update(value: dict[str, Any]) -> None:
            mcp = _nested(value, "mcp")
            sessions = mcp.get("oauth_sessions")
            sessions = list(sessions) if isinstance(sessions, list) else []
            sessions.append(record)
            mcp["oauth_sessions"] = sessions[-20:]

        self.config_store.update_credentials(update)

    def delete_expired_oauth_sessions(self, _user_id: int, *, now: str) -> None:
        def update(value: dict[str, Any]) -> None:
            mcp = _nested(value, "mcp")
            sessions = mcp.get("oauth_sessions")
            sessions = list(sessions) if isinstance(sessions, list) else []
            mcp["oauth_sessions"] = [
                item for item in sessions
                if isinstance(item, dict) and str(item.get("expires_at") or "") > now
            ]

        self.config_store.update_credentials(update)

    def consume_oauth_session_by_state(self, _user_id: int, state_hash: str, *, now: str) -> dict[str, Any] | None:
        found: dict[str, Any] | None = None

        def update(value: dict[str, Any]) -> None:
            nonlocal found
            mcp = _nested(value, "mcp")
            sessions = mcp.get("oauth_sessions")
            sessions = list(sessions) if isinstance(sessions, list) else []
            kept = []
            for item in sessions:
                if (
                    found is None
                    and isinstance(item, dict)
                    and item.get("state_hash") == state_hash
                    and str(item.get("expires_at") or "") > now
                ):
                    found = dict(item)
                else:
                    kept.append(item)
            mcp["oauth_sessions"] = kept

        self.config_store.update_credentials(update)
        return found

    def _local_skill_root(self, *, create: bool = False) -> Path:
        root = self.data_root / "skills"
        if root.is_symlink():
            raise LocalExtensionError("Skill存储目录不能是符号链接。")
        if create:
            root.mkdir(parents=True, exist_ok=True)
        try:
            root.resolve().relative_to(self.data_root)
        except ValueError as exc:
            raise LocalExtensionError("Skill存储目录无效。") from exc
        return root

    def skill_roots(self) -> list[Path]:
        roots = [self._local_skill_root()]
        try:
            builtin = resources.files("knowflow").joinpath("builtin_skills")
            builtin_path = Path(str(builtin))
            if builtin_path.is_dir():
                roots.insert(0, builtin_path)
        except Exception:
            pass
        return roots

    @staticmethod
    def _validate_skill_source(source: Path) -> None:
        file_count = 0
        total_bytes = 0
        for entry in source.rglob("*"):
            if entry.is_symlink():
                raise LocalExtensionError("Skill目录不能包含符号链接。")
            if entry.is_dir():
                continue
            if not entry.is_file():
                raise LocalExtensionError("Skill目录包含不支持的文件类型。")
            file_count += 1
            if file_count > LOCAL_SKILL_MAX_FILES:
                raise LocalExtensionError("Skill目录文件数量过多。")
            size = entry.stat().st_size
            if size > LOCAL_SKILL_MAX_FILE_BYTES:
                raise LocalExtensionError("Skill目录包含过大的单个文件。")
            total_bytes += size
            if total_bytes > LOCAL_SKILL_MAX_TOTAL_BYTES:
                raise LocalExtensionError("Skill目录总体积过大。")

    def install_skill(self, source: Path) -> dict[str, Any]:
        source = Path(source).expanduser()
        if source.is_symlink():
            raise LocalExtensionError("Skill来源不能是符号链接。")
        source = source.resolve()
        manifest_path = source / "SKILL.md" if source.is_dir() else source
        if not manifest_path.is_file() or manifest_path.name != "SKILL.md":
            raise LocalExtensionError("Skill来源必须是SKILL.md或包含它的目录。")
        if manifest_path.is_symlink():
            raise LocalExtensionError("Skill清单不能是符号链接。")
        if manifest_path.stat().st_size > LOCAL_SKILL_MAX_FILE_BYTES:
            raise LocalExtensionError("Skill清单文件过大。")
        manifest = parse_skill_markdown(
            manifest_path.read_text(encoding="utf-8"),
            max_body_chars=LOCAL_SKILL_BODY_LIMIT,
        )
        destination = self._local_skill_root(create=True) / manifest.slug
        if destination.exists():
            raise LocalExtensionError("同名Skill已安装。")
        if manifest_path.parent == source:
            self._validate_skill_source(source)
            shutil.copytree(source, destination, symlinks=True)
        else:
            destination.mkdir()
            shutil.copy2(manifest_path, destination / "SKILL.md")
        return self._skill_row(destination, manifest, "local")

    def remove_skill(self, slug: str) -> bool:
        normalized_slug = _safe_slug(slug)
        if not normalized_slug:
            raise LocalExtensionError("Skill名称不能为空。")
        root = self._local_skill_root().resolve()
        target = root / normalized_slug
        try:
            target.resolve().relative_to(root)
        except ValueError as exc:
            raise LocalExtensionError("Skill路径无效。") from exc
        if target.is_symlink():
            raise LocalExtensionError("Skill路径无效。")
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True

    @staticmethod
    def _skill_row(path: Path, manifest: SkillManifest, source: str) -> dict[str, Any]:
        digest = int(manifest.content_hash[:12], 16)
        return {
            "id": digest,
            "packageId": digest,
            "installationId": digest,
            "slug": manifest.slug,
            "name": manifest.display_name,
            "displayName": manifest.display_name,
            "description": manifest.description,
            "version": manifest.version,
            "contentHash": manifest.content_hash,
            "sourceKind": source,
            "requiredTools": list(manifest.required_tools),
            "requiredMcp": list(manifest.required_mcp),
            "planning": manifest.planning,
            "systemMessage": manifest.body,
            "path": str(path),
            "enabled": True,
        }

    def list_skills(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root_index, root in enumerate(self.skill_roots()):
            if not root.is_dir():
                continue
            resolved_root = root.resolve()
            for manifest_path in sorted(root.glob("*/SKILL.md")):
                if manifest_path.is_symlink() or manifest_path.parent.is_symlink():
                    continue
                try:
                    manifest_path.resolve().relative_to(resolved_root)
                except ValueError:
                    continue
                try:
                    manifest = parse_skill_markdown(
                        manifest_path.read_text(encoding="utf-8"),
                        max_body_chars=LOCAL_SKILL_BODY_LIMIT,
                    )
                except Exception:
                    continue
                if manifest.slug in seen:
                    continue
                seen.add(manifest.slug)
                rows.append(
                    self._skill_row(
                        manifest_path.parent,
                        manifest,
                        "bundled" if root_index == 0 and len(self.skill_roots()) > 1 else "local",
                    )
                )
        return rows

    def activation_candidates(self, _user_id: int, available_tools: Any) -> list[dict[str, Any]]:
        available = set(str(item) for item in available_tools)
        return [
            item for item in self.list_skills()
            if set(item["requiredTools"]).issubset(available)
            and set(item["requiredMcp"]).issubset(available)
        ]

    def resolve_for_activation(self, _user_id: int, skill: Any, available_tools: Any) -> dict[str, Any]:
        candidates = self.activation_candidates(1, available_tools)
        target = str(skill)
        for item in candidates:
            if target in {str(item["id"]), item["slug"]}:
                return item
        raise LocalExtensionError("Skill不存在或依赖尚未满足。")

    def read_text_resource(self, _user_id: int, package_id: int, relative_path: str) -> str:
        item = next((row for row in self.list_skills() if int(row["packageId"]) == int(package_id)), None)
        if item is None:
            raise LocalExtensionError("Skill不存在。")
        root = Path(item["path"]).resolve()
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise LocalExtensionError("Skill资源路径无效。") from exc
        if not target.is_file() or target.is_symlink():
            raise LocalExtensionError("Skill资源不存在。")
        return target.read_text(encoding="utf-8")[:LOCAL_SKILL_BODY_LIMIT]

    def memory_settings(self) -> dict[str, Any]:
        public = _nested(self.config_store.load_public(), "memory")
        secret = _nested(self.config_store.load_credentials(), "memory")
        enabled = bool(public.get("enabled", False))
        configured = bool(
            secret.get("llm_api_key")
            and secret.get("embedder_api_key")
            and public.get("llm_base_url")
            and public.get("embedder_base_url")
            and public.get("llm_model")
            and public.get("embedder_model")
        )
        return {**public, "enabled": enabled, "configured": configured}

    def save_memory(self, *, public: dict[str, Any], secrets: dict[str, str]) -> None:
        normalized = {
            **public,
            "llm_base_url": _validate_api_url(public.get("llm_base_url")),
            "embedder_base_url": _validate_api_url(public.get("embedder_base_url")),
            "llm_model": str(public.get("llm_model") or "").strip(),
            "embedder_model": str(public.get("embedder_model") or "").strip(),
            "embedding_dims": max(1, min(65536, int(public.get("embedding_dims") or 1536))),
        }
        normalized_secrets = {
            "llm_api_key": str(secrets.get("llm_api_key") or "").strip(),
            "embedder_api_key": str(secrets.get("embedder_api_key") or "").strip(),
        }
        if not normalized["llm_model"] or not normalized["embedder_model"]:
            raise LocalExtensionError("记忆模型名称不能为空。")
        if not all(normalized_secrets.values()):
            raise LocalExtensionError("记忆模型Key不能为空。")

        def update_public(value: dict[str, Any]) -> None:
            value["memory"] = normalized

        def update_credentials(value: dict[str, Any]) -> None:
            value["memory"] = normalized_secrets

        self.config_store.update_public(update_public)
        self.config_store.update_credentials(update_credentials)
        self._reset_memory_provider()

    def set_memory_enabled(self, enabled: bool) -> None:
        settings = self.memory_settings()
        if enabled and not settings["configured"]:
            raise LocalExtensionError("请先运行agentlens memory configure。")

        def update(value: dict[str, Any]) -> None:
            memory = _nested(value, "memory")
            memory["enabled"] = bool(enabled)

        self.config_store.update_public(update)
        if not enabled:
            self._reset_memory_provider()

    def memory_provider(self) -> Mem0MemoryProvider | None:
        settings = self.memory_settings()
        if not settings["enabled"] or not settings["configured"]:
            self._reset_memory_provider()
            return None
        secret = _nested(self.config_store.load_credentials(), "memory")
        dims = max(1, min(65536, int(settings.get("embedding_dims") or 1536)))
        signature = (
            settings.get("llm_base_url"),
            settings.get("llm_model"),
            settings.get("embedder_base_url"),
            settings.get("embedder_model"),
            dims,
            secret.get("llm_api_key"),
            secret.get("embedder_api_key"),
        )
        if self._memory_provider is not None and self._memory_signature == signature:
            return self._memory_provider
        self._reset_memory_provider()
        memory_root = self.data_root / "mem0"
        memory_root.mkdir(parents=True, exist_ok=True)
        config = {
            "llm": {
                "provider": "openai",
                "config": {
                    "api_key": str(secret["llm_api_key"]),
                    "model": str(settings["llm_model"]),
                    "openai_base_url": str(settings["llm_base_url"]).rstrip("/"),
                    "temperature": 0.1,
                },
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "api_key": str(secret["embedder_api_key"]),
                    "model": str(settings["embedder_model"]),
                    "openai_base_url": str(settings["embedder_base_url"]).rstrip("/"),
                    "embedding_dims": dims,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "knowflow_cli_memories",
                    "embedding_model_dims": dims,
                    "path": str(memory_root / "qdrant"),
                    "on_disk": True,
                },
            },
            "history_db_path": str(memory_root / "history.db"),
            "custom_instructions": (
                "Only retain durable user facts, preferences, goals, decisions, and explicit corrections. "
                "Ignore transient requests, tool output, credentials, passwords, tokens, and API keys. "
                "Preserve the user's primary language; store Chinese memories in concise Simplified Chinese."
            ),
        }
        self._memory_provider = Mem0MemoryProvider(config=config)
        self._memory_signature = signature
        return self._memory_provider

    def capability_status(self) -> dict[str, Any]:
        web = self.web_search()
        mcp = self.list_mcp()
        skills = [
            {
                key: item.get(key)
                for key in (
                    "slug",
                    "name",
                    "displayName",
                    "description",
                    "version",
                    "sourceKind",
                    "requiredTools",
                    "requiredMcp",
                    "enabled",
                )
            }
            for item in self.list_skills()
        ]
        memory = self.memory_settings()
        return {
            "webSearch": {key: value for key, value in web.items() if key != "api_key"},
            "mcp": {
                "count": len(mcp),
                "connected": sum(1 for item in mcp if item["enabled"] and item["status"] == "connected"),
                "servers": mcp,
            },
            "skills": {"count": len(skills), "items": skills},
            "memory": memory,
        }
