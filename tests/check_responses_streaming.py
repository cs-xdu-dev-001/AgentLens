from pathlib import Path
from contextlib import contextmanager
import json
import requests
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.responses_protocol import (
    MAX_SSE_EVENT_BYTES,
    ResponsesProtocolError,
    ResponsesStreamAccumulator,
    iter_sse_json,
)
from knowflow.services.model_gateway import ModelGateway


class FakeCipher:
    def decrypt(self, value):
        return value or ""


class FakeStreamResponse:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.status_code = 200

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        assert chunk_size in {None, 8192}
        yield from self.chunks

    def close(self):
        self.closed = True


def stream_chunks(text: str = "Hello"):
    events = [
        {
            "type": "response.output_item.added",
            "item": {
                "id": "msg_gateway",
                "type": "message",
                "content": [],
            },
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_gateway",
            "delta": text[:3],
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_gateway",
            "delta": text[3:],
        },
        {
            "type": "response.output_item.done",
            "item": {
                "id": "msg_gateway",
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            },
        },
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        },
    ]
    return [
        f"data: {json.dumps(event)}\n\n".encode("utf-8")
        for event in events
    ]


def expect_protocol_error(callback, expected: str) -> None:
    try:
        callback()
    except ResponsesProtocolError as exc:
        assert expected in str(exc), str(exc)
        return
    raise AssertionError("expected ResponsesProtocolError")


def main() -> None:
    chunks = [
        b': keepalive\r\n'
        b'data: {"type":"response.output_item.added",'
        b'"item":{"id":"msg_1","type":"message","content":[]}}\r\n\r',
        b'\ndata: {"type":"response.output_text.delta",'
        b'"item_id":"msg_1","delta":"Hel"}\n\n'
        b'data: {"type":"response.output_text.delta",\n'
        b'data: "item_id":"msg_1","delta":"lo"}\n\n',
        b'data: {"type":"response.output_item.done",'
        b'"item":{"id":"msg_1","type":"message","content":'
        b'[{"type":"output_text","text":"Hello"}]}}\n\n'
        b'data: {"type":"response.completed","response":'
        b'{"status":"completed","output":[]}}\n\n'
        b'data: [DONE]\n\n',
    ]
    parsed = list(iter_sse_json(chunks))
    assert [event["type"] for event in parsed] == [
        "response.output_item.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_item.done",
        "response.completed",
    ]

    accumulator = ResponsesStreamAccumulator()
    public_events = []
    for event in parsed:
        public_events.extend(accumulator.feed(event))
    assert public_events[:2] == [
        {"type": "text_delta", "text": "Hel"},
        {"type": "text_delta", "text": "lo"},
    ]
    assert public_events[-1]["type"] == "completed"
    assert public_events[-1]["message"] == {
        "role": "assistant",
        "content": "Hello",
        "tool_calls": [],
    }
    assert accumulator.finish()["content"] == "Hello"

    tool_accumulator = ResponsesStreamAccumulator()
    tool_events = [
        {
            "type": "response.output_item.added",
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "web_search",
                "arguments": "",
            },
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_1",
            "delta": '{"query":',
        },
        {
            "type": "response.function_call_arguments.done",
            "item_id": "fc_1",
            "arguments": '{"query":"news"}',
        },
        {
            "type": "response.output_item.done",
            "item": {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "web_search",
                "arguments": '{"query":"news"}',
            },
        },
        {
            "type": "response.completed",
            "response": {"status": "completed", "output": []},
        },
    ]
    tool_public = []
    for event in tool_events:
        tool_public.extend(tool_accumulator.feed(event))
    tool_message = tool_accumulator.finish()
    assert not any(event["type"] == "text_delta" for event in tool_public)
    assert tool_message["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": '{"query":"news"}',
            },
        }
    ]
    assert tool_message["_response_items"][0]["arguments"] == '{"query":"news"}'

    unknown = ResponsesStreamAccumulator()
    assert unknown.feed({"type": "response.created", "response": {}}) == []

    expect_protocol_error(
        lambda: list(iter_sse_json([b"data: {not-json}\n\n"])),
        "invalid JSON",
    )
    expect_protocol_error(
        lambda: list(iter_sse_json([b'data: {"type":"response.created"'])),
        "incomplete event",
    )
    expect_protocol_error(
        lambda: list(iter_sse_json([b"x" * (MAX_SSE_EVENT_BYTES + 1)])),
        "size limit",
    )
    expect_protocol_error(
        lambda: ResponsesStreamAccumulator().feed(
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "code": "upstream_failed",
                        "message": (
                            "The model failed for sk-live-secret with "
                            "Authorization: Bearer hidden-token."
                        ),
                    }
                },
            }
        ),
        "upstream_failed",
    )
    try:
        ResponsesStreamAccumulator().feed(
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "code": "upstream_failed",
                        "message": (
                            "The model failed for sk-live-secret with "
                            "Authorization: Bearer hidden-token."
                        ),
                    }
                },
            }
        )
    except ResponsesProtocolError as exc:
        public_error = str(exc)
        assert "sk-live-secret" not in public_error
        assert "hidden-token" not in public_error
    else:
        raise AssertionError("expected sanitized ResponsesProtocolError")
    expect_protocol_error(
        lambda: ResponsesStreamAccumulator().feed(
            {
                "type": "response.incomplete",
                "response": {
                    "incomplete_details": {"reason": "max_output_tokens"}
                },
            }
        ),
        "max_output_tokens",
    )
    expect_protocol_error(
        lambda: ResponsesStreamAccumulator().feed(
            {
                "type": "error",
                "code": "bad_request",
                "message": "Invalid request.",
            }
        ),
        "bad_request",
    )
    expect_protocol_error(
        ResponsesStreamAccumulator().finish,
        "response.completed",
    )

    captured = {}
    fake_response = FakeStreamResponse(stream_chunks())

    @contextmanager
    def stream_model_json(url, headers, payload, timeout=None):
        captured.update(
            url=url,
            headers=headers,
            payload=payload,
            timeout=timeout,
        )
        try:
            yield fake_response
        finally:
            fake_response.close()

    gateway = ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=FakeCipher(),
        post_model_json=lambda *_args, **_kwargs: None,
        stream_model_json=stream_model_json,
        local_embedding=lambda _text: [0.0],
    )
    deltas = []
    config = {
        "model_type": "chat",
        "api_mode": "responses",
        "model_name": "gpt-test",
        "base_url": "https://example.com/v1",
        "api_key_cipher": "test-key",
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 123,
    }
    message = gateway.complete(
        [{"role": "user", "content": "Hi"}],
        config,
        event_callback=deltas.append,
    )
    assert captured["url"] == "https://example.com/v1/responses"
    assert captured["payload"]["stream"] is True
    assert "top_p" not in captured["payload"]
    assert deltas == [
        {"type": "text_delta", "text": "Hel"},
        {"type": "text_delta", "text": "lo"},
        {"type": "completed", "message": message},
    ]
    assert message == {
        "role": "assistant",
        "content": "Hello",
        "tool_calls": [],
    }
    assert fake_response.closed is True

    class ClosedBodyErrorResponse(FakeStreamResponse):
        def __init__(self):
            super().__init__(
                [
                    json.dumps(
                        {
                            "error": {
                                "type": "invalid_request_error",
                                "code": "unsupported_parameter",
                                "message": (
                                    "Unsupported parameter: top_p "
                                    "for sk-live-secret"
                                ),
                            }
                        }
                    ).encode("utf-8")
                ]
            )
            self.status_code = 400

        def raise_for_status(self):
            error = requests.HTTPError(
                "400 Client Error for url: "
                "https://example.com/v1/responses"
            )
            error.response = self
            raise error

        def json(self):
            if self.closed:
                raise RuntimeError("response body is closed")
            return json.loads(b"".join(self.chunks))

    closed_body_error = ClosedBodyErrorResponse()

    @contextmanager
    def error_stream(*_args, **_kwargs):
        try:
            yield closed_body_error
        finally:
            closed_body_error.close()

    gateway.stream_model_json = error_stream
    status, detail = gateway.test(config)
    assert status == "unavailable"
    assert "unsupported_parameter" in detail, detail
    assert "Unsupported parameter: top_p" in detail, detail
    assert "sk-live-secret" not in detail
    assert closed_body_error.closed is True

    cancelled_response = FakeStreamResponse(stream_chunks())

    @contextmanager
    def cancelled_stream(*_args, **_kwargs):
        try:
            yield cancelled_response
        finally:
            cancelled_response.close()

    gateway.stream_model_json = cancelled_stream
    try:
        gateway.complete(
            [{"role": "user", "content": "Hi"}],
            config,
            event_callback=lambda _event: (_ for _ in ()).throw(
                RuntimeError("cancel stream")
            ),
        )
    except RuntimeError as exc:
        assert str(exc) == "cancel stream"
    else:
        raise AssertionError("expected callback cancellation")
    assert cancelled_response.closed is True

    class ErrorResponse:
        status_code = 400

        @staticmethod
        def json():
            return {
                "error": {
                    "type": "invalid_request_error",
                    "code": "unsupported_parameter",
                    "message": (
                        "Unsupported stream option for sk-live-secret "
                        "Authorization: Bearer hidden-token."
                    ),
                }
            }

    class ErrorWithResponse(RuntimeError):
        def __init__(self):
            super().__init__(
                "400 Client Error for url: "
                "https://model.example/v1/responses?api_key=secret"
            )
            self.response = ErrorResponse()

    public_error = gateway._safe_error(ErrorWithResponse())
    assert "unsupported_parameter" in public_error, public_error
    assert "Unsupported stream option" in public_error, public_error
    assert "sk-live-secret" not in public_error
    assert "hidden-token" not in public_error
    assert "api_key=secret" not in public_error

    test_response = FakeStreamResponse(stream_chunks("pong"))

    @contextmanager
    def test_stream(*_args, **_kwargs):
        try:
            yield test_response
        finally:
            test_response.close()

    gateway.stream_model_json = test_stream
    status, detail = gateway.test(config)
    assert status == "available"
    assert "Responses API" in detail
    assert test_response.closed is True
    print("responses streaming protocol parses SSE and aggregates output")


if __name__ == "__main__":
    main()
