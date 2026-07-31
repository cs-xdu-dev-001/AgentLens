# Responses API Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让Responses协议的普通问答、Agent工具循环和连接检查使用真实上游SSE流，并把文本增量实时转发到现有前端。

**Architecture:** 在`responses_protocol.py`集中完成SSE分帧、事件归一化和最终消息聚合；`ModelGateway.complete()`消费同一事件流并通过可选回调暴露增量，避免保留第二套非流式Responses实现。普通聊天和Agent运行把文本增量送入现有`/api/chat/stream`，数据库仍只保存完整assistant消息。

**Tech Stack:** FastAPI、requests、Python生成器、Responses API SSE、React现有SSE客户端、Python脚本测试、Vite

---

## 文件职责映射

- `backend/knowflow/services/responses_protocol.py`：请求体、SSE分帧、事件归一化、工具参数聚合和最终消息。
- `backend/knowflow/runtime.py`：保持HTTP会话存活的流式POST上下文管理器。
- `backend/knowflow/services/model_gateway.py`：Responses流消费、增量回调、连接检查和Chat Completions兼容分流。
- `backend/knowflow/services/agent_loop.py`：将模型事件回调穿过工具循环。
- `backend/knowflow/routers/extensions.py`：取消感知、Agent增量事件和最终结果去重。
- `backend/knowflow/routers/chat.py`：非Agent普通问答的后台执行与增量转发。
- `backend/knowflow/runtime.py`：`generate_answer()`把增量回调传入模型网关。
- `frontend/react/src/controller/chatFlow.js`：沿用现有`answer`事件，无需新增前端事件协议。
- `tests/check_responses_streaming.py`：SSE解析、网关流、错误、断流和连接检查。
- `tests/check_responses_protocol.py`：请求体及最终消息兼容断言。
- `tests/check_agent_loop.py`：Agent增量回调与工具轮次。
- `tests/check_agent_web_search_flow.py`、`tests/check_mcp_agent_flow.py`：工具回归。
- `tests/check_chat_streaming.py`：普通聊天增量不重复。
- `README.md`：Responses流式能力与兼容边界。

## Task 1：SSE协议解析与最终消息聚合

**Files:**
- Create: `tests/check_responses_streaming.py`
- Modify: `tests/check_responses_protocol.py`
- Modify: `backend/knowflow/services/responses_protocol.py`

- [ ] **Step 1：写SSE分帧红灯测试**

在`tests/check_responses_streaming.py`构造跨块输入：

```python
chunks = [
    b'data: {"type":"response.output_item.added","item":{"id":"msg_1","type":"message"}}\r\n\r',
    b'\ndata: {"type":"response.output_text.delta","item_id":"msg_1","delta":"Hel"}\n\n',
    b'data: {"type":"response.output_text.delta","item_id":"msg_1","delta":"lo"}\n\n',
    b'data: {"type":"response.completed","response":{"status":"completed","output":[]}}\n\n',
]
events = list(iter_sse_json(chunks))
assert [event["type"] for event in events] == [
    "response.output_item.added",
    "response.output_text.delta",
    "response.output_text.delta",
    "response.completed",
]
```

另测注释行、多个`data:`行、`[DONE]`和非法JSON；非法JSON必须抛`ResponsesProtocolError`。

- [ ] **Step 2：运行测试确认红灯**

```powershell
py -3.13 tests/check_responses_streaming.py
```

Expected：导入`iter_sse_json`失败。

- [ ] **Step 3：实现有限缓冲SSE解析器**

在`responses_protocol.py`加入：

```python
MAX_SSE_EVENT_BYTES = 1_048_576


def iter_sse_json(chunks: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    buffer = b""
    for chunk in chunks:
        buffer += bytes(chunk or b"")
        if len(buffer) > MAX_SSE_EVENT_BYTES:
            raise ResponsesProtocolError("Responses SSE event exceeded the size limit.")
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
                raise ResponsesProtocolError("Responses SSE contained invalid JSON.") from exc
            if not isinstance(value, dict):
                raise ResponsesProtocolError("Responses SSE event must be an object.")
            yield value
    if buffer.strip():
        raise ResponsesProtocolError("Responses SSE ended with an incomplete event.")
```

- [ ] **Step 4：写文本、工具和结束状态聚合红灯测试**

测试`ResponsesStreamAccumulator.feed()`：

```python
accumulator.feed({"type": "response.output_item.added", "item": {"id": "fc_1", "type": "function_call", "call_id": "call_1", "name": "web_search", "arguments": ""}})
accumulator.feed({"type": "response.function_call_arguments.delta", "item_id": "fc_1", "delta": '{"query":'})
accumulator.feed({"type": "response.function_call_arguments.done", "item_id": "fc_1", "arguments": '{"query":"news"}'})
completed = accumulator.feed({"type": "response.completed", "response": {"status": "completed", "output": []}})
assert completed["message"]["tool_calls"][0]["function"]["arguments"] == '{"query":"news"}'
```

分别断言`response.failed`、`response.incomplete`、流内`error`及没有`response.completed`时失败。

- [ ] **Step 5：实现最小事件聚合器**

实现`ResponsesStreamAccumulator`：

- 以`item_id`保存Items和工具参数。
- `response.output_text.delta`只为message Item产生`{"type":"text_delta","text":...}`。
- `response.output_item.done`以最终Item覆盖初始Item。
- `response.completed`调用现有`parse_responses_message()`生成完整消息。
- 失败事件只提取`code`和有限长度`message`，不拼接完整事件。
- `finish()`在未完成时抛`ResponsesProtocolError("Responses SSE ended before response.completed.")`。

- [ ] **Step 6：运行协议测试并提交**

```powershell
py -3.13 tests/check_responses_streaming.py
py -3.13 tests/check_responses_protocol.py
git add backend/knowflow/services/responses_protocol.py tests/check_responses_streaming.py tests/check_responses_protocol.py
git commit -m "feat: parse responses SSE events"
```

Expected：两个测试退出码0。

## Task 2：流式HTTP传输与ModelGateway

**Files:**
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/services/model_gateway.py`
- Modify: `tests/check_responses_streaming.py`
- Modify: `tests/check_model_gateway_tools.py`

- [ ] **Step 1：写网关流式请求红灯测试**

使用假的上下文管理器和Response：

```python
@contextmanager
def stream_model_json(url, headers, payload, timeout=None):
    captured.update(url=url, payload=payload)
    yield FakeStreamResponse(chunks)

deltas = []
message = gateway.complete(
    [{"role": "user", "content": "Hi"}],
    responses_config,
    event_callback=lambda event: deltas.append(event),
)
assert captured["payload"]["stream"] is True
assert deltas == [{"type": "text_delta", "text": "Hel"}, {"type": "text_delta", "text": "lo"}]
assert message["content"] == "Hello"
```

断言上下文退出时Response关闭；HTTP 400只暴露脱敏错误。

- [ ] **Step 2：运行测试确认红灯**

```powershell
py -3.13 tests/check_responses_streaming.py
```

Expected：`ModelGateway`不接受`stream_model_json`或`event_callback`。

- [ ] **Step 3：实现流式HTTP上下文管理器**

在`runtime.py`加入：

```python
@contextmanager
def stream_model_json(url, headers, payload, timeout=None):
    session = requests.Session()
    session.trust_env = MODEL_TRUST_ENV
    response = None
    try:
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout or MODEL_REQUEST_TIMEOUT,
            stream=True,
        )
        yield response
    finally:
        if response is not None:
            response.close()
        session.close()
```

构造全局`gateway`时注入该函数。

- [ ] **Step 4：让Responses只走流式实现**

`build_responses_payload()`固定写入：

```python
payload["stream"] = True
```

`ModelGateway.__init__()`接收`stream_model_json`。`complete()`新增可选参数：

```python
event_callback: Callable[[dict[str, Any]], None] | None = None
```

当`api_mode == "responses"`时：

1. 用上下文管理器请求`/responses`。
2. `raise_for_status()`。
3. 用`iter_content(chunk_size=None)`送入`iter_sse_json()`。
4. 每个事件交给聚合器。
5. 对归一化事件调用`event_callback`。
6. 返回`accumulator.finish()`得到的完整消息。

Chat Completions分支不传`stream`，保持现有payload和JSON解析。

- [ ] **Step 5：连接检查消费真实流**

`ModelGateway.test()`继续调用`complete()`，因此Responses检查只有收到`response.completed`且得到有效消息才成功。补测试断言只请求一次`/responses`，不降级到`/chat/completions`。

- [ ] **Step 6：运行定向测试并提交**

```powershell
py -3.13 tests/check_responses_streaming.py
py -3.13 tests/check_responses_protocol.py
py -3.13 tests/check_model_gateway_tools.py
git add backend/knowflow/runtime.py backend/knowflow/services/model_gateway.py backend/knowflow/services/responses_protocol.py tests/check_responses_streaming.py tests/check_responses_protocol.py tests/check_model_gateway_tools.py
git commit -m "feat: stream responses model requests"
```

## Task 3：Agent工具循环实时转发

**Files:**
- Modify: `backend/knowflow/services/agent_loop.py`
- Modify: `backend/knowflow/routers/extensions.py`
- Modify: `tests/check_agent_loop.py`
- Modify: `tests/check_agent_web_search_flow.py`
- Modify: `tests/check_mcp_agent_flow.py`

- [ ] **Step 1：写Agent增量和工具轮次红灯测试**

假的Gateway在第一轮发出function_call并返回工具调用，第二轮回调两次文本：

```python
events = []
result = runner.run(
    messages=messages,
    config=config,
    registry=registry,
    model_event_callback=events.append,
)
assert [event["text"] for event in events] == ["final ", "answer"]
assert result.answer == "final answer"
assert len(result.executions) == 1
```

第一轮工具调用不得产生公开文本增量；工具只执行一次。

- [ ] **Step 2：运行测试确认红灯**

```powershell
py -3.13 tests/check_agent_loop.py
```

Expected：`AgentRunner.run()`不接受`model_event_callback`。

- [ ] **Step 3：穿透模型事件回调**

`AgentRunner.run()`新增：

```python
model_event_callback: Callable[[dict[str, Any]], None] | None = None
```

调用网关时传入`event_callback=model_event_callback`。`_CancellationAwareGateway.complete()`包装该回调，每个事件前后调用`_raise_if_cancelled()`，回调抛错时上游上下文必须关闭。

`execute_agent_chat()`为每次runner调用传入回调，只转发：

```python
emit_named("message", {"type": "answer", "content": event["text"]})
```

协议聚合器只有确定当前输出Item是message时才产生`text_delta`；function_call轮次不产生公开文本。

- [ ] **Step 4：避免最终答案重复发送**

`agent_chat_stream.generate()`对队列中的`message`事件立即：

```python
yield sse_event("message", value)
```

记录`streamed_answer=True`。收到最终`result`后，仅当没有流式增量时才执行原来的12字符兼容分片；引用、工具、质量和`done`保持原顺序。

- [ ] **Step 5：运行Agent回归并提交**

```powershell
py -3.13 tests/check_agent_loop.py
py -3.13 tests/check_agent_web_search_flow.py
py -3.13 tests/check_mcp_agent_flow.py
py -3.13 tests/check_agent_run_api.py
py -3.13 tests/check_agent_run_store.py
git add backend/knowflow/services/agent_loop.py backend/knowflow/routers/extensions.py tests/check_agent_loop.py tests/check_agent_web_search_flow.py tests/check_mcp_agent_flow.py
git commit -m "feat: stream responses agent output"
```

## Task 4：普通聊天实时转发

**Files:**
- Create: `tests/check_chat_streaming.py`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/routers/chat.py`

- [ ] **Step 1：写普通问答红灯测试**

用TestClient替换网关为可控假流，POST`/api/chat/stream`，断言：

```python
answer_events = [
    event for event in parse_sse(response.text)
    if event["type"] == "answer"
]
assert [event["content"] for event in answer_events] == ["Hello", " world"]
assert "".join(event["content"] for event in answer_events) == "Hello world"
assert response.text.count('"type": "done"') == 1
```

再断言数据库只有一条完整assistant消息，没有增量碎片。

- [ ] **Step 2：运行测试确认红灯**

```powershell
py -3.13 tests/check_chat_streaming.py
```

Expected：当前路由只在模型完成后按12字符模拟分片。

- [ ] **Step 3：给普通生成链路增加增量回调**

`generate_answer()`新增`event_callback=None`并传给`gateway.chat()`；`ModelGateway.chat()`将回调传给`complete()`。

在`chat.py`提取内部`run_chat(payload, request, event_callback=None)`，原`chat()`调用它且不传回调。

非Agent的`chat_stream()`使用工作线程和队列：

- worker调用`run_chat()`。
- 模型回调把`message`事件放入队列。
- 生成器立即yield增量。
- worker完成后把结果放入队列。
- 如果收到过真实增量，不再执行12字符模拟分片。
- 最后发送引用、质量和单个`done`。

- [ ] **Step 4：运行普通聊天及前端契约测试**

```powershell
py -3.13 tests/check_chat_streaming.py
py -3.13 tests/check_frontend_chat_flow_module.py
```

Expected：真实增量不重复，Chat Completions仍使用兼容分片。

- [ ] **Step 5：提交普通聊天流**

```powershell
git add backend/knowflow/runtime.py backend/knowflow/routers/chat.py tests/check_chat_streaming.py
git commit -m "feat: stream responses chat output"
```

## Task 5：错误边界、文档与全量门禁

**Files:**
- Modify: `tests/check_responses_streaming.py`
- Modify: `tests/check_release_hygiene.py` only if the new test requires the standard secure-cookie isolation declaration
- Modify: `README.md`
- Verify: all changed files

- [ ] **Step 1：补齐错误和取消红灯测试**

测试HTTP 400、`response.failed`、`response.incomplete`、流内`error`、非法JSON、未完成断流、超过事件大小限制和回调取消。断言：

```python
assert "sk-live-secret" not in public_error
assert "Authorization" not in public_error
assert "response.completed" in interrupted_error
assert fake_response.closed is True
```

- [ ] **Step 2：运行测试确认红灯并做最小修正**

```powershell
py -3.13 tests/check_responses_streaming.py
```

Expected：至少一个新错误边界失败；只修改协议解析、网关关闭或脱敏逻辑，不增加自动重试。

- [ ] **Step 3：更新README**

写明：

- Responses请求默认使用`stream: true`。
- 上游必须提供标准SSE事件并以`response.completed`结束。
- KnowFlow不自动降级到Chat Completions。
- 非标准中转站返回400时应检查模型路由及Responses SSE兼容性。

- [ ] **Step 4：运行完整门禁**

```powershell
$checks = Get-ChildItem tests -Filter 'check_*.py' | Sort-Object Name
foreach ($check in $checks) {
  py -3.13 $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "FAILED: $($check.Name)" }
}
npm ci --prefix frontend
npm audit --prefix frontend
npm run build --prefix frontend
git diff --check
```

Expected：全部Python检查通过；前端audit为0个漏洞；构建成功。

- [ ] **Step 5：检查敏感文件和提交**

```powershell
git ls-files -- 'backend/.env' 'data/*.db' 'data/**/*.db' 'data/uploads/**' 'data/mem0/**' 'frontend/dist/**'
git status --short
git diff --cached --check
```

Expected：禁止文件列表为空；不提交真实Key、数据库、上传文件、Mem0数据或构建产物。

```powershell
git add README.md backend/knowflow tests
git commit -m "fix: harden responses streaming failures"
```

## 生产验收

1. 新建或编辑一条Responses模型配置。
2. 连接检查确认请求`/v1/responses`且SSE正常完成。
3. 普通无工具问答确认首字在模型完成前到达。
4. 联网搜索确认工具参数完整、工具只执行一次、第二轮答案实时输出。
5. MCP或Skill调用确认trace最终完成。
6. 中断生成确认上游连接关闭且运行状态不是成功。
7. Chat Completions配置确认原路径正常。
8. journal确认无Traceback、重复保存、敏感信息或未关闭连接警告。
