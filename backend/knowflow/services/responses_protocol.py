from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any
import copy, json


MAX_SSE_EVENT_BYTES = 1_048_576

def _normalize_items(items):
    out=copy.deepcopy(items)
    for item in out:
        if not isinstance(item, dict):
            raise ResponsesProtocolError("Invalid Responses structure: output item must be an object.")
        if item.get("type")=="function_call" and isinstance(item.get("arguments"),(dict,list)):
            item["arguments"]=json.dumps(item["arguments"],ensure_ascii=False)
        if item.get("type")=="function_call":
            item["arguments"] = json.dumps(item.get("arguments", "{}"), ensure_ascii=False) if not isinstance(item.get("arguments", "{}"), str) else item.get("arguments", "{}")
    return out


class ResponsesProtocolError(ValueError):
    """Raised when a Responses API payload/response violates the expected shape."""


def iter_sse_json(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    buffer = b""
    for chunk in chunks:
        buffer += bytes(chunk or b"")
        if len(buffer) > MAX_SSE_EVENT_BYTES:
            raise ResponsesProtocolError(
                "Responses SSE event exceeded the size limit."
            )
        buffer = buffer.replace(b"\r\n", b"\n")
        while b"\n\n" in buffer:
            raw, buffer = buffer.split(b"\n\n", 1)
            data_lines = [
                line[5:].lstrip()
                for line in raw.split(b"\n")
                if line.startswith(b"data:")
            ]
            if not data_lines:
                continue
            data = b"\n".join(data_lines)
            if data == b"[DONE]":
                continue
            try:
                value = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ResponsesProtocolError(
                    "Responses SSE contained invalid JSON."
                ) from exc
            if not isinstance(value, dict):
                raise ResponsesProtocolError(
                    "Responses SSE event must be an object."
                )
            yield value
    if buffer.strip():
        raise ResponsesProtocolError(
            "Responses SSE ended with an incomplete event."
        )


class ResponsesStreamAccumulator:
    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._text_by_item: dict[str, str] = {}
        self._tool_args: dict[str, str] = {}
        self._completed = False
        self._message: dict[str, Any] | None = None

    @staticmethod
    def _error_text(code: Any, message: Any) -> str:
        safe_code = str(code or "responses_stream_error")[:100]
        safe_message = " ".join(str(message or "Responses stream failed.").split())
        return f"{safe_code}: {safe_message[:300]}"

    def _store_item(self, item: Any) -> str:
        if not isinstance(item, dict):
            raise ResponsesProtocolError(
                "Responses SSE output item must be an object."
            )
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            raise ResponsesProtocolError(
                "Responses SSE output item missing id."
            )
        if item_id not in self._items:
            self._order.append(item_id)
        self._items[item_id] = copy.deepcopy(item)
        if item.get("type") == "function_call":
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                self._tool_args[item_id] = arguments
        return item_id

    def _final_items(self, response: dict[str, Any]) -> list[dict[str, Any]]:
        output = response.get("output")
        if isinstance(output, list) and output:
            return copy.deepcopy(output)
        items: list[dict[str, Any]] = []
        for item_id in self._order:
            item = copy.deepcopy(self._items[item_id])
            if item.get("type") == "message":
                text = self._text_by_item.get(item_id, "")
                if text and not item.get("content"):
                    item["content"] = [
                        {"type": "output_text", "text": text}
                    ]
            if item.get("type") == "function_call":
                item["arguments"] = self._tool_args.get(
                    item_id,
                    str(item.get("arguments") or "{}"),
                )
            items.append(item)
        return items

    def feed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        event_type = event.get("type")
        if event_type in {
            "response.output_item.added",
            "response.output_item.done",
        }:
            self._store_item(event.get("item"))
            return []
        if event_type == "response.output_text.delta":
            item_id = event.get("item_id")
            delta = event.get("delta")
            if not isinstance(item_id, str) or item_id not in self._items:
                raise ResponsesProtocolError(
                    "Responses text delta referenced an unknown item."
                )
            if not isinstance(delta, str):
                raise ResponsesProtocolError(
                    "Responses text delta must be a string."
                )
            self._text_by_item[item_id] = (
                self._text_by_item.get(item_id, "") + delta
            )
            if self._items[item_id].get("type") == "message":
                return [{"type": "text_delta", "text": delta}]
            return []
        if event_type == "response.function_call_arguments.delta":
            item_id = event.get("item_id")
            delta = event.get("delta")
            if not isinstance(item_id, str) or item_id not in self._items:
                raise ResponsesProtocolError(
                    "Responses tool delta referenced an unknown item."
                )
            if not isinstance(delta, str):
                raise ResponsesProtocolError(
                    "Responses tool argument delta must be a string."
                )
            self._tool_args[item_id] = (
                self._tool_args.get(item_id, "") + delta
            )
            return []
        if event_type == "response.function_call_arguments.done":
            item_id = event.get("item_id")
            arguments = event.get("arguments")
            if not isinstance(item_id, str) or item_id not in self._items:
                raise ResponsesProtocolError(
                    "Responses tool arguments referenced an unknown item."
                )
            if not isinstance(arguments, str):
                raise ResponsesProtocolError(
                    "Responses tool arguments must be a string."
                )
            self._tool_args[item_id] = arguments
            return []
        if event_type == "response.completed":
            response = event.get("response")
            if not isinstance(response, dict):
                raise ResponsesProtocolError(
                    "Responses completed event missing response."
                )
            if response.get("status") not in {None, "completed"}:
                raise ResponsesProtocolError(
                    self._error_text(
                        response.get("status"),
                        "Responses stream did not complete successfully.",
                    )
                )
            payload = {
                **response,
                "output": self._final_items(response),
            }
            self._message = parse_responses_message(payload)
            self._completed = True
            return [{"type": "completed", "message": self._message}]
        if event_type == "response.failed":
            response = event.get("response")
            error = response.get("error") if isinstance(response, dict) else {}
            error = error if isinstance(error, dict) else {}
            raise ResponsesProtocolError(
                self._error_text(error.get("code"), error.get("message"))
            )
        if event_type == "response.incomplete":
            response = event.get("response")
            details = (
                response.get("incomplete_details")
                if isinstance(response, dict)
                else {}
            )
            details = details if isinstance(details, dict) else {}
            raise ResponsesProtocolError(
                self._error_text(
                    "response_incomplete",
                    details.get("reason"),
                )
            )
        if event_type == "error":
            raise ResponsesProtocolError(
                self._error_text(event.get("code"), event.get("message"))
            )
        return []

    def finish(self) -> dict[str, Any]:
        if not self._completed or self._message is None:
            raise ResponsesProtocolError(
                "Responses SSE ended before response.completed."
            )
        return self._message


def to_responses_tool(tool: dict[str, Any]) -> dict[str, Any]:
    fn = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(fn, dict) or not isinstance(fn.get("name"), str) or not isinstance(fn.get("parameters"), dict):
        raise ResponsesProtocolError("Invalid tool definition.")
    return {"type": "function", "name": fn["name"], "description": fn.get("description", ""), "parameters": fn["parameters"], "strict": False}

def messages_to_response_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]
    for item in messages:
        role=item.get("role")
        if role=="system": continue
        if role=="assistant":
            if item.get("_response_items"):
                out.extend(_normalize_items(item["_response_items"])); continue
            if item.get("tool_calls"):
                if item.get("content"): out.append({"role":"assistant","content":item.get("content")})
                for c in item["tool_calls"]:
                    fn=c.get("function",{})
                    out.append({"type":"function_call","call_id":c.get("id",""),"name":fn.get("name",""),"arguments":fn.get("arguments","{}")})
                continue
        if role=="tool":
            out.append({"type":"function_call_output","call_id":item.get("tool_call_id", ""),"output":item.get("content", "")}); continue
        if role in {"user","assistant"}: out.append({"role":role,"content":item.get("content","")})
    return out


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
        "stream": True,
        "input": messages_to_response_input(messages),
    }
    if tools:
        payload["tools"] = [to_responses_tool(t) for t in tools]
        payload["tool_choice"] = tool_choice or "auto"
    if system:
        payload["instructions"] = "\n\n".join(system)
    payload["temperature"] = float(config.get("temperature", 0.3) if config.get("temperature") is not None else 0.3)
    if config.get("top_p") is not None:
        payload["top_p"] = float(config["top_p"])
    if config.get("max_tokens") is not None:
        payload["max_output_tokens"] = int(config["max_tokens"])
    return payload


def parse_responses_message(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ResponsesProtocolError("Invalid Responses structure: response data must be an object.")
    if "choices" in data and "output" not in data:
        raise ResponsesProtocolError("Responses API upstream returned Chat Completions shape (choices); expected output.")
    output = data.get("output")
    if not isinstance(output, list):
        raise ResponsesProtocolError("Invalid Responses structure: output must be a list.")
    texts: list[str] = []
    calls=[]
    for item in output:
        if not isinstance(item, dict):
            raise ResponsesProtocolError("Invalid Responses structure: output item must be an object.")
        if item.get("type") == "function_call":
            if not isinstance(item.get("call_id"), str) or not item.get("call_id"):
                raise ResponsesProtocolError("Responses API function call missing call_id.")
            if not isinstance(item.get("name"), str) or not item.get("name"):
                raise ResponsesProtocolError("Responses API function call missing name.")
            args=item.get("arguments", "{}")
            if not isinstance(args, str): args=json.dumps(args,ensure_ascii=False)
            calls.append({"id":item.get("call_id", ""),"type":"function","function":{"name":item.get("name", ""),"arguments":args}})
        if item.get("type") != "message": continue
        content_items = item.get("content", [])
        if not isinstance(content_items, list):
            raise ResponsesProtocolError("Invalid Responses structure: message content must be a list.")
        for content in content_items:
            if not isinstance(content, dict):
                raise ResponsesProtocolError("Invalid Responses structure: content item must be an object.")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                texts.append(content["text"])
    if not texts and not calls:
        raise ResponsesProtocolError("Responses API returned no text or tool calls.")
    result={"role":"assistant","content":"".join(texts),"tool_calls":calls}
    if calls or any(i.get("type")!="message" for i in output): result["_response_items"]=_normalize_items(output)
    return result
