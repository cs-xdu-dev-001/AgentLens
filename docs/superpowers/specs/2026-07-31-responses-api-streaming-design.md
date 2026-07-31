# Responses API上游流式设计

## 目标

让选择`responses`协议的聊天模型真正使用上游SSE流。普通回答要实时到达前端，Agent工具调用要在参数完整后执行并继续下一轮流，连接检查也必须验证流式Responses链路。`chat_completions`保持现有行为。

## 当前问题

现有`ModelGateway.complete()`对`POST /responses`执行普通阻塞请求，请求体没有`stream: true`，随后一次性解析完整JSON。KnowFlow对浏览器暴露的SSE只是应用外层流，无法降低模型首字延迟，也不兼容只提供流式Responses的中转实现。

## 方案选择

采用“内部统一事件流＋最终消息聚合”：

- Responses请求固定加入`stream: true`。
- 独立协议模块将上游SSE转换为少量内部事件，不把厂商事件直接扩散到Agent和路由层。
- 同一事件流既能实时转发文本增量，也能聚合成现有`role/content/tool_calls/_response_items`消息结构。
- Agent循环仍以完整工具调用为执行边界；工具执行完成后，用已有上下文转换规则发起下一轮Responses流。

不引入OpenAI SDK。KnowFlow需要兼容OpenAI、NewAPI、OneAPI及其他实现Responses SSE的中转站，继续使用现有HTTP传输层更可控。

## 内部事件

协议层只向调用方暴露以下事件：

| 类型 | 数据 | 用途 |
|---|---|---|
| `text_delta` | `text` | 实时追加答案文本 |
| `output_item` | `item` | 保存message、reasoning及function_call Item |
| `tool_call_delta` | `item_id`、`call_id`、`name`、`arguments_delta` | 聚合函数名和JSON参数 |
| `completed` | `response` | 确认上游正常结束并补齐最终Items |
| `error` | `code`、`message` | 终止本轮并生成脱敏错误 |

未知事件忽略，不视为失败。事件缺少本类型必需字段、SSE JSON无效、连接在`response.completed`之前结束，均抛出`ResponsesProtocolError`。

## SSE解析

新增按字节块解析的SSE解码器：

- 支持一个事件跨多个网络块。
- 支持`\n\n`及`\r\n\r\n`事件边界。
- 合并同一事件的多个`data:`行。
- 忽略注释、空行和`[DONE]`。
- 只解析`data:`中的JSON，不信任`event:`名称；以JSON的`type`为准。
- 对响应体设置现有模型请求超时，不无限等待。

## Responses事件映射

需要处理的核心上游事件：

- `response.output_text.delta`：产生`text_delta`。
- `response.output_item.added`：记录初始Item；若为`function_call`，初始化工具调用聚合器。
- `response.function_call_arguments.delta`：按`item_id`追加参数片段。
- `response.function_call_arguments.done`：以最终参数覆盖或完成聚合。
- `response.output_item.done`：保存最终Item并补齐`call_id`、`name`、`arguments`。
- `response.completed`：读取最终Response，确认状态并产生`completed`。
- `response.failed`、`response.incomplete`、`error`：产生协议错误，不伪装完成。

聚合结束后仍返回现有内部消息结构：

```json
{
  "role": "assistant",
  "content": "完整文本",
  "tool_calls": [{
    "id": "call_x",
    "type": "function",
    "function": {
      "name": "web_search",
      "arguments": "{\"query\":\"...\"}"
    }
  }],
  "_response_items": []
}
```

纯文本轮次不必保存`_response_items`；存在reasoning、function_call或其他非message Item时继续保存，供同一次Agent运行的下一轮回放。

## 网关接口

`ModelGateway`增加Responses专用流式入口，返回Python迭代器：

```python
gateway.stream_complete(messages, config, tools=tools, tool_choice=tool_choice)
```

迭代器输出内部事件，最后一个`completed`事件携带聚合后的完整消息。`complete()`在`api_mode=responses`时消费该迭代器并返回最终消息，因此Mem0、连接测试及尚未接入增量的调用方仍可复用同一实现，不保留第二套非流式Responses代码。

Chat Completions继续走原有`complete()`分支。

## Agent与前端数据流

Agent运行时：

1. 发起Responses流。
2. 每个`text_delta`立即交给现有聊天SSE生成器。
3. 协议层同时聚合完整消息。
4. 若完整消息包含工具调用，Agent在参数JSON完整后执行工具。
5. 将assistant运行时Items和`function_call_output`加入工作上下文。
6. 发起下一轮Responses流，直到获得最终文本或达到工具轮数限制。

现有运行trace、工具审批、超时和错误记录继续生效。增量文本不逐片写数据库；仅在一轮完成后保存完整assistant消息，避免产生碎片记录。

浏览器取消请求时关闭上游Response和HTTP会话。已经持久化的工具结果不回滚；未完成的模型轮次标记中断。

## 连接检查

连接检查使用与真实聊天相同的流式Responses实现：

- 请求体必须包含`stream: true`。
- 至少收到一个有效输出事件。
- 必须收到`response.completed`。
- 完成事件中的最终消息必须含文本或工具调用。

HTTP 400等错误返回状态码和脱敏错误类型。不得自动切换到Chat Completions，也不得因为失败而删除参数重试。

## 错误与安全

- HTTP错误在读取有限长度的上游错误摘要后立即关闭响应。
- 错误摘要继续经过现有`_safe_error()`脱敏，禁止出现API Key、Authorization头、查询参数值或完整请求体。
- SSE单事件和累计缓冲区设置大小上限，防止异常中转站无限占用内存。
- 工具参数在`arguments.done`或`output_item.done`前不解析、不执行。
- 工具参数不是合法JSON时沿用现有工具失败回传，不执行目标工具。
- `response.failed`、`response.incomplete`和无完成事件断流都必须形成失败状态。

## 测试

自动化测试覆盖：

1. 请求体包含`stream: true`。
2. SSE事件跨块、多个`data:`行、CRLF和`[DONE]`。
3. 文本增量实时输出并聚合为完整消息。
4. 工具名称、`call_id`和参数增量正确聚合。
5. 工具成功、工具失败及第二轮Responses请求。
6. `response.failed`、流内`error`、非法JSON、无完成事件断流。
7. HTTP 400错误脱敏。
8. 连接检查完整消费流。
9. Chat Completions路径不回归。
10. 全部`tests/check_*.py`、前端生产构建、`git diff --check`和敏感文件检查。

## 完成标准

- Responses普通回答的文本增量实时出现在前端。
- Responses工具调用参数完整后只执行一次，后续轮次正常完成。
- 连接检查验证真实SSE链路。
- 断流和协议错误不会显示成功。
- Chat Completions、Mem0、联网搜索、MCP、Skill和现有运行流图不回归。
