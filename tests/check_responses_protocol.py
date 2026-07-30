from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_gateway import ModelGateway
from knowflow.services.responses_protocol import ResponsesProtocolError


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
    calls = []

    def post_model_json(url, headers, payload):
        calls.append((url, payload))
        return FakeResponse({"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Current answer."}]}]})

    gateway = ModelGateway(fetch_one=lambda *_a, **_k: None, cipher=FakeCipher(), post_model_json=post_model_json, local_embedding=lambda _: [0.0])
    config = {"api_mode": "responses", "model_name": "gpt-test", "base_url": "https://example.com/v1", "api_key_cipher": "key", "temperature": "0.2", "top_p": "0.8", "max_tokens": 123}
    message = gateway.complete([{ "role": "system", "content": "Be concise."}, {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}], config)
    assert calls[0][0] == "https://example.com/v1/responses"
    payload = calls[0][1]
    assert payload["instructions"] == "Be concise."
    assert payload["input"] == [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
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
    print("responses protocol adapts payload and parses text")


if __name__ == "__main__":
    main()
