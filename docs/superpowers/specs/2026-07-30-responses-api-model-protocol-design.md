# 模型双协议与Responses API设计

## 目标

让每个用户在模型配置中明确选择`Chat Completions`或`Responses API`，并保证普通问答、联网搜索、MCP、Skill及连接测试都严格使用所选协议。旧配置继续使用Chat Completions，不产生行为变化。

## 范围

本次包含模型配置、数据库迁移、后端模型网关、Agent工具循环适配、设置页协议选择及相关测试。不迁移Mem0自身使用的LLM客户端，不接入OpenAI托管工具，不改变现有聊天记录存储方式。

## 方案选择

采用“每条模型配置保存协议，模型网关内部归一化”的方案：

- `chat_completions`继续调用`/chat/completions`。
- `responses`调用`/responses`。
- 两种上游响应均转换成现有Agent循环使用的`role`、`content`、`tool_calls`内部结构。

不采用自动探测或失败降级。自动探测可能产生重复请求、重复计费和非幂等工具执行，也无法可靠区分临时故障与协议不兼容。

## 配置模型

模型配置新增`apiMode`字段，对应数据库列`api_mode`：

| API值 | 前端文案 | 用途 |
|---|---|---|
| `chat_completions` | Chat Completions | 兼容现有OpenAI兼容接口 |
| `responses` | Responses API | 使用Responses协议的聊天模型 |

约束如下：

- 数据库默认值为`chat_completions`，已有记录迁移后保持原行为。
- 创建和更新接口只接受上述两个值；缺省时使用`chat_completions`。
- `apiMode`仅影响`chat`类型模型；向量与重排模型继续走各自原有接口。
- 模型配置响应必须返回`apiMode`，编辑表单重新打开时恢复已保存选择。
- OpenAI聊天预设默认`responses`；其他提供商聊天预设默认`chat_completions`；自定义配置由用户明确选择。

## 前端交互

设置页在“模型类型”旁增加“接口协议”下拉框：

- 聊天模型显示并允许选择两个协议。
- 向量或重排模型不显示该控件，同时提交`chat_completions`兼容值。
- 编辑既有配置时显示其持久化值；旧响应缺失该字段时显示Chat Completions。
- 模型卡片或详情显示协议标签，避免用户测试失败后才发现协议不匹配。
- 保存与连接测试期间沿用现有busy态，禁止重复提交。

## 后端网关

`ModelGateway.complete()`按`api_mode`分流，外部调用方保持不变。

### Chat Completions

保持现有端点、请求结构和返回解析，作为兼容路径及旧配置默认路径。

### Responses

请求规则：

- 端点为`/responses`。
- `model`保持用户配置值。
- 系统级消息合并到`instructions`，其余上下文转换为`input`Items。
- `maxTokens`映射为`max_output_tokens`。
- 温度和Top P仅在用户配置且目标协议允许时传递；上游明确拒绝时返回原始HTTP错误的脱敏摘要，不静默删除参数重试。
- 设置`store: false`，KnowFlow继续自行保存与裁剪会话上下文。

返回解析规则：

- 遍历`output[]`，而不是读取`choices[0].message`。
- 合并`message`中的`output_text`为最终文本。
- 将每个`function_call`转换为现有内部`tool_calls`结构。
- reasoning Item不是最终答案，不单独渲染；需要继续工具循环时随本轮输出一起回传。
- 没有文本且没有函数调用时，返回明确的无效模型响应错误。

## 工具调用转换

发送工具定义时，将Chat Completions格式：

```json
{"type":"function","function":{"name":"web_search","description":"...","parameters":{}}}
```

转换为Responses格式：

```json
{"type":"function","name":"web_search","description":"...","parameters":{},"strict":false}
```

模型返回的`function_call`按`call_id`、`name`、`arguments`归一化为现有`tool_calls`。Agent执行结束后，现有`role=tool`消息转换成：

```json
{"type":"function_call_output","call_id":"call_xxx","output":"..."}
```

每个工具结果必须与原函数调用使用相同`call_id`。多轮工具调用继续受现有最大轮数、审批、超时、错误回传和trace机制约束。

## 状态策略

首版采用本地管理的无状态Responses模式：

- 每次请求发送KnowFlow整理后的完整上下文。
- 不使用`previous_response_id`和Conversations API。
- `store: false`避免在上游额外持久化用户会话。
- reasoning及函数调用Items只在当前Agent运行的后续工具轮次中回传，不写入普通聊天消息正文。

这一策略优先保证多提供商兼容与用户数据边界；未来若引入上游状态链，必须作为独立功能设计。

## 数据库迁移

SQLite和MySQL的`model_config`均新增`api_mode`：

- SQLite：`TEXT NOT NULL DEFAULT 'chat_completions'`。
- MySQL：`VARCHAR(30) NOT NULL DEFAULT 'chat_completions'`。
- 启动迁移必须可重复执行，并为既有行回填默认值。
- 迁移不得改写API密钥、默认模型或用户归属。

## 错误处理

对用户返回可执行的中文错误，不暴露Key、Authorization头或完整上游响应：

- 所选接口不支持Responses API。
- Responses返回结构无效。
- 函数调用缺少`call_id`或名称。
- 模型没有返回文本或工具调用。
- 上游返回Chat Completions结构但配置选择了Responses。

协议失败不会自动切换接口。连接测试必须显示实际测试的协议，并严格调用对应端点。

## 测试与验收

自动化测试必须覆盖：

1. SQLite与MySQL新建表及旧表迁移。
2. 创建、读取、更新配置时`apiMode`完整往返，非法值返回400。
3. 前端创建、编辑、预设切换和旧数据默认行为。
4. Chat Completions文本与工具调用路径不回归。
5. Responses纯文本、单工具、多轮工具及工具失败路径。
6. `instructions`、`input`、`max_output_tokens`、`store: false`及函数定义转换。
7. `function_call_output`与`call_id`关联。
8. 连接测试按所选协议请求正确端点。
9. 错误内容脱敏。
10. 全部`tests/check_*.py`、前端生产构建、`git diff --check`和敏感文件检查。

生产验收顺序：

1. 新建Responses配置并设为默认，重新打开确认协议选择仍为Responses。
2. 连接测试确认请求`/v1/responses`。
3. 完成一次不调用工具的问答。
4. 完成一次联网搜索并验证第二轮模型请求和最终回答。
5. 完成一次MCP或Skill调用并验证trace收敛。
6. 切换回Chat Completions配置，验证原有模型正常。
7. 检查journal无schema、解析、工具调用或敏感信息异常。

## 完成标准

用户能在前端明确选择并持久化接口协议；所有聊天入口与连接测试遵守该选择；Responses的文本和工具循环均能结束并生成正常trace；旧模型配置无需编辑且行为不变。
