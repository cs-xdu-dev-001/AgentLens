from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_gateway import ModelGateway


class FakeCipher:
    def decrypt(self, value):
        return value or ""


class FakeResponse:
    def __init__(self, message):
        self.message = message

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": self.message}]}


def main() -> None:
    calls = []
    tool_message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-search-1",
                "type": "function",
                "function": {
                    "name": "web_search",
                    "arguments": '{"query":"latest release","top_k":3}',
                },
            }
        ],
    }

    def post_model_json(url, headers, payload):
        calls.append((url, headers, payload))
        return FakeResponse(tool_message)

    gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        local_embedding=lambda _text: [0.0],
    )
    config = {
        "provider": "openai",
        "model_name": "gpt-test",
        "base_url": "https://example.com/v1",
        "api_key_cipher": "unit-test-key",
        "temperature": 0.3,
        "top_p": None,
        "max_tokens": 1000,
    }
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the public web.",
                "parameters": {"type": "object"},
            },
        }
    ]
    message = gateway.complete(
        [{"role": "user", "content": "latest release"}],
        config,
        tools=tools,
        tool_choice="auto",
    )
    assert message == tool_message
    url, _headers, payload = calls[0]
    assert url == "https://example.com/v1/chat/completions"
    assert payload["messages"] == [{"role": "user", "content": "latest release"}]
    assert "input" not in payload
    assert payload["tools"] == tools
    assert payload["tool_choice"] == "auto"
    assert payload["max_completion_tokens"] == 1000

    local_message = gateway.complete(
        [{"role": "user", "content": "hello"}],
        None,
        tools=tools,
        tool_choice="auto",
    )
    assert local_message["role"] == "assistant"
    assert "Local fallback model" in local_message["content"]
    print("model gateway preserves native assistant tool calls")


if __name__ == "__main__":
    main()
