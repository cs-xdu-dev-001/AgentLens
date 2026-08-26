from __future__ import annotations

from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import re
import requests
from time import sleep
from typing import Any, Callable

from .responses_protocol import (
    ResponsesProtocolError,
    ResponsesStreamAccumulator,
    build_responses_payload,
    iter_sse_json,
    sanitize_upstream_error,
)

MAX_UPSTREAM_ERROR_BYTES = 65_536
RETRYABLE_MODEL_STATUSES = {408, 409, 429, 500, 502, 503, 504}
MAX_MODEL_RETRIES = 3
MAX_RATE_LIMIT_RETRIES = 5
MAX_MODEL_RETRY_DELAY_SECONDS = 60.0
RATE_LIMIT_RETRY_BASE_SECONDS = 5.0
TRANSIENT_RETRY_BASE_SECONDS = 1.0


def model_connection_diagnostic(status: Any, detail: Any) -> dict[str, Any]:
    """Classify model connection results without exposing provider-specific secrets."""

    normalized_status = str(status or "").strip().lower()
    text = " ".join(str(detail or "").split())[:800]
    lowered = text.lower()
    if normalized_status in {"available", "success"}:
        return {"code": "available", "retryable": False}
    if "invalid temperature" in lowered or "unsupported parameter" in lowered:
        code = "incompatible_parameters"
    elif "http 401" in lowered or "authentication" in lowered or "unauthorized" in lowered:
        code = "authentication_failed"
    elif "http 403" in lowered or "forbidden" in lowered:
        code = "access_denied"
    elif "http 404" in lowered or "model_not_found" in lowered or "not found" in lowered:
        code = "not_found"
    elif "http 429" in lowered or "rate_limit" in lowered:
        code = "rate_limited"
    elif (
        ("not support" in lowered or "unsupported" in lowered)
        and ("chat completion" in lowered or "responses" in lowered or "protocol" in lowered)
    ):
        code = "protocol_unsupported"
    elif (
        "http 503" in lowered
        or "no available channel" in lowered
        or "unavailable channel" in lowered
    ):
        code = "upstream_unavailable"
    elif "timeout" in lowered or "timed out" in lowered or "connection error" in lowered:
        code = "network_error"
    elif "http 400" in lowered or "invalid_request" in lowered:
        code = "invalid_request"
    else:
        code = "connection_failed"
    return {
        "code": code,
        "retryable": code in {"rate_limited", "upstream_unavailable", "network_error"},
    }


PROTOCOL_FALLBACK_CODES = {
    "access_denied",
    "not_found",
    "protocol_unsupported",
    "upstream_unavailable",
    "invalid_request",
    "incompatible_parameters",
    "connection_failed",
}


def test_model_protocols(gateway: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Test the selected chat protocol and probe the alternative when useful.

    The selected protocol remains authoritative. A successful alternative is
    returned as an explicit recommendation and is never persisted silently.
    """

    selected_mode = str(config.get("api_mode") or "chat_completions")
    status, message = gateway.test(config)
    diagnostic = model_connection_diagnostic(status, message)
    selected = {
        "apiMode": selected_mode,
        "status": status,
        "message": message,
        **diagnostic,
    }
    result: dict[str, Any] = {
        **selected,
        "checkedProtocols": [selected],
    }
    if (
        str(config.get("model_type") or "chat") != "chat"
        or status == "available"
        or diagnostic["code"] not in PROTOCOL_FALLBACK_CODES
    ):
        return result

    alternate_mode = (
        "chat_completions" if selected_mode == "responses" else "responses"
    )
    alternate_config = {**config, "api_mode": alternate_mode}
    alternate_status, alternate_message = gateway.test(alternate_config)
    alternate_diagnostic = model_connection_diagnostic(
        alternate_status,
        alternate_message,
    )
    alternate = {
        "apiMode": alternate_mode,
        "status": alternate_status,
        "message": alternate_message,
        **alternate_diagnostic,
    }
    result["checkedProtocols"].append(alternate)
    if alternate_status == "available":
        result["recommendedApiMode"] = alternate_mode
    return result


class ChatCompletionsStreamAccumulator:
    """Build one assistant message from OpenAI-compatible chat SSE chunks."""

    def __init__(self) -> None:
        self.role = "assistant"
        self.content: list[str] = []
        self.tool_calls: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] = {}

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        usage = event.get("usage")
        if isinstance(usage, dict):
            self.usage = dict(usage)
            usage_event = {"type": "usage_updated", "usage": self.usage}
        else:
            usage_event = None
        choices = event.get("choices")
        if not isinstance(choices, list) or not choices:
            return [usage_event] if usage_event else []
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ResponsesProtocolError(
                "Chat Completions SSE choice must be an object."
            )
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return []
        if delta.get("role"):
            self.role = str(delta["role"])
        public_events: list[dict[str, Any]] = []
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.content.append(content)
            public_events.append({"type": "text_delta", "text": content})
        calls = delta.get("tool_calls")
        if isinstance(calls, list):
            for fallback_index, value in enumerate(calls):
                if not isinstance(value, dict):
                    continue
                raw_index = value.get("index", fallback_index)
                try:
                    index = int(raw_index)
                except (TypeError, ValueError):
                    index = fallback_index
                call = self.tool_calls.setdefault(
                    index,
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if value.get("id"):
                    call["id"] = str(value["id"])
                if value.get("type"):
                    call["type"] = str(value["type"])
                function = value.get("function")
                if isinstance(function, dict):
                    if function.get("name"):
                        call["function"]["name"] += str(function["name"])
                    if function.get("arguments"):
                        call["function"]["arguments"] += str(
                            function["arguments"]
                        )
        if usage_event:
            public_events.append(usage_event)
        return public_events

    def finish(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": self.role,
            "content": "".join(self.content) or None,
        }
        if self.tool_calls:
            message["tool_calls"] = [
                self.tool_calls[index] for index in sorted(self.tool_calls)
            ]
        return message


class ModelGateway:
    def __init__(
        self,
        *,
        fetch_one,
        cipher,
        post_model_json,
        local_embedding,
        stream_model_json=None,
        sleep_fn=sleep,
    ):
        self.fetch_one = fetch_one
        self.cipher = cipher
        self.post_model_json = post_model_json
        self.local_embedding = local_embedding
        self.stream_model_json = stream_model_json
        self.sleep_fn = sleep_fn

    @staticmethod
    def _retry_delay(
        response: Any,
        attempt: int,
        *,
        status: int = 0,
    ) -> float:
        headers = getattr(response, "headers", None)
        retry_after = None
        if hasattr(headers, "get"):
            retry_after_ms = headers.get("Retry-After-Ms")
            retry_after = headers.get("Retry-After")
            if retry_after_ms is not None:
                try:
                    retry_after = float(retry_after_ms) / 1000.0
                except (TypeError, ValueError):
                    pass
        base = (
            RATE_LIMIT_RETRY_BASE_SECONDS
            if status == 429
            else TRANSIENT_RETRY_BASE_SECONDS
        )
        backoff = min(
            MAX_MODEL_RETRY_DELAY_SECONDS,
            base * float(2 ** max(0, attempt - 1)),
        )
        try:
            upstream_delay = max(0.0, float(retry_after))
        except (TypeError, ValueError):
            upstream_delay = 0.0
            if isinstance(retry_after, str):
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    upstream_delay = max(
                        0.0,
                        (retry_at - datetime.now(timezone.utc)).total_seconds(),
                    )
                except (TypeError, ValueError, OverflowError):
                    pass
        return min(
            MAX_MODEL_RETRY_DELAY_SECONDS,
            max(backoff, upstream_delay),
        )

    @staticmethod
    def _emit_retry(
        event_callback: Callable[[dict[str, Any]], None] | None,
        *,
        status: int,
        attempt: int,
        delay: float,
        error_type: str = "",
    ) -> None:
        if event_callback is None:
            return
        event: dict[str, Any] = {
            "type": "model_retry",
            "retryAttempt": attempt,
            "maxRetries": (
                MAX_RATE_LIMIT_RETRIES
                if status == 429
                else MAX_MODEL_RETRIES
            ),
            "retryInMs": int(delay * 1000),
        }
        if status:
            event["statusCode"] = status
        if error_type:
            event["errorType"] = error_type
        event_callback(event)

    def _model_request(
        self,
        transport: Callable[[], Any],
        event_callback: Callable[[dict[str, Any]], None] | None,
    ) -> Any:
        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
            try:
                response = transport()
            except requests.RequestException as exc:
                if attempt > MAX_MODEL_RETRIES:
                    raise
                delay = self._retry_delay(None, attempt)
                self._emit_retry(
                    event_callback,
                    status=0,
                    attempt=attempt,
                    delay=delay,
                    error_type=type(exc).__name__,
                )
                self.sleep_fn(delay)
                continue
            try:
                status = int(getattr(response, "status_code", 200))
            except (TypeError, ValueError):
                status = 200
            max_retries = (
                MAX_RATE_LIMIT_RETRIES
                if status == 429
                else MAX_MODEL_RETRIES
            )
            if status not in RETRYABLE_MODEL_STATUSES or attempt > max_retries:
                return response
            delay = self._retry_delay(response, attempt, status=status)
            self._emit_retry(
                event_callback,
                status=status,
                attempt=attempt,
                delay=delay,
                error_type=(
                    "rate_limit"
                    if status == 429
                    else "upstream_unavailable"
                ),
            )
            close = getattr(response, "close", None)
            if callable(close):
                close()
            self.sleep_fn(delay)
        raise RuntimeError("Model retry loop ended unexpectedly.")

    @contextmanager
    def _model_stream_request(
        self,
        transport: Callable[[], Any],
        event_callback: Callable[[dict[str, Any]], None] | None,
    ):
        for attempt in range(1, MAX_RATE_LIMIT_RETRIES + 2):
            stack = ExitStack()
            try:
                response = stack.enter_context(transport())
            except requests.RequestException as exc:
                stack.close()
                if attempt > MAX_MODEL_RETRIES:
                    raise
                delay = self._retry_delay(None, attempt)
                self._emit_retry(
                    event_callback,
                    status=0,
                    attempt=attempt,
                    delay=delay,
                    error_type=type(exc).__name__,
                )
                self.sleep_fn(delay)
                continue
            try:
                status = int(getattr(response, "status_code", 200))
            except (TypeError, ValueError):
                status = 200
            max_retries = (
                MAX_RATE_LIMIT_RETRIES
                if status == 429
                else MAX_MODEL_RETRIES
            )
            if status not in RETRYABLE_MODEL_STATUSES or attempt > max_retries:
                with stack:
                    yield response
                return
            delay = self._retry_delay(response, attempt, status=status)
            self._emit_retry(
                event_callback,
                status=status,
                attempt=attempt,
                delay=delay,
                error_type=(
                    "rate_limit"
                    if status == 429
                    else "upstream_unavailable"
                ),
            )
            stack.close()
            self.sleep_fn(delay)
        raise RuntimeError("Model retry loop ended unexpectedly.")

    def get_config(self, config_id: int | None, model_type: str, user_id: int | None = None) -> dict[str, Any] | None:
        if config_id:
            if user_id is None:
                row = self.fetch_one("SELECT * FROM model_config WHERE id=:id AND model_type=:model_type", {"id": config_id, "model_type": model_type})
            else:
                row = self.fetch_one(
                    "SELECT * FROM model_config WHERE id=:id AND model_type=:model_type AND user_id=:user_id",
                    {"id": config_id, "model_type": model_type, "user_id": user_id},
                )
            if row:
                return row
            if user_id is not None:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail="Model configuration not found.")
        if user_id is not None:
            return self.fetch_one(
                "SELECT * FROM model_config WHERE model_type=:model_type AND is_default=1 AND user_id=:user_id ORDER BY id DESC LIMIT 1",
                {"model_type": model_type, "user_id": user_id},
            )
        return self.fetch_one(
            "SELECT * FROM model_config WHERE model_type=:model_type AND is_default=1 ORDER BY id DESC LIMIT 1",
            {"model_type": model_type},
        )

    def test(self, config: dict[str, Any]) -> tuple[str, str]:
        model_type = config["model_type"]
        try:
            if model_type == "embedding":
                vector = self.embed("ping", config)
                if vector:
                    return "available", f"Connection succeeded. The model returned a {len(vector)}-dimension vector."
            else:
                answer = self.complete([{"role": "user", "content": "ping"}], config)
                if answer:
                    protocol = "Responses API" if (config.get("api_mode") or "chat_completions") == "responses" else "Chat Completions"
                    return "available", f"{protocol} connection succeeded. The model returned a normal response."
        except Exception as exc:
            if model_type == "embedding":
                return "unavailable", f"Embedding connection failed: {self._safe_error(exc)}"
            protocol = "Responses API" if (config.get("api_mode") or "chat_completions") == "responses" else "Chat Completions"
            return "unavailable", f"{protocol} connection failed: {self._safe_error(exc)}"
        return "unavailable", "The model did not return a valid result."

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        try: raw = str(exc)
        except Exception: raw = ""
        try: response = getattr(exc, "response", None)
        except Exception: response = None
        try: status = getattr(response, "status_code", None)
        except Exception: status = None
        if not isinstance(status, int) and not (isinstance(status, str) and status.isdigit() and len(status) < 5): status = None
        upstream_code = ""
        upstream_message = ""
        if response is not None:
            try:
                payload = response.json()
                error = (
                    payload.get("error")
                    if isinstance(payload, dict)
                    else None
                )
                if isinstance(error, dict):
                    upstream_code = str(
                        error.get("code")
                        or error.get("type")
                        or ""
                    )
                    upstream_message = str(error.get("message") or "")
            except Exception:
                pass
        text = " ".join(raw.split())
        if upstream_code or upstream_message:
            text = " ".join(
                value
                for value in (upstream_code, upstream_message)
                if value
            )
        if not isinstance(exc, ResponsesProtocolError) and (
            "{" in text or "[" in text
        ):
            text = "Upstream request failed."
        text = sanitize_upstream_error(text, limit=450)
        suffix = f" (HTTP {status})" if status is not None else ""
        return f"{type(exc).__name__}{suffix}: {text}"[:500]

    @staticmethod
    def _raise_responses_http_error(response) -> None:
        status = getattr(response, "status_code", None)
        raw = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            raw.extend(chunk or b"")
            if len(raw) >= MAX_UPSTREAM_ERROR_BYTES:
                break
        code = "upstream_error"
        message = "Upstream returned an error response."
        try:
            payload = json.loads(bytes(raw[:MAX_UPSTREAM_ERROR_BYTES]).decode("utf-8"))
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                code = error.get("code") or error.get("type") or code
                message = error.get("message") or message
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        safe_code = sanitize_upstream_error(code, limit=100)
        safe_message = sanitize_upstream_error(message, limit=300)
        raise ResponsesProtocolError(
            f"HTTP {status}: {safe_code}: {safe_message}"
        )

    def endpoint(self, base_url: str, path: str) -> str:
        base = base_url.rstrip("/")
        if base.endswith(path):
            return base
        return base + path

    def headers(self, config: dict[str, Any]) -> dict[str, str]:
        key = self.cipher.decrypt(config.get("api_key_cipher"))
        headers = {"Content-Type": "application/json"}
        if key:
            if config.get("provider") == "mimo":
                headers["api-key"] = key
            else:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def embed(self, text_value: str, config: dict[str, Any] | None = None) -> list[float]:
        if not config or not self.cipher.decrypt(config.get("api_key_cipher")):
            return self.local_embedding(text_value)
        url = self.endpoint(config["base_url"], "/embeddings")
        payload = {"model": config["model_name"], "input": text_value}
        response = self._model_request(
            lambda: self.post_model_json(
                url,
                self.headers(config),
                payload,
            ),
            None,
        )
        response.raise_for_status()
        data = response.json()
        return list(data["data"][0]["embedding"])

    def complete(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if config is None:
            return {"role": "assistant", "content": self.local_answer(messages)}
        api_mode = config.get("api_mode") or "chat_completions"
        if api_mode not in {"chat_completions", "responses"}:
            raise ValueError(f"Unsupported api_mode: {api_mode}")
        if not self.cipher.decrypt(config.get("api_key_cipher")):
            return {"role": "assistant", "content": self.local_answer(messages)}
        if api_mode == "responses":
            if self.stream_model_json is None:
                raise RuntimeError(
                    "Responses streaming transport is not configured."
                )
            url = self.endpoint(config["base_url"], "/responses")
            payload = build_responses_payload(messages, config, tools=tools, tool_choice=tool_choice)
            accumulator = ResponsesStreamAccumulator()
            response = self._model_stream_request(
                lambda: self.stream_model_json(
                    url,
                    self.headers(config),
                    payload,
                ),
                event_callback,
            )
            with response as response:
                if int(getattr(response, "status_code", 200)) >= 400:
                    self._raise_responses_http_error(response)
                response.raise_for_status()
                for upstream_event in iter_sse_json(
                    response.iter_content(chunk_size=None)
                ):
                    for public_event in accumulator.feed(upstream_event):
                        if event_callback is not None:
                            event_callback(public_event)
            return accumulator.finish()
        url = self.endpoint(config["base_url"], "/chat/completions")
        payload: dict[str, Any] = {
            "model": config["model_name"],
            "messages": messages,
        }
        if config.get("max_tokens") is not None:
            if config.get("provider") in {"mimo", "openai"}:
                payload["max_completion_tokens"] = int(config["max_tokens"])
            else:
                payload["max_tokens"] = int(config["max_tokens"])
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        if event_callback is not None and self.stream_model_json is not None:
            payload["stream"] = True
            accumulator = ChatCompletionsStreamAccumulator()
            response = self._model_stream_request(
                lambda: self.stream_model_json(
                    url,
                    self.headers(config),
                    payload,
                ),
                event_callback,
            )
            with response as response:
                if int(getattr(response, "status_code", 200)) >= 400:
                    self._raise_responses_http_error(response)
                response.raise_for_status()
                for upstream_event in iter_sse_json(
                    response.iter_content(chunk_size=None)
                ):
                    for public_event in accumulator.feed(upstream_event):
                        event_callback(public_event)
            return accumulator.finish()
        response = self._model_request(
            lambda: self.post_model_json(
                url,
                self.headers(config),
                payload,
            ),
            event_callback,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        if not isinstance(message, dict):
            raise ValueError(
                "Model response did not contain a valid assistant message."
            )
        return message

    def chat(
        self,
        messages: list[dict[str, Any]],
        config: dict[str, Any] | None = None,
        *,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> str:
        message = self.complete(
            messages,
            config,
            event_callback=event_callback,
        )
        return str(message.get("content") or "")

    def local_answer(self, messages: list[dict[str, Any]]) -> str:
        system_content = next((item["content"] for item in messages if item["role"] == "system"), "")
        user_content = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        identity_keywords = ["model", "provider", "identity", "who are you", "\u4ec0\u4e48\u6a21\u578b", "\u4f9b\u5e94\u5546", "\u4f60\u662f\u8c01", "\u8eab\u4efd"]
        if any(keyword in user_content.lower() for keyword in identity_keywords):
            match = re.search(r"Current model configuration: ([^.]+)", system_content)
            identity = match.group(1) if match else "local fallback / no remote provider configured"
            return f"The current model configuration is {identity}. AgentLens is only the application wrapper and entry point."
        return "Local fallback model received the question: " + user_content
