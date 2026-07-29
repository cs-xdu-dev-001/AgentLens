from __future__ import annotations

import importlib
import importlib.metadata
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol


REDACTED = "[敏感信息已移除]"
logger = logging.getLogger(__name__)
_NAMED_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret)"
    r"\b\s*[:=]\s*[\"']?(?:Bearer\s+)?[^\s,;\"']+"
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)\bAuthorization\s*:\s*Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
)
_KNOWN_TOKEN_PATTERN = re.compile(
    r"(?i)(?:sk|tvly|ghp|github_pat)_[A-Za-z0-9_-]{8,}"
    r"|sk-[A-Za-z0-9_-]{8,}"
    r"|tvly-[A-Za-z0-9_-]{8,}"
)


class MemoryUnavailableError(RuntimeError):
    pass


class MemoryNotFoundError(LookupError):
    pass


class MemoryProvider(Protocol):
    def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def remember(
        self,
        *,
        user_id: int,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...

    def list(
        self,
        *,
        user_id: int,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def update(
        self,
        *,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> dict[str, Any]: ...

    def delete(self, *, user_id: int, memory_id: str) -> None: ...

    def delete_all(self, *, user_id: int) -> None: ...


def redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    text = _AUTHORIZATION_PATTERN.sub(REDACTED, text)
    text = _NAMED_SECRET_PATTERN.sub(REDACTED, text)
    return _KNOWN_TOKEN_PATTERN.sub(REDACTED, text)


def sanitize_memory_messages(
    messages: list[dict[str, str]],
) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role") or "").strip()
        content = redact_sensitive_text(str(message.get("content") or ""))[:12000]
        if role in {"user", "assistant"} and content.strip():
            sanitized.append({"role": role, "content": content})
    return sanitized


def _results(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("results", [])
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


class Mem0MemoryProvider:
    def __init__(
        self,
        *,
        client: Any | None = None,
        config: dict[str, Any] | None = None,
        search_threshold: float = 0.2,
        rerank: bool = False,
    ):
        self._client = client
        self._config = dict(config or {})
        self.search_threshold = max(0.0, min(1.0, float(search_threshold)))
        self.rerank = bool(rerank)
        self._lock = threading.Lock()
        self._initialization_error = ""

    @property
    def configured(self) -> bool:
        return self._client is not None or bool(self._config)

    @property
    def initialization_error(self) -> str:
        return self._initialization_error

    @property
    def version(self) -> str:
        try:
            return importlib.metadata.version("mem0ai")
        except importlib.metadata.PackageNotFoundError:
            return "not-installed"

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._config:
            raise MemoryUnavailableError("Mem0尚未配置。")
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                os.environ.setdefault("MEM0_TELEMETRY", "False")
                memory_class = importlib.import_module("mem0").Memory
                self._client = memory_class.from_config(self._config)
                self._initialization_error = ""
            except Exception as exc:
                self._initialization_error = type(exc).__name__
                raise MemoryUnavailableError(
                    "Mem0初始化失败，请检查记忆模型和向量存储配置。"
                ) from exc
        return self._client

    def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        clean_query = str(query or "").strip()
        if not clean_query:
            return []
        result = self._get_client().search(
            clean_query,
            top_k=max(1, min(20, int(limit))),
            filters={"user_id": str(user_id)},
            threshold=self.search_threshold,
            rerank=self.rerank,
        )
        return _results(result)

    def remember(
        self,
        *,
        user_id: int,
        messages: list[dict[str, str]],
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        sanitized = sanitize_memory_messages(messages)
        if not sanitized:
            return []
        source = dict(metadata or {})
        mem0_metadata = {
            "source_session_id": source.get("session_id"),
            "source_message_id": source.get("message_id"),
            "source_operation_id": source.get("operation_id"),
            "source": "knowflow_chat",
        }
        result = self._get_client().add(
            sanitized,
            user_id=str(user_id),
            metadata=mem0_metadata,
            infer=True,
        )
        return _results(result)

    def list(
        self,
        *,
        user_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = self._get_client().get_all(
            filters={"user_id": str(user_id)},
            top_k=max(1, min(500, int(limit))),
        )
        return _results(result)

    def _owned(self, user_id: int, memory_id: str) -> dict[str, Any]:
        memory = self._get_client().get(str(memory_id))
        if not isinstance(memory, dict):
            raise MemoryNotFoundError(memory_id)
        if str(memory.get("user_id") or "") != str(user_id):
            raise MemoryNotFoundError(memory_id)
        return dict(memory)

    def update(
        self,
        *,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> dict[str, Any]:
        self._owned(user_id, memory_id)
        clean_content = redact_sensitive_text(str(content or "").strip())
        if not clean_content:
            raise ValueError("记忆内容不能为空。")
        result = self._get_client().update(str(memory_id), text=clean_content)
        if isinstance(result, dict):
            return dict(result)
        return self._owned(user_id, memory_id)

    def delete(self, *, user_id: int, memory_id: str) -> None:
        self._owned(user_id, memory_id)
        self._get_client().delete(str(memory_id))

    def delete_all(self, *, user_id: int) -> None:
        self._get_client().delete_all(user_id=str(user_id))

    def close(self) -> None:
        client = self._client
        if client is None:
            return
        direct_close = getattr(client, "close", None)
        if callable(direct_close):
            direct_close()
            return
        vector_store = getattr(client, "vector_store", None)
        qdrant_client = getattr(vector_store, "client", None)
        close = getattr(qdrant_client, "close", None)
        if callable(close):
            close()


class MemoryManager:
    def __init__(
        self,
        *,
        provider: MemoryProvider,
        backend_enabled: bool,
        default_enabled: bool,
        get_user_enabled,
        set_user_enabled,
        executor=None,
        search_limit: int = 5,
        list_limit: int = 100,
    ):
        self.provider = provider
        self.backend_enabled = bool(backend_enabled)
        self.default_enabled = bool(default_enabled)
        self.get_user_enabled = get_user_enabled
        self.set_user_enabled_value = set_user_enabled
        self.executor = executor or ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="knowflow-memory",
        )
        self.search_limit = max(1, min(20, int(search_limit)))
        self.list_limit = max(1, min(500, int(list_limit)))

    def _configured(self) -> bool:
        return bool(
            self.backend_enabled
            and getattr(self.provider, "configured", True)
        )

    def _enabled(self, user_id: int) -> bool:
        stored = self.get_user_enabled(int(user_id))
        return self.default_enabled if stored is None else bool(stored)

    def settings(self, user_id: int) -> dict[str, Any]:
        configured = self._configured()
        enabled = self._enabled(user_id)
        version = str(getattr(self.provider, "version", "unknown"))
        return {
            "provider": "mem0",
            "version": version,
            "configured": configured,
            "enabled": enabled,
            "available": configured,
        }

    def set_enabled(self, user_id: int, enabled: bool) -> dict[str, Any]:
        if enabled and not self._configured():
            raise MemoryUnavailableError(
                "Mem0尚未配置，管理员需要先设置记忆模型Key。"
            )
        self.set_user_enabled_value(int(user_id), bool(enabled))
        return self.settings(user_id)

    def recall(
        self,
        user_id: int,
        query: str,
    ) -> list[dict[str, Any]]:
        if not self._configured() or not self._enabled(user_id):
            return []
        try:
            return self.provider.search(
                user_id=int(user_id),
                query=query,
                limit=self.search_limit,
            )
        except Exception as exc:
            logger.warning(
                "Memory recall failed for user %s: %s",
                user_id,
                type(exc).__name__,
            )
            return []

    def _remember(
        self,
        *,
        user_id: int,
        session_id: str,
        message_id: int,
        question: str,
        answer: str,
    ) -> None:
        try:
            self.remember_now(
                user_id=user_id,
                session_id=session_id,
                message_id=message_id,
                question=question,
                answer=answer,
            )
        except Exception as exc:
            logger.warning(
                "Memory write failed for user %s: %s",
                user_id,
                type(exc).__name__,
            )

    def remember_now(
        self,
        *,
        user_id: int,
        session_id: str,
        message_id: int,
        question: str,
        answer: str,
        operation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self._configured() or not self._enabled(user_id):
            return []
        return self.provider.remember(
            user_id=int(user_id),
            messages=[
                {"role": "user", "content": str(question)},
                {"role": "assistant", "content": str(answer)},
            ],
            metadata={
                "session_id": str(session_id),
                "message_id": int(message_id),
                "operation_id": (
                    str(operation_id)
                    if operation_id is not None
                    else None
                ),
            },
        )

    def remember_async(
        self,
        *,
        user_id: int,
        session_id: str,
        message_id: int,
        question: str,
        answer: str,
    ):
        if not self._configured() or not self._enabled(user_id):
            return None
        return self.executor.submit(
            self._remember,
            user_id=int(user_id),
            session_id=str(session_id),
            message_id=int(message_id),
            question=str(question),
            answer=str(answer),
        )

    def _require_configured(self) -> None:
        if not self._configured():
            raise MemoryUnavailableError(
                "Mem0尚未配置，管理员需要先设置记忆模型Key。"
            )

    def list(
        self,
        user_id: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        self._require_configured()
        return self.provider.list(
            user_id=int(user_id),
            limit=min(self.list_limit, int(limit or self.list_limit)),
        )

    def update(
        self,
        user_id: int,
        memory_id: str,
        content: str,
    ) -> dict[str, Any]:
        self._require_configured()
        return self.provider.update(
            user_id=int(user_id),
            memory_id=str(memory_id),
            content=content,
        )

    def delete(self, user_id: int, memory_id: str) -> None:
        self._require_configured()
        self.provider.delete(
            user_id=int(user_id),
            memory_id=str(memory_id),
        )

    def delete_all(self, user_id: int) -> None:
        self._require_configured()
        self.provider.delete_all(user_id=int(user_id))

    def close(self) -> None:
        shutdown = getattr(self.executor, "shutdown", None)
        if callable(shutdown):
            shutdown(wait=True, cancel_futures=False)
        close = getattr(self.provider, "close", None)
        if callable(close):
            close()
