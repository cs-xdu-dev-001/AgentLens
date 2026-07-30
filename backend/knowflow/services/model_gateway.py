from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from .responses_protocol import build_responses_payload, parse_responses_message


class ModelGateway:
    def __init__(self, *, fetch_one, cipher, post_model_json, local_embedding):
        self.fetch_one = fetch_one
        self.cipher = cipher
        self.post_model_json = post_model_json
        self.local_embedding = local_embedding

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
                return "unavailable", self._safe_error(exc)
            protocol = "Responses API" if (config.get("api_mode") or "chat_completions") == "responses" else "Chat Completions"
            return "unavailable", f"{protocol} connection failed: {self._safe_error(exc)}"
        return "unavailable", "The model did not return a valid result."

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        text = f"{type(exc).__name__}: " + " ".join(str(exc).split())
        text = re.sub(r"\{[^{}]*\}|\[[^\[\]]*\]", "[response omitted]", text)
        text = re.sub(r"Bearer\s+[^\s,;]+", "Bearer [redacted]", text, flags=re.I)
        text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-[redacted]", text)
        text = re.sub(r"Authorization\s*[:=]\s*[^\s,;]+", "Authorization: [redacted]", text, flags=re.I)
        text = re.sub(r"(?:api[_-]?key|token)=[^\s&]+", "[redacted]", text, flags=re.I)
        return text[:500]

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
        response = self.post_model_json(url, self.headers(config), payload)
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
    ) -> dict[str, Any]:
        if config is None:
            return {"role": "assistant", "content": self.local_answer(messages)}
        api_mode = config.get("api_mode") or "chat_completions"
        if api_mode not in {"chat_completions", "responses"}:
            raise ValueError(f"Unsupported api_mode: {api_mode}")
        if not self.cipher.decrypt(config.get("api_key_cipher")):
            return {"role": "assistant", "content": self.local_answer(messages)}
        if api_mode == "responses":
            url = self.endpoint(config["base_url"], "/responses")
            payload = build_responses_payload(messages, config, tools=tools, tool_choice=tool_choice)
            response = self.post_model_json(url, self.headers(config), payload)
            response.raise_for_status()
            return parse_responses_message(response.json())
        url = self.endpoint(config["base_url"], "/chat/completions")
        payload: dict[str, Any] = {
            "model": config["model_name"],
            "messages": messages,
            "temperature": config.get("temperature") if config.get("temperature") is not None else 0.3,
        }
        if config.get("top_p") is not None:
            payload["top_p"] = float(config["top_p"])
        if config.get("max_tokens") is not None:
            if config.get("provider") in {"mimo", "openai"}:
                payload["max_completion_tokens"] = int(config["max_tokens"])
            else:
                payload["max_tokens"] = int(config["max_tokens"])
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        response = self.post_model_json(url, self.headers(config), payload)
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
    ) -> str:
        message = self.complete(messages, config)
        return str(message.get("content") or "")

    def local_answer(self, messages: list[dict[str, Any]]) -> str:
        system_content = next((item["content"] for item in messages if item["role"] == "system"), "")
        user_content = next((item["content"] for item in reversed(messages) if item["role"] == "user"), "")
        identity_keywords = ["model", "provider", "identity", "who are you", "\u4ec0\u4e48\u6a21\u578b", "\u4f9b\u5e94\u5546", "\u4f60\u662f\u8c01", "\u8eab\u4efd"]
        if any(keyword in user_content.lower() for keyword in identity_keywords):
            match = re.search(r"Current model configuration: ([^.]+)", system_content)
            identity = match.group(1) if match else "local fallback / no remote provider configured"
            return f"The current model configuration is {identity}. KnowFlow AI is only the application wrapper and entry point."
        return "Local fallback model received the question: " + user_content
