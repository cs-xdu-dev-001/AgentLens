from pathlib import Path
from contextlib import contextmanager
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_gateway import ModelGateway
from knowflow.services.responses_protocol import ResponsesProtocolError, to_responses_tool, messages_to_response_input, parse_responses_message
from knowflow.services.agent_loop import AgentRunner, ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder


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


class FakeStreamResponse:
    def __init__(self, data):
        event = {
            "type": "response.completed",
            "response": {
                "status": "completed",
                "output": data.get("output"),
            },
        }
        self.body = (
            f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        ).encode("utf-8")

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        yield self.body


def stream_from_post(post_function):
    @contextmanager
    def stream(url, headers, payload, timeout=None):
        response = post_function(url, headers, payload)
        yield FakeStreamResponse(response.json())

    return stream


def main():
    def assert_protocol_error(payload):
        try:
            parse_responses_message(payload)
        except ResponsesProtocolError as exc:
            assert "{" not in str(exc) and "[" not in str(exc)
            return str(exc)
        raise AssertionError("expected ResponsesProtocolError")

    for bad in (None, {"output":"bad"}, {"output":["bad"]},
                {"output":[{"type":"message","content":"bad"}]},
                {"output":[{"type":"message","content":["bad"]}]},
                {"choices": [{"message": {}}]}, {"output": []},
                {"output":[{"type":"reasoning"}]},
                {"output":[{"type":"message","content":[{"type":"x"}]}]}):
        assert_protocol_error(bad)
    assert "call_id" in assert_protocol_error({"output":[{"type":"function_call","name":"x"}]})
    assert "name" in assert_protocol_error({"output":[{"type":"function_call","call_id":"c"}]})

    safe = ModelGateway._safe_error(RuntimeError('HTTP 502 {"secret":"x"} sk-testsecret Bearer testtoken Authorization=abc token=xyz'))
    assert "RuntimeError" in safe and all(x not in safe for x in ["secret","sk-testsecret","testtoken","Authorization=abc","token=xyz"])
    class E(RuntimeError): pass
    nested=E('HTTP {"outer":{"secret":"nested-value"}}'); nested.response=type('R',(),{'status_code':400})()
    safe=ModelGateway._safe_error(nested)
    assert 'E (HTTP 400)' in safe and all(x not in safe for x in ['outer','secret','nested-value','{','}'])

    calls=[]
    def post_test(url, headers, payload):
        calls.append(url)
        if url.endswith('/responses'):
            return FakeResponse({"output":[{"type":"message","content":[{"type":"output_text","text":"ok"}]}]})
        return FakeResponse({"choices":[{"message":{"role":"assistant","content":"ok"}}]})
    gwtest=ModelGateway(fetch_one=lambda *_a,**_k:None,cipher=FakeCipher(),post_model_json=post_test,stream_model_json=stream_from_post(post_test),local_embedding=lambda _:[0.])
    status,msg=gwtest.test({"model_type":"chat","api_mode":"responses","model_name":"m","base_url":"https://x","api_key_cipher":"k"})
    assert status=="available" and "Responses API" in msg and calls==["https://x/responses"]
    calls.clear(); status,msg=gwtest.test({"model_type":"chat","model_name":"m","base_url":"https://x","api_key_cipher":"k"})
    assert status=="available" and "Chat Completions" in msg and calls==["https://x/chat/completions"]
    for mode, suffix in (("responses", "/responses"), ("chat_completions", "/chat/completions")):
        calls.clear()
        def failing(url, headers, payload):
            calls.append(url); raise RuntimeError('bad sk-secret Bearer token')
        gwtest.post_model_json=failing
        gwtest.stream_model_json=stream_from_post(failing)
        cfg={"model_type":"chat","api_mode":mode,"model_name":"m","base_url":"https://x","api_key_cipher":"k"}
        status,msg=gwtest.test(cfg)
        assert status=="unavailable" and ("Responses API" if mode=="responses" else "Chat Completions") in msg and calls==["https://x"+suffix]
    emb_calls=[]
    def emb_ok(url,headers,payload): emb_calls.append(url); return FakeResponse({"data":[{"embedding":[1.,2.]}]})
    gwtest.post_model_json=emb_ok
    status,msg=gwtest.test({"model_type":"embedding","model_name":"e","base_url":"https://x","api_key_cipher":"k"})
    assert status=="available" and "2-dimension" in msg and len(emb_calls)==1
    gwtest.post_model_json=lambda *a: (_ for _ in ()).throw(RuntimeError('embedding boom {"secret":"nested"} sk-key token=hide'))
    status,msg=gwtest.test({"model_type":"embedding","model_name":"e","base_url":"https://x","api_key_cipher":"k"})
    assert status=="unavailable" and "Embedding connection failed" in msg and "RuntimeError" in msg
    assert all(x not in msg for x in ["nested", "sk-key", "hide", "{"])
    class BadStr(Exception):
        def __str__(self): raise RuntimeError("bad str")
    assert "BadStr" in ModelGateway._safe_error(BadStr())
    class BadStatus(Exception):
        @property
        def response(self): raise RuntimeError("bad status")
    assert "BadStatus" in ModelGateway._safe_error(BadStatus("oops"))
    safe=ModelGateway._safe_error(RuntimeError("https://host/path?a=one&token=two api-key: three x-api-key=four x-secret: five Authorization: six"))
    assert all(x not in safe for x in ["one","two","three","four","five","six"])
    assert len(ModelGateway._safe_error(RuntimeError("x"*1000))) <= 500
    for val in (None, 1, True):
        parsed=parse_responses_message({"output":[{"type":"function_call","call_id":"c","name":"f","arguments":val}]})
        assert isinstance(parsed["tool_calls"][0]["function"]["arguments"], str)
        assert isinstance(parsed["_response_items"][0]["arguments"], str)
    try:
        messages_to_response_input([{"role":"assistant","_response_items":["bad"]}])
    except ResponsesProtocolError:
        pass
    else: raise AssertionError("expected ResponsesProtocolError")
    flat = to_responses_tool({"type":"function","function":{"name":"web_search","description":"Search","parameters":{"type":"object"}}})
    assert flat == {"type":"function","name":"web_search","description":"Search","parameters":{"type":"object"},"strict":False}
    parsed = parse_responses_message({"output":[{"type":"reasoning","id":"r1"},{"type":"function_call","call_id":"c1","name":"web_search","arguments":{"query":"中文"}}]})
    assert parsed["tool_calls"][0]["function"]["arguments"] == '{"query": "中文"}'
    assert parsed["_response_items"][0]["type"] == "reasoning"
    assert parsed["_response_items"][1]["arguments"] == '{"query": "中文"}'
    fixture={"type":"function_call","call_id":"a","name":"x","arguments":{"n":1}}
    two=parse_responses_message({"output":[fixture,{"type":"function_call","call_id":"b","name":"y","arguments":{}}]})
    assert fixture["arguments"]=={"n":1} and [c["id"] for c in two["tool_calls"]]==["a","b"]
    inp = messages_to_response_input([parsed, {"role":"tool","tool_call_id":"c1","content":"ok"}])
    assert inp[0]["type"] == "reasoning" and inp[1]["type"] == "function_call" and inp[2] == {"type":"function_call_output","call_id":"c1","output":"ok"}
    legacy = messages_to_response_input([{"role":"assistant","content":"","tool_calls":[{"id":"c2","function":{"name":"x","arguments":"{}"}}]}])
    assert legacy[-1]["type"] == "function_call" and legacy[-1]["call_id"] == "c2"

    # End-to-end Responses rounds through real ModelGateway and AgentRunner.
    http_payloads=[]
    responses=[{"output":[{"type":"reasoning","id":"r1"},{"type":"function_call","call_id":"cid1","name":"web_search","arguments":{"query":"x"}}]},
               {"output":[{"type":"message","content":[{"type":"output_text","text":"done"}]}]}]
    def post(url, headers, payload):
        http_payloads.append(payload); return FakeResponse(responses.pop(0))
    gw=ModelGateway(fetch_one=lambda *_a,**_k:None,cipher=FakeCipher(),post_model_json=post,stream_model_json=stream_from_post(post),local_embedding=lambda _:[0.])
    reg=ToolRegistry(); reg.register(name="web_search",description="search",input_schema={"type":"object"},handler=lambda args:{"ok":True})
    tr=AgentTraceRecorder(run_id="responses-e2e")
    out=AgentRunner(gateway=gw,max_tool_rounds=2).run(messages=[{"role":"user","content":"find"}],config={"api_mode":"responses","model_name":"m","base_url":"https://x","api_key_cipher":"k"},registry=reg,trace=tr)
    assert out.answer=="done" and len(out.executions)==1 and out.executions[0].status=="success"
    kinds=[s["kind"] for s in out.trace]; assert kinds==["model","tool","model"]
    second=http_payloads[1]["input"]; assert any(i.get("type")=="reasoning" for i in second) and any(i.get("type")=="function_call" and i.get("call_id")=="cid1" for i in second) and any(i.get("type")=="function_call_output" and i.get("call_id")=="cid1" for i in second)

    failed_payloads=[]; failed_responses=[{"output":[{"type":"function_call","call_id":"bad1","name":"boom","arguments":"{}"}]},{"output":[{"type":"message","content":[{"type":"output_text","text":"recovered"}]}]}]
    def post_failed(url,headers,payload): failed_payloads.append(payload); return FakeResponse(failed_responses.pop(0))
    gw.post_model_json=post_failed; gw.stream_model_json=stream_from_post(post_failed); bad=ToolRegistry(); bad.register(name="boom",description="boom",input_schema={"type":"object"},handler=lambda args: (_ for _ in ()).throw(RuntimeError("boom")))
    out2=AgentRunner(gateway=gw,max_tool_rounds=2).run(messages=[{"role":"user","content":"go"}],config={"api_mode":"responses","model_name":"m","base_url":"https://x","api_key_cipher":"k"},registry=bad)
    assert out2.answer=="recovered" and out2.executions[0].status=="failed" and any(i.get("type")=="function_call_output" and i.get("call_id")=="bad1" for i in failed_payloads[1]["input"])
    calls = []

    def post_model_json(url, headers, payload):
        calls.append((url, payload))
        return FakeResponse({"output": [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Current answer."}]}]})

    gateway = ModelGateway(fetch_one=lambda *_a, **_k: None, cipher=FakeCipher(), post_model_json=post_model_json, stream_model_json=stream_from_post(post_model_json), local_embedding=lambda _: [0.0])
    config = {"api_mode": "responses", "model_name": "gpt-test", "base_url": "https://example.com/v1", "api_key_cipher": "key", "temperature": "0.2", "top_p": "0.8", "max_tokens": 123}
    message = gateway.complete([{ "role": "system", "content": "Be concise."}, {"role": "system", "content": "Use plain text."}, {"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Again"}], config)
    assert calls[0][0] == "https://example.com/v1/responses"
    payload = calls[0][1]
    assert payload["instructions"] == "Be concise.\n\nUse plain text."
    assert payload["input"] == [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}, {"role": "user", "content": "Again"}]
    assert payload["model"] == "gpt-test" and payload["store"] is False
    assert payload["max_output_tokens"] == 123
    assert payload["temperature"] == 0.2
    assert "top_p" not in payload
    assert "previous_response_id" not in payload and "conversation" not in payload
    assert message == {"role": "assistant", "content": "Current answer.", "tool_calls": []}

    def no_text(*_args):
        return FakeResponse({"output": [{"type": "message", "content": []}]})
    gateway.post_model_json = no_text
    gateway.stream_model_json = stream_from_post(no_text)
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
