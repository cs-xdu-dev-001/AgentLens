from pathlib import Path
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
import requests
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


class FakeStreamResponse:
    def __init__(self, chunks, *, status_code=200, headers=None):
        self.chunks = chunks
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=None):
        yield from self.chunks


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

    default_sampling_config = dict(config)
    default_sampling_config.pop("temperature")
    default_sampling_config["max_tokens"] = None
    gateway.complete(
        [{"role": "user", "content": "ping"}],
        default_sampling_config,
    )
    default_payload = calls[-1][2]
    assert "temperature" not in default_payload
    assert "top_p" not in default_payload

    retry_response = FakeStreamResponse(
        [],
        status_code=429,
        headers={"Retry-After": "0"},
    )
    success_response = FakeStreamResponse(
        [
            (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "delta": {
                                    "role": "assistant",
                                    "content": "正在",
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            ).encode("utf-8"),
            (
                "data: "
                + json.dumps(
                    {"choices": [{"delta": {"content": "处理"}}]},
                    ensure_ascii=False,
                )
                + "\n\n"
            ).encode("utf-8"),
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"id":"call-stream","type":"function","function":'
            b'{"name":"web_search","arguments":"{\\"query\\":\\""}}]}}]}\n\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
            b'"function":{"arguments":"news\\"}"}}]}}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":12,'
            b'"completion_tokens":5,"total_tokens":17}}\n\n',
            b"data: [DONE]\n\n",
        ]
    )
    stream_responses = [retry_response, success_response]
    stream_calls = []
    waits = []
    public_events = []

    def stream_model_json(url, headers, payload):
        stream_calls.append((url, headers, payload))
        return stream_responses.pop(0)

    streaming_gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        stream_model_json=stream_model_json,
        local_embedding=lambda _text: [0.0],
        sleep_fn=waits.append,
    )
    streamed = streaming_gateway.complete(
        [{"role": "user", "content": "latest release"}],
        config,
        tools=tools,
        event_callback=public_events.append,
    )
    assert retry_response.closed
    assert waits == [5.0]
    assert public_events[0] == {
        "type": "model_retry",
        "statusCode": 429,
        "retryAttempt": 1,
        "maxRetries": 5,
        "retryInMs": 5000,
        "errorType": "rate_limit",
    }
    assert [event.get("text") for event in public_events[1:] if event.get("type") == "text_delta"] == [
        "正在",
        "处理",
    ]
    assert public_events[-1] == {
        "type": "usage_updated",
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 5,
            "total_tokens": 17,
        },
    }
    assert streamed["content"] == "正在处理"
    assert streamed["tool_calls"] == [
        {
            "id": "call-stream",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": '{"query":"news"}',
            },
        }
    ]
    assert len(stream_calls) == 2
    assert stream_calls[-1][2]["stream"] is True

    connection_attempts = []
    connection_events = []
    connection_waits = []

    def connection_stream(_url, _headers, _payload):
        connection_attempts.append(True)
        if len(connection_attempts) == 1:
            raise requests.ConnectTimeout("synthetic timeout")
        return FakeStreamResponse(
            [b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n']
        )

    connection_gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        stream_model_json=connection_stream,
        local_embedding=lambda _text: [0.0],
        sleep_fn=connection_waits.append,
    )
    connection_message = connection_gateway.complete(
        [{"role": "user", "content": "retry connection"}],
        config,
        event_callback=connection_events.append,
    )
    assert connection_message["content"] == "ok"
    assert connection_waits == [1.0]
    assert connection_events[0]["errorType"] == "ConnectTimeout"
    assert connection_events[-1] == {"type": "text_delta", "text": "ok"}

    sustained_limit_responses = [
        FakeStreamResponse(
            [],
            status_code=429,
            headers={"Retry-After": "1"},
        )
        for _ in range(3)
    ] + [
        FakeStreamResponse(
            [b'data: {"choices":[{"delta":{"content":"recovered"}}]}\n\n']
        )
    ]
    sustained_limit_waits = []
    sustained_limit_events = []

    def sustained_limit_stream(_url, _headers, _payload):
        return sustained_limit_responses.pop(0)

    sustained_limit_gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        stream_model_json=sustained_limit_stream,
        local_embedding=lambda _text: [0.0],
        sleep_fn=sustained_limit_waits.append,
    )
    sustained_limit_message = sustained_limit_gateway.complete(
        [{"role": "user", "content": "respect a low RPM limit"}],
        config,
        event_callback=sustained_limit_events.append,
    )
    assert sustained_limit_message["content"] == "recovered"
    assert sustained_limit_waits == [5.0, 10.0, 20.0]
    assert [
        event["retryInMs"]
        for event in sustained_limit_events
        if event.get("type") == "model_retry"
    ] == [5000, 10000, 20000]

    assert ModelGateway._retry_delay(
        FakeStreamResponse(
            [],
            status_code=429,
            headers={"Retry-After-Ms": "7500"},
        ),
        1,
        status=429,
    ) == 7.5
    http_date_delay = ModelGateway._retry_delay(
        FakeStreamResponse(
            [],
            status_code=429,
            headers={
                "Retry-After": format_datetime(
                    datetime.now(timezone.utc) + timedelta(seconds=30),
                    usegmt=True,
                )
            },
        ),
        1,
        status=429,
    )
    assert 25.0 <= http_date_delay <= 30.0

    patient_limit_responses = [
        FakeStreamResponse([], status_code=429)
        for _ in range(5)
    ] + [
        FakeStreamResponse(
            [b'data: {"choices":[{"delta":{"content":"patient"}}]}\n\n']
        )
    ]
    patient_limit_waits = []
    patient_limit_events = []
    patient_limit_gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=post_model_json,
        stream_model_json=lambda *_args: patient_limit_responses.pop(0),
        local_embedding=lambda _text: [0.0],
        sleep_fn=patient_limit_waits.append,
    )
    patient_limit_message = patient_limit_gateway.complete(
        [{"role": "user", "content": "wait through the RPM window"}],
        config,
        event_callback=patient_limit_events.append,
    )
    assert patient_limit_message["content"] == "patient"
    assert patient_limit_waits == [5.0, 10.0, 20.0, 40.0, 60.0]
    assert [
        event["maxRetries"]
        for event in patient_limit_events
        if event.get("type") == "model_retry"
    ] == [5, 5, 5, 5, 5]

    class FakeEmbeddingResponse:
        def __init__(self, *, status_code, vector=None):
            self.status_code = status_code
            self.headers = {"Retry-After": "0"}
            self.vector = vector or []
            self.closed = False

        def close(self):
            self.closed = True

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return {"data": [{"embedding": self.vector}]}

    embedding_responses = [
        FakeEmbeddingResponse(status_code=429),
        FakeEmbeddingResponse(status_code=200, vector=[0.25, 0.75]),
    ]
    embedding_waits = []
    embedding_gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=lambda *_args: embedding_responses.pop(0),
        local_embedding=lambda _text: [0.0],
        sleep_fn=embedding_waits.append,
    )
    embedding_config = {
        **config,
        "model_type": "embedding",
    }
    assert embedding_gateway.embed("remember this", embedding_config) == [0.25, 0.75]
    assert embedding_waits == [5.0]

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
