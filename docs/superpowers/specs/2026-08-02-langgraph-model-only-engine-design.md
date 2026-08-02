# LangGraph纯模型执行引擎设计

## 目标

完成LangGraph渐进迁移的第3阶段：新增一个可以完成普通模型问答的`LangGraphAgentEngine`，同时保留`CurrentAgentEngine`作为默认执行引擎。

本阶段只验证执行引擎边界、模型协议兼容性、流式输出和现有运行记录能否在LangGraph下继续工作。工具、MCP、Skills、审批、Mem0节点和checkpoint均不在本阶段接入。

## 已确认决策

- 使用LangGraph的Graph API和`StateGraph`；
- LangGraph只负责编排，不替换现有`ModelGateway`；
- 使用全局环境变量`KNOWFLOW_AGENT_ENGINE`选择执行引擎；
- 默认值继续为`current`；
- 只有显式配置`KNOWFLOW_AGENT_ENGINE=langgraph`时才启用新引擎；
- 不增加用户级灰度配置或前端选择器；
- 暂不使用checkpoint；
- 不改变聊天接口、SSE事件、消息表、运行表和前端协议。

## 方案选择

### 方案A：StateGraph包装现有ModelGateway

新增单节点图，模型节点通过LangGraph运行时上下文取得本次请求的模型配置、网关和回调，然后调用现有`ModelGateway.complete()`。

优点是保留现有Chat Completions、Responses API、用户模型选择、流式事件、取消处理和异常分类。图结构也能在后续阶段自然增加工具、审批和记忆节点。

采用此方案。

### 方案B：LangGraph Functional API

代码更短，但当前项目需要逐步增加清晰可见的节点和边。Functional API不如Graph API适合作为后续运行图和状态迁移的共同结构，不采用。

### 方案C：LangChain模型适配器

使用LangChain聊天模型替换现有模型网关。该方案会同时改动模型协议层和执行层，扩大回归范围，也可能破坏现有Responses API兼容逻辑，不采用。

## 依赖

后端固定使用`langgraph==1.2.9`。固定版本用于保证Windows本地环境、服务器虚拟环境和测试环境获得一致行为。

LangGraph可以脱离LangChain模型适配器使用，因此本阶段不引入LangChain聊天模型封装。模型调用继续使用KnowFlow AI已有实现。

## 架构

```text
聊天路由
  ↓
build_agent_engine(KNOWFLOW_AGENT_ENGINE)
  ├─ current   → CurrentAgentEngine → AgentRunner
  └─ langgraph → LangGraphAgentEngine
                    ↓
                 START
                    ↓
                 model节点
                    ↓
                  END
```

`AgentEngine`仍是路由依赖的唯一执行接口。路由不判断LangGraph节点，也不读取LangGraph内部状态。

## 组件职责

### `LangGraphAgentEngine`

- 实现现有`AgentEngine.run()`签名；
- 在构造时编译纯模型图；
- 将消息作为图状态传入；
- 将本次模型配置、网关、trace和回调作为运行时上下文传入；
- 将最终图状态转换为现有`AgentRunResult`；
- 始终返回空的工具执行记录。

### 图状态

图状态只保存执行过程中会变化的数据：

- `messages`：本次模型请求使用的消息副本；
- `answer`：最终可见回答。

图状态不保存API Key、Base URL、用户ID、回调函数、数据库连接或其他运行依赖。

### 运行时上下文

以下内容通过LangGraph的`context_schema`传入节点，不进入图状态：

- 现有模型配置；
- `_CancellationAwareGateway`包装后的模型网关；
- `AgentTraceRecorder`；
- 父步骤ID；
- `model_event_callback`。

这样可以避免后续加入checkpoint时误把密钥或进程内对象持久化。

### model节点

model节点执行以下步骤：

1. 记录现有格式的模型步骤trace，并标记`engineName=langgraph`；
2. 调用`gateway.complete(messages, config, tools=None, tool_choice=None)`；
3. 原样传递`model_event_callback`，保持增量文本事件；
4. 校验模型响应；
5. 将文本写入`answer`；
6. 将模型步骤标记为成功或失败。

## 数据流

```text
ChatRequest
→ extensions组装messages、chat_config、registry和trace
→ build_agent_engine()
→ LangGraphAgentEngine.run()
→ graph.invoke(state, context=runtime_context)
→ model节点调用现有ModelGateway
→ AgentRunResult(answer, executions=[], trace)
→ extensions保存assistant消息
→ 发送现有流式done事件
```

`registry`参数为兼容现有接口继续传入，但LangGraph纯模型引擎不得读取其schema或执行任何注册工具。

## 引擎选择与回退

`normalize_agent_engine_name()`只接受以下显式值：

- `current`；
- `langgraph`。

空值和未知值继续归一化为`current`，避免环境变量拼写错误影响生产启动。

当值明确为`langgraph`时：

- 必须构建`LangGraphAgentEngine`；
- LangGraph依赖缺失或图构建失败时必须抛出明确错误；
- 不允许静默切回`CurrentAgentEngine`；
- 不允许在一次运行中切换执行引擎。

切回`KNOWFLOW_AGENT_ENGINE=current`只影响后续新运行，不修改历史运行记录。

## 模型协议与流式输出

纯模型节点复用现有`ModelGateway`，因此协议选择仍由模型配置中的`api_mode`决定：

- `chat_completions`继续请求Chat Completions；
- `responses`继续请求Responses API；
- 模型名称、Base URL、API Key和用户默认模型选择保持原样；
- 流式增量文本继续通过现有回调进入SSE；
- LangGraph本阶段使用同步`invoke()`，不另建第二套流式协议。

## trace与前端兼容

LangGraph纯模型引擎继续生成现有`model`步骤，步骤名称、完成状态和公开摘要保持兼容。

允许增加的诊断字段只有：

```json
{
  "engineName": "langgraph"
}
```

不得改变：

- `agent_run`状态语义；
- `agent_run_step`现有字段；
- 流式`answer`、`done`和`error`事件结构；
- assistant消息保存格式；
- 前端运行面板需要的数据结构。

本阶段不要求前端展示执行引擎名称。

## 错误处理

### 模型请求失败

沿用现有异常传播、失败分类、trace失败状态和前端错误事件。LangGraph层不重试模型请求，也不改写上游错误。

### 空响应

模型没有返回非空文本时，抛出无效模型响应错误，不保存空assistant消息。

### 意外工具调用

即使模型返回了`tool_calls`，LangGraph纯模型引擎也不得执行。该运行以“纯模型模式不支持工具调用”的明确错误结束，避免测试阶段产生未审计副作用。

### 取消

继续依赖路由传入的`_CancellationAwareGateway`。模型调用前、流式回调期间和模型调用后均沿用现有取消检查。

### LangGraph依赖异常

仅当显式选择`langgraph`时加载LangGraph实现。依赖不可用时返回明确的引擎初始化错误；`current`模式不应因LangGraph导入失败而无法启动。

## 测试设计

### 单元测试

- 图包含`START → model → END`；
- 普通模型回答能转换为`AgentRunResult`；
- Chat Completions配置原样传给网关；
- Responses API配置原样传给网关；
- `model_event_callback`能够收到网关事件；
- trace包含`engineName=langgraph`；
- 返回空内容时失败；
- 返回`tool_calls`时失败且工具未执行；
- 取消异常能够透传；
- 工具执行记录始终为空。

### 引擎选择测试

- `current`构建`CurrentAgentEngine`；
- `langgraph`构建`LangGraphAgentEngine`；
- 大小写和首尾空白正确归一化；
- 未知值安全回退`current`；
- 选择`langgraph`但依赖初始化失败时不静默回退。

### 路由回归

- 现有聊天接口请求体和响应格式不变；
- 流式`answer`事件继续产生；
- `done`事件格式不变；
- assistant消息正常保存；
- 运行状态最终收敛；
- `current`模式下现有工具、MCP、Skills、审批和记忆测试全部保持通过。

### 全量门禁

- 全部`tests/check_*.py`通过；
- `frontend npm run build`通过；
- `git diff --check`通过；
- 不提交`.env`、数据库、上传文件、`frontend/dist`、`data`或密钥；
- `KNOWFLOW_AGENT_ENGINE=current`完整回归通过；
- `KNOWFLOW_AGENT_ENGINE=langgraph`纯模型专项测试通过。

## 成功标准

- 默认部署行为不变；
- 配置为`langgraph`后，普通连续问答可以完成；
- Chat Completions和Responses API模型均可运行；
- 前端无需修改即可显示增量回答和最终状态；
- LangGraph运行不会调用任何工具；
- 切回`current`后，现有工具、MCP、Skills、审批和Mem0行为不受影响。

## 非目标

- 不接入SQLite或其他checkpointer；
- 不实现服务重启后的图恢复；
- 不迁移`web_search`或任何MCP工具；
- 不迁移Skills和任务计划；
- 不迁移写入审批；
- 不迁移Mem0召回或整理；
- 不增加前端执行引擎选择器；
- 不增加用户级或会话级灰度；
- 不重构现有`ModelGateway`；
- 不删除`AgentRunner`。

## 后续阶段

本阶段通过后，第4阶段再为LangGraph加入SQLite checkpoint，并建立`run_id`与LangGraph`thread_id`的一一对应。任何持久化设计都必须继续保证运行时上下文中的模型密钥和进程内对象不进入checkpoint。

## 参考

- LangGraph官方概览：https://docs.langchain.com/oss/python/langgraph/overview
- LangGraph Graph API：https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph运行时上下文：https://docs.langchain.com/oss/python/concepts/context
- LangGraph PyPI：https://pypi.org/project/langgraph/
