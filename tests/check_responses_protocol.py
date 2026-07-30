from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_gateway import ModelGateway
from knowflow.services.responses_protocol import ResponsesProtocolError, to_responses_tool, messages_to_response_input, parse_responses_message


class FakeCipher:
    def decrypt(self, value):
        return value or ""


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


def main():
    flat = to_responses_tool({"type":"function","function":{"name":"web_search","description":"Search","parameters":{"type":"object"}}})
    assert flat == {"type":"function","name":"web_search","description":"Search","parameters":{"type":"object"},"strict":False}
    parsed = parse_responses_message({"output":[{"type":"reasoning","id":"r1"},{"type":"function_call","call_id":"c1","name":"web_search","arguments":{"query":"中文"}}]})
    assert parsed["tool_calls"][0]["function"]["arguments"] == '{"query": "中文"}'
    assert parsed["_response_items"][0]["type"] == "reasoning"
    inp = messages_to_response_input([parsed, {"role":"tool","tool_call_id":"c1","content":"ok"}])
    assert inp[0]["type"] == "reasoning" and inp[1]["type"] == "function_call" and inp[2] == {"type":"function_call_output","call_id":"c1","output":"ok"}
    legacy = messages_to_response_input([{"role":"assistant","content":"","tool_calls":[{"id":"c2","function":{"name":"x","arguments":"{}"}}]}])
    assert legacy[-1]["type"] == "function_call" and legacy[-1]["call_id"] == "c2"
    calls = []

    def post_model_json(url, headers, payload):
        calls.append((url, payload))
        return FakeResponse({"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Current answer."}]}]})

    gateway = ModelGateway(fetch_one=lambda *_a, **_k: None, cipher=FakeCipher(), post_model_json=post_model_json, local_embedding=lambda _: [0.0])
    config = {"api_mode": "responses", "model_name": "gpt-test", "base_url": "https://example.com/v1", "api_key_cipher": "key", "temperature": "0.2", "top_p": "0.8", "max_tokens": 123}
    message = gateway.complete([{ "role": "system", "content": "Be concise."}, {"role": "system", "content": "Use plain text."}, {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Again"}], config)
    assert calls[0][0] == "https://example.com/v1/responses"
    payload = calls[0][1]
    assert payload["instructions"] == "Be concise.\n\nUse plain text."
    assert payload["input"] == [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Again"}]
    assert payload["model"] == "gpt-test" and payload["store"] is False
    assert payload["max_output_tokens"] == 123 and payload["temperature"] == 0.2 and payload["top_p"] == 0.8
    assert "previous_response_id" not in payload and "conversation" not in payload
    assert message == {"role": "assistant", "content": "Current answer.", "tool_calls": []}

    def no_text(*_args):
        return FakeResponse({"output": [{"type": "message", "content": []}]})
    gateway.post_model_json = no_text
    try:
        gateway.complete([{ "role": "user", "content": "Hi"}], config)
    except ResponsesProtocolError:
        pass
    else:
        raise AssertionError("expected ResponsesProtocolError")
    invalid = dict(config, api_mode="invalid", api_key_cipher=None)
    try:
        gateway.complete([{ "role": "user", "content": "Hi"}], invalid)
    except ValueError as exc:
        assert "Unsupported api_mode" in str(exc)
    else:
        raise AssertionError("expected invalid api_mode ValueError")
    print("responses protocol adapts payload and parses text")


if __name__ == "__main__":
    main()
