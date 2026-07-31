# Selectable Responses API Protocol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让每条聊天模型配置可明确选择Chat Completions或Responses API，并让普通问答、联网搜索、MCP、Skill及连接测试严格使用所选协议。

**Architecture:** 在模型配置层持久化`api_mode`，由`ModelGateway`按协议分流；新增独立Responses适配器负责请求Items、输出Items和函数调用转换，对现有Agent循环继续暴露统一的`role/content/tool_calls`结构。Responses的reasoning及函数调用Items仅保留在单次Agent运行内，不进入聊天正文或数据库。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy、SQLite/MySQL、React、原生fetch兼容HTTP客户端、Python脚本测试、Vite

---

## 文件职责映射

- `backend/knowflow/db_schema.py`：SQLite/MySQL新建库的`api_mode`列。
- `backend/knowflow/database.py`：旧库幂等迁移及schema版本9。
- `backend/knowflow/schemas.py`：模型配置请求中的`apiMode`字段。
- `backend/knowflow/runtime.py`：数据库行到前端模型对象的`apiMode`归一化。
- `backend/knowflow/routers/model_configs.py`：协议校验、创建、更新和连接测试入口。
- `backend/knowflow/services/responses_protocol.py`：Responses请求构造、工具schema转换、输出解析及协议错误。
- `backend/knowflow/services/model_gateway.py`：按`api_mode`调用`/chat/completions`或`/responses`。
- `backend/knowflow/services/agent_loop.py`：在当前Agent运行内保留Responses输出Items，供下一工具轮回放。
- `frontend/react/src/data/settings.js`：预设模型的默认协议。
- `frontend/react/src/components/SettingsPage.jsx`：表单值、编辑回填和提交payload。
- `frontend/react/src/components/ModelConfigForm.jsx`：聊天模型协议选择器。
- `frontend/react/src/components/ModelListPanel.jsx`：模型协议标签。
- `tests/check_model_api_mode.py`：持久化、兼容默认值及400校验。
- `tests/check_responses_protocol.py`：Responses纯文本、工具调用、错误和端点契约。
- `tests/check_agent_loop.py`：Responses中间Items在工具循环内的传递。
- `tests/check_model_gateway_tools.py`：旧Chat Completions路径不回归。
- `tests/check_frontend_model_settings_react.py`、`tests/check_frontend_model_list_data_react.py`、`tests/check_model_provider_presets.py`：前端字段、标签和预设协议。
- `README.md`：用户配置及兼容边界。

## Task 1：持久化并校验模型接口协议

**Files:**
- Create: `tests/check_model_api_mode.py`
- Modify: `backend/knowflow/db_schema.py`
- Modify: `backend/knowflow/database.py`
- Modify: `backend/knowflow/schemas.py`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/routers/model_configs.py`
- Modify: `tests/check_schema_versioning.py`
- Modify: `tests/check_memory_config.py`
- Modify: `tests/check_memory_operations.py`
- Modify: `tests/check_skill_schema.py`

- [ ] **Step 1：先写模型协议API失败测试**

`tests/check_model_api_mode.py`沿用现有`TestClient`隔离数据库模式，设置：

```python
os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
os.environ["KNOWFLOW_SECRET_KEY"] = "model-api-mode-test-secret"
os.environ["KNOWFLOW_COOKIE_SECURE"] = "0"
os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
```

测试同一登录用户的以下契约：

```python
legacy = client.post("/api/model-configs", json={
    "name": "Legacy Chat",
    "provider": "custom",
    "modelType": "chat",
    "baseUrl": "https://example.com/v1",
    "apiKey": "test-key",
    "modelName": "legacy-chat",
})
assert legacy.status_code == 200, legacy.text
assert legacy.json()["data"]["apiMode"] == "chat_completions"

responses = client.post("/api/model-configs", json={
    "name": "Responses Chat",
    "provider": "openai",
    "modelType": "chat",
    "apiMode": "responses",
    "baseUrl": "https://example.com/v1",
    "apiKey": "test-key",
    "modelName": "gpt-test",
})
assert responses.status_code == 200, responses.text
model_id = responses.json()["data"]["id"]
assert client.get(f"/api/model-configs/{model_id}").json()["data"]["apiMode"] == "responses"

updated = client.put(f"/api/model-configs/{model_id}", json={"apiMode": "chat_completions"})
assert updated.status_code == 200, updated.text
assert updated.json()["data"]["apiMode"] == "chat_completions"

assert client.put(f"/api/model-configs/{model_id}", json={"apiMode": "auto"}).status_code == 400
assert client.post("/api/model-configs", json={
    "name": "Invalid Embedding",
    "provider": "openai",
    "modelType": "embedding",
    "apiMode": "responses",
    "baseUrl": "https://example.com/v1",
    "modelName": "embedding-test",
}).status_code == 400
```

- [ ] **Step 2：运行新测试，确认红灯**

Run:

```powershell
python tests/check_model_api_mode.py
```

Expected：失败于响应缺少`apiMode`、请求字段被忽略或数据库缺少`api_mode`。

- [ ] **Step 3：增加新建表列和旧库迁移**

在SQLite和MySQL的`model_config`表中分别加入：

```sql
api_mode TEXT NOT NULL DEFAULT 'chat_completions'
```

```sql
api_mode VARCHAR(30) NOT NULL DEFAULT 'chat_completions'
```

在`Database.migrate_schema()`加入：

```python
self.add_column_if_missing(
    conn,
    "model_config",
    "api_mode",
    "VARCHAR(30) NOT NULL DEFAULT 'chat_completions'"
    if self.is_mysql
    else "TEXT NOT NULL DEFAULT 'chat_completions'",
)
```

将`CURRENT_SCHEMA_VERSION`改为`9`，描述改为：

```python
"Add selectable chat model API protocol."
```

同步把四个显式断言版本8的测试改为9；`check_schema_versioning.py`改为断言描述含`protocol`，并断言`model_config`包含`api_mode`。

- [ ] **Step 4：增加请求字段、400校验和响应归一化**

在两个Pydantic模型中加入：

```python
apiMode: str = "chat_completions"
```

```python
apiMode: str | None = None
```

在`model_configs.py`加入统一校验，确保错误码是400而非Pydantic默认422：

```python
MODEL_API_MODES = {"chat_completions", "responses"}


def validate_api_mode(model_type: str, api_mode: str | None) -> str:
    mode = str(api_mode or "chat_completions").strip().lower()
    if mode not in MODEL_API_MODES:
        raise HTTPException(status_code=400, detail="不支持的模型接口协议。")
    if model_type != "chat" and mode != "chat_completions":
        raise HTTPException(status_code=400, detail="只有聊天模型可以使用Responses API。")
    return mode
```

创建时验证并写入`api_mode`；更新时先读取完整当前记录，再用“请求值覆盖当前值”得到有效`model_type`和`api_mode`后验证，最后把`apiMode`映射到`api_mode`。不要让先把模型改为embedding、协议仍为responses的组合落库。

在`normalize_model_config()`返回：

```python
"apiMode": row.get("api_mode") or "chat_completions",
```

- [ ] **Step 5：运行定向测试，确认绿灯**

Run:

```powershell
python tests/check_model_api_mode.py
python tests/check_schema_versioning.py
python tests/check_memory_config.py
python tests/check_memory_operations.py
python tests/check_skill_schema.py
```

Expected：全部退出码0；旧请求不传`apiMode`时返回`chat_completions`。

- [ ] **Step 6：提交持久化层**

```powershell
git add backend/knowflow/db_schema.py backend/knowflow/database.py backend/knowflow/schemas.py backend/knowflow/runtime.py backend/knowflow/routers/model_configs.py tests/check_model_api_mode.py tests/check_schema_versioning.py tests/check_memory_config.py tests/check_memory_operations.py tests/check_skill_schema.py
git commit -m "feat: persist model API protocol"
```

## Task 2：实现Responses纯文本适配和网关分流

**Files:**
- Create: `backend/knowflow/services/responses_protocol.py`
- Create: `tests/check_responses_protocol.py`
- Modify: `backend/knowflow/services/model_gateway.py`
- Modify: `tests/check_model_gateway_tools.py`

- [ ] **Step 1：写纯文本请求与响应失败测试**

在`tests/check_responses_protocol.py`构造假的HTTP响应并捕获URL和payload，验证：

```python
message = gateway.complete(
    [
        {"role": "system", "content": "Answer with sources."},
        {"role": "user", "content": "What changed?"},
    ],
    {
        "provider": "openai",
        "model_name": "gpt-test",
        "base_url": "https://example.com/v1",
        "api_key_cipher": "unit-test-key",
        "api_mode": "responses",
        "temperature": 0.2,
        "top_p": 0.8,
        "max_tokens": 1200,
    },
)
assert captured["url"] == "https://example.com/v1/responses"
assert captured["payload"]["instructions"] == "Answer with sources."
assert captured["payload"]["input"] == [
    {"role": "user", "content": "What changed?"},
]
assert captured["payload"]["max_output_tokens"] == 1200
assert captured["payload"]["store"] is False
assert "previous_response_id" not in captured["payload"]
assert "conversation" not in captured["payload"]
assert message == {"role": "assistant", "content": "Current answer.", "tool_calls": []}
```

首版固定使用`store: false`和KnowFlow本地完整上下文，不引入`previous_response_id`或Conversations API。

假的Responses数据使用真实形状：

```python
{
    "id": "resp_1",
    "output": [{
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "Current answer."}],
    }],
}
```

同时扩展`check_model_gateway_tools.py`，显式断言缺少`api_mode`仍请求`/chat/completions`且payload继续使用`messages`。

- [ ] **Step 2：运行两个测试，确认红灯**

```powershell
python tests/check_responses_protocol.py
python tests/check_model_gateway_tools.py
```

Expected：Responses测试失败，因为网关仍请求`/chat/completions`并读取`choices`；Chat测试保持通过。

- [ ] **Step 3：新增Responses协议适配器**

在`responses_protocol.py`定义：

```python
class ResponsesProtocolError(ValueError):
    pass


def build_responses_payload(
    messages: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
) -> dict[str, Any]:
    instructions = "\n\n".join(
        str(message.get("content") or "")
        for message in messages
        if message.get("role") == "system" and message.get("content")
    )
    payload: dict[str, Any] = {
        "model": config["model_name"],
        "input": messages_to_response_input(messages),
        "store": False,
    }
    if instructions:
        payload["instructions"] = instructions
    if config.get("temperature") is not None:
        payload["temperature"] = float(config["temperature"])
    if config.get("top_p") is not None:
        payload["top_p"] = float(config["top_p"])
    if config.get("max_tokens") is not None:
        payload["max_output_tokens"] = int(config["max_tokens"])
    if tools:
        payload["tools"] = [to_responses_tool(tool) for tool in tools]
        payload["tool_choice"] = tool_choice or "auto"
    return payload
```

`messages_to_response_input()`首版处理system之外的普通user/assistant消息；`parse_responses_message()`遍历`output[]`，只拼接`message.content[]`中的`output_text.text`，返回统一内部结构：

```python
{
    "role": "assistant",
    "content": "\n".join(text_parts) or None,
    "tool_calls": tool_calls,
}
```

没有文本和工具调用时抛`ResponsesProtocolError("Responses API没有返回文本或工具调用。")`。

- [ ] **Step 4：在ModelGateway按配置分流**

在`complete()`远程调用分支最前面加入：

```python
api_mode = str(config.get("api_mode") or "chat_completions")
if api_mode == "responses":
    url = self.endpoint(config["base_url"], "/responses")
    payload = build_responses_payload(
        messages,
        config,
        tools=tools,
        tool_choice=tool_choice,
    )
    response = self.post_model_json(url, self.headers(config), payload)
    response.raise_for_status()
    return parse_responses_message(response.json())
```

原Chat Completions分支不改请求字段和解析逻辑。未知`api_mode`在路由已阻止，网关仍以明确错误防御非法数据库数据。

- [ ] **Step 5：运行定向测试，确认绿灯**

```powershell
python tests/check_responses_protocol.py
python tests/check_model_gateway_tools.py
python tests/check_model_provider_presets.py
```

Expected：Responses请求使用`/responses`；旧Chat请求仍使用`/chat/completions`。

- [ ] **Step 6：提交纯文本协议层**

```powershell
git add backend/knowflow/services/responses_protocol.py backend/knowflow/services/model_gateway.py tests/check_responses_protocol.py tests/check_model_gateway_tools.py
git commit -m "feat: add responses API gateway"
```

## Task 3：打通Responses工具调用和多轮Agent循环

**Files:**
- Modify: `backend/knowflow/services/responses_protocol.py`
- Modify: `backend/knowflow/services/agent_loop.py`
- Modify: `tests/check_responses_protocol.py`
- Modify: `tests/check_agent_loop.py`

- [ ] **Step 1：写工具schema及首轮函数调用失败测试**

验证Chat格式工具：

```python
{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the public web.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    },
}
```

转换为Responses格式：

```python
{
    "type": "function",
    "name": "web_search",
    "description": "Search the public web.",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
    "strict": False,
}
```

假的首轮输出包含reasoning和function_call：

```python
output_items = [
    {"id": "rs_1", "type": "reasoning", "summary": []},
    {
        "id": "fc_1",
        "type": "function_call",
        "call_id": "call_search_1",
        "name": "web_search",
        "arguments": '{"query":"latest release"}',
    },
]
```

断言归一化结果包含`tool_calls[0].id == "call_search_1"`，并带内部`_response_items == output_items`。

- [ ] **Step 2：写第二轮回放和Agent端到端失败测试**

使用依次返回“function_call”和“最终message”的假HTTP函数运行真实`AgentRunner`，断言第二次`/responses`请求的`input`顺序包含：

```python
{"id": "rs_1", "type": "reasoning", "summary": []}
{"id": "fc_1", "type": "function_call", "call_id": "call_search_1", ...}
{"type": "function_call_output", "call_id": "call_search_1", "output": "..."}
```

并断言Agent最终答案、tool execution和trace均成功。

- [ ] **Step 3：运行工具循环测试，确认红灯**

```powershell
python tests/check_responses_protocol.py
python tests/check_agent_loop.py
```

Expected：失败于工具格式未扁平化、`function_call`未解析、第二轮没有回放Items。

- [ ] **Step 4：实现工具转换和输出Items保留**

`to_responses_tool()`必须校验工具结构并扁平化；`parse_responses_message()`必须把function_call转为：

```python
{
    "id": item["call_id"],
    "type": "function",
    "function": {
        "name": item["name"],
        "arguments": item.get("arguments") or "{}",
    },
}
```

若`arguments`是对象，用`json.dumps(..., ensure_ascii=False)`稳定序列化。仅当本轮包含工具调用或非message Item（例如reasoning）时，将完整`output[]`深拷贝到`_response_items`；纯文本响应保持公开归一化结构不变。该内部字段只用于当前运行。

`messages_to_response_input()`按以下顺序转换：

1. system消息跳过，已进入`instructions`。
2. assistant消息存在`_response_items`时直接回放这些Items，不再重复构造文本或函数调用。
3. 兼容没有`_response_items`的assistant `tool_calls`，构造function_call Items。
4. `role=tool`转换为`function_call_output`，`call_id`来自`tool_call_id`。
5. 普通user/assistant消息保留`role/content`。

在`AgentRunner.run()`追加assistant工作消息时保留内部Items：

```python
assistant_message = {
    "role": "assistant",
    "content": message.get("content"),
    "tool_calls": calls,
}
if message.get("_response_items"):
    assistant_message["_response_items"] = message["_response_items"]
working.append(assistant_message)
```

`working`是运行时局部列表；不得把`_response_items`加入`save_message()`、API聊天正文或`trace_json`。

- [ ] **Step 5：运行工具循环测试，确认绿灯**

```powershell
python tests/check_responses_protocol.py
python tests/check_agent_loop.py
python tests/check_agent_web_search_flow.py
python tests/check_mcp_agent_flow.py
```

Expected：Responses第二轮含匹配`call_id`的`function_call_output`；现有web_search/MCP测试不回归。

- [ ] **Step 6：提交工具循环**

```powershell
git add backend/knowflow/services/responses_protocol.py backend/knowflow/services/agent_loop.py tests/check_responses_protocol.py tests/check_agent_loop.py
git commit -m "feat: support responses tool loops"
```

## Task 4：补齐协议错误和连接测试语义

**Files:**
- Modify: `backend/knowflow/services/responses_protocol.py`
- Modify: `backend/knowflow/services/model_gateway.py`
- Modify: `tests/check_responses_protocol.py`

- [ ] **Step 1：先写错误分支失败测试**

逐项覆盖：

```python
{"choices": [{"message": {"content": "chat shape"}}]}
```

配置为Responses时必须报“上游返回了Chat Completions结构”；`output`非列表报“Responses返回结构无效”；function_call缺`call_id`或`name`分别报明确中文错误；空`output`报“没有返回文本或工具调用”。断言错误文本不包含API Key、`Authorization`或完整响应JSON。

再为`gateway.test()`写两条测试：

- `api_mode=responses`仅请求`/responses`，成功文案包含`Responses API`。
- 缺少`api_mode`仅请求`/chat/completions`，成功文案包含`Chat Completions`。

- [ ] **Step 2：运行测试，确认红灯**

```powershell
python tests/check_responses_protocol.py
```

Expected：错误信息或连接测试文案断言失败。

- [ ] **Step 3：实现严格解析和脱敏连接测试**

`parse_responses_message()`在解析前执行结构判定：

```python
if "choices" in data and "output" not in data:
    raise ResponsesProtocolError(
        "配置选择了Responses API，但上游返回了Chat Completions结构。"
    )
output = data.get("output")
if not isinstance(output, list):
    raise ResponsesProtocolError("Responses API返回结构无效。")
```

function_call缺关键字段时只报告字段名，不拼接整个Item。`ModelGateway.test()`按`api_mode`调用`complete()`，成功文案分别返回：

```python
"Responses API连接成功，模型返回了正常响应。"
"Chat Completions连接成功，模型返回了正常响应。"
```

失败时使用固定脱敏函数，不拼接请求头或完整响应对象：

```python
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE),
)


def sanitize_protocol_error(exc: Exception) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ")[:500]
    for pattern in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text or "上游模型请求失败。"
```

保留HTTP状态、上游错误类型和可执行摘要，不自动换协议重试。连接测试返回`"Responses API连接失败：" + sanitize_protocol_error(exc)`或对应Chat Completions文案。

- [ ] **Step 4：运行错误和兼容测试**

```powershell
python tests/check_responses_protocol.py
python tests/check_model_gateway_tools.py
python tests/check_model_provider_presets.py
```

Expected：全部退出码0；每次测试只命中所选协议端点一次。

- [ ] **Step 5：提交错误处理**

```powershell
git add backend/knowflow/services/responses_protocol.py backend/knowflow/services/model_gateway.py tests/check_responses_protocol.py
git commit -m "fix: clarify model protocol failures"
```

## Task 5：在设置页提供清晰的协议选择和回填

**Files:**
- Modify: `frontend/react/src/data/settings.js`
- Modify: `frontend/react/src/components/SettingsPage.jsx`
- Modify: `frontend/react/src/components/ModelConfigForm.jsx`
- Modify: `frontend/react/src/components/ModelListPanel.jsx`
- Modify: `tests/check_frontend_model_settings_react.py`
- Modify: `tests/check_frontend_model_list_data_react.py`
- Modify: `tests/check_model_provider_presets.py`

- [ ] **Step 1：先扩展前端静态契约测试**

断言代码中存在以下完整数据流：

- `defaultModelFormValues.apiMode === "chat_completions"`。
- `formValuesFromPreset()`读取`preset.apiMode`并回退`chat_completions`。
- `formValuesFromModel()`读取`model.apiMode`并回退`chat_completions`。
- `payloadFromFormValues()`提交`apiMode`。
- `ModelConfigForm`含`name="apiMode"`的两个option，且仅聊天模型显示。
- `ModelListPanel`显示Chat Completions或Responses API标签。
- OpenAI三个聊天预设显式为`responses`；其他聊天预设没有被误改。

- [ ] **Step 2：运行前端契约测试，确认红灯**

```powershell
python tests/check_frontend_model_settings_react.py
python tests/check_frontend_model_list_data_react.py
python tests/check_model_provider_presets.py
```

Expected：失败于表单和预设缺少`apiMode`。

- [ ] **Step 3：贯通表单状态和payload**

在`SettingsPage.jsx`的默认值、预设值、编辑值和payload都加入：

```javascript
apiMode: preset.apiMode || "chat_completions"
```

编辑回填使用：

```javascript
apiMode: valueForInput(model.apiMode || "chat_completions")
```

提交使用：

```javascript
apiMode: formValues.modelType === "chat" ? formValues.apiMode : "chat_completions",
```

`handleFieldChange()`在模型类型切到embedding或rerank时同步把`apiMode`复位为`chat_completions`，防止隐藏控件保留非法组合。

- [ ] **Step 4：加入协议选择器、标签和预设默认值**

在“模型类型”相邻位置加入：

```jsx
{formValues.modelType === "chat" ? (
  <label>
    {"接口协议"}
    <select name={"apiMode"} value={formValues.apiMode} onChange={onFieldChange}>
      <option value={"chat_completions"}>{"Chat Completions"}</option>
      <option value={"responses"}>{"Responses API"}</option>
    </select>
  </label>
) : null}
```

模型列表只对聊天模型显示简短协议标签，不增加解释段落：

```javascript
const apiModeLabel = {
  chat_completions: "Chat Completions",
  responses: "Responses API",
};
```

OpenAI三个聊天预设加入`apiMode: "responses"`；向量预设和其他提供商保持兼容默认值。

- [ ] **Step 5：运行前端测试和生产构建**

```powershell
python tests/check_frontend_model_settings_react.py
python tests/check_frontend_model_list_data_react.py
python tests/check_model_provider_presets.py
npm run build --prefix frontend
```

Expected：脚本退出码0；Vite生产构建成功；设置页无React警告。

- [ ] **Step 6：提交前端选择器**

```powershell
git add frontend/react/src/data/settings.js frontend/react/src/components/SettingsPage.jsx frontend/react/src/components/ModelConfigForm.jsx frontend/react/src/components/ModelListPanel.jsx tests/check_frontend_model_settings_react.py tests/check_frontend_model_list_data_react.py tests/check_model_provider_presets.py
git commit -m "feat: select model API protocol"
```

## Task 6：文档、全量门禁和发布

**Files:**
- Modify: `README.md`
- Verify: `backend/.env.example`
- Verify: `.gitignore`
- Verify: all changed files

- [ ] **Step 1：更新用户文档**

在README模型配置章节写明：

- Chat Completions适合传统OpenAI兼容中转。
- Responses API必须由上游真实支持`POST /v1/responses`。
- 协议按每条模型配置保存，不会自动探测或失败降级。
- OpenAI聊天预设默认Responses，已有配置仍默认Chat Completions。
- Mem0的独立LLM配置不受此选择器影响。

确认该功能没有新增环境变量，因此`backend/.env.example`无需增加伪配置。

- [ ] **Step 2：运行全部Python检查，遇到首个失败立即停止修复**

```powershell
$checks = Get-ChildItem -LiteralPath tests -Filter 'check_*.py' | Sort-Object Name
foreach ($check in $checks) {
  Write-Host "RUN $($check.Name)"
  python $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "FAILED: $($check.Name)" }
}
```

Expected：全部检查通过；不得跳过失败项继续宣称完成。

- [ ] **Step 3：运行前端与diff门禁**

```powershell
npm ci --prefix frontend
npm audit --prefix frontend
npm run build --prefix frontend
git diff --check
```

Expected：依赖安装和构建成功；audit无已知漏洞；`git diff --check`无输出。

- [ ] **Step 4：检查敏感文件和生成物没有进入提交**

```powershell
git status --short
git ls-files backend/.env 'data/*.db' 'data/**/*.db' 'data/uploads/**' 'data/mem0/**' 'frontend/dist/**'
git diff --cached --name-only
git diff --cached | Select-String -Pattern 'sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*["''][^"'']+["'']' -CaseSensitive:$false
```

Expected：不跟踪`backend/.env`、数据库、上传文件、`data/mem0`、`frontend/dist`；暂存diff不含真实Key或Token。若正则仅命中测试占位符，逐条人工确认。

- [ ] **Step 5：提交文档和最终修正**

```powershell
git add README.md
git add -f docs/superpowers/plans/2026-07-30-responses-api-model-protocol.md
git status --short
git commit -m "docs: explain selectable model protocols"
```

若前序验证产生必要修正，将修正文件与对应测试一并加入本提交；不得加入构建产物或运行数据。

- [ ] **Step 6：推送并核对远端**

```powershell
git push origin main
git status -sb
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Expected：本地`main`与`origin/main`一致，工作树干净。

- [ ] **Step 7：生产验收清单**

部署到服务器后严格按以下顺序验收：

1. 新建Responses配置，保存、重新打开并确认仍选Responses API。
2. 连接测试只请求`/v1/responses`且成功文案标明Responses API。
3. 完成一次无工具问答。
4. 完成一次联网搜索，确认第二轮请求含同一`call_id`的`function_call_output`。
5. 完成一次MCP或Skill调用，确认trace最终收敛。
6. 切回旧Chat Completions配置，确认`/v1/chat/completions`仍正常。
7. 检查journal无schema迁移、Responses解析、工具调用、权限或敏感信息异常。

生产验收不得自动改协议、自动重试另一端点或回显请求头和Key。
