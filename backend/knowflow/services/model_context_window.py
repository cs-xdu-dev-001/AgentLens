from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.messages.utils import (
    convert_to_openai_messages,
    count_tokens_approximately,
    trim_messages,
)


@dataclass(frozen=True)
class ModelContextWindow:
    messages: list[dict[str, Any]]
    original_tokens: int
    sent_tokens: int
    trimmed: bool


def _tool_sequence_is_complete(messages: list[dict[str, Any]]) -> bool:
    pending: set[str] = set()
    for message in messages:
        role = str(message.get("role") or "")
        if role == "assistant":
            if pending:
                return False
            pending = {
                str(call.get("id") or "")
                for call in (message.get("tool_calls") or [])
                if isinstance(call, dict) and str(call.get("id") or "")
            }
            continue
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            if not call_id or call_id not in pending:
                return False
            pending.remove(call_id)
            continue
        if pending:
            return False
    return not pending


def _latest_valid_turn(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    system = [
        dict(message)
        for message in messages
        if str(message.get("role") or "") == "system"
    ]
    latest_user = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if str(messages[index].get("role") or "") == "user"
        ),
        max(0, len(messages) - 1),
    )
    recent = [
        dict(message)
        for message in messages[latest_user:]
        if str(message.get("role") or "") != "system"
    ]
    return [*system, *recent]


def prepare_model_context(
    messages: list[dict[str, Any]],
    *,
    max_tokens: int,
) -> ModelContextWindow:
    copied = [dict(message) for message in messages]
    original_tokens = count_tokens_approximately(copied)
    limit = max(1_000, int(max_tokens))
    if original_tokens <= limit:
        return ModelContextWindow(
            messages=copied,
            original_tokens=original_tokens,
            sent_tokens=original_tokens,
            trimmed=False,
        )

    trimmed_messages = trim_messages(
        copied,
        max_tokens=limit,
        token_counter=count_tokens_approximately,
        strategy="last",
        allow_partial=False,
        include_system=True,
        start_on="human",
    )
    converted = convert_to_openai_messages(trimmed_messages)
    if isinstance(converted, dict):
        converted = [converted]
    normalized = [dict(message) for message in converted]
    if not normalized or not _tool_sequence_is_complete(normalized):
        normalized = _latest_valid_turn(copied)
    sent_tokens = count_tokens_approximately(normalized)
    return ModelContextWindow(
        messages=normalized,
        original_tokens=original_tokens,
        sent_tokens=sent_tokens,
        trimmed=normalized != copied,
    )
