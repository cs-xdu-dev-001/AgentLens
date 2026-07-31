from __future__ import annotations

from typing import Any
import copy, json

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
