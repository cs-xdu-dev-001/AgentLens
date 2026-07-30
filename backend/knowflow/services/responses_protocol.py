from __future__ import annotations

from typing import Any


class ResponsesProtocolError(ValueError):
    """Raised when a Responses API payload/response violates the expected shape."""


def messages_to_response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"role": item["role"], "content": item.get("content", "")}
        for item in messages
        if item.get("role") in {"user", "assistant"}
    ]


def build_responses_payload(
    messages: list[dict[str, Any]],
    config: dict[str, Any],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    system = [str(item.get("content", "")) for item in messages if item.get("role") == "system"]
    payload: dict[str, Any] = {
        "model": config["model_name"],
        "store": False,
        "input": messages_to_response_input(messages),
    }
    if system:
        payload["instructions"] = "\n\n".join(system)
    payload["temperature"] = float(config.get("temperature", 0.3) if config.get("temperature") is not None else 0.3)
    if config.get("top_p") is not None:
        payload["top_p"] = float(config["top_p"])
    if config.get("max_tokens") is not None:
        payload["max_output_tokens"] = int(config["max_tokens"])
    return payload


def parse_responses_message(data: dict[str, Any]) -> dict[str, Any]:
    texts: list[str] = []
    for item in data.get("output", []) or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if not texts:
        raise ResponsesProtocolError("Responses API returned no output text.")
    return {"role": "assistant", "content": "".join(texts), "tool_calls": []}
