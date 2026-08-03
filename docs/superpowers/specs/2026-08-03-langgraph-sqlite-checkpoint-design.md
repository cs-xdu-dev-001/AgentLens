# LangGraph SQLite checkpoint设计

## 目标

完成LangGraph渐进迁移的第4阶段：使用LangGraph官方SQLite checkpointer保存纯模型图的执行进度，建立现有`run_id`与LangGraph`thread_id`的一一对应，并在用户主动继续任务时从最近节点边界恢复。

本阶段只建设可靠的checkpoint底座，不在服务启动后自动扫描或续跑任务，不迁移工具、MCP、Skills、审批和Mem0节点。生产环境继续默认使用`CurrentAgentEngine`。

## 已确认决策

- 使用`langgraph-checkpoint-sqlite==3.1.0`；
- checkpoint使用独立SQLite文件，不写入现有`knowflow.db`；
- 默认路径为`data/langgraph/checkpoints.sqlite3`；
- `thread_id`直接使用现有`run_id`；
- 恢复只能由用户主动触发，服务启动时不自动续跑；
- 用户归属继续由现有`agent_run`记录验证；
- 删除聊天会话时同步删除所属checkpoint thread；
- 严格限制checkpoint反序列化，不允许pickle回退；
- 当前执行器仍是默认执行器，`current`模式不得创建checkpoint文件。

## 方案选择

### 方案A：独立官方SQLite checkpointer

使用LangGraph官方`SqliteSaver`，将checkpoint保存在独立文件中。该方案适合Windows本地单机版和当前单worker服务器，存储与业务数据库解耦，也便于备份、清理和以后迁移到Postgres。

采用此方案。

### 方案B：复用现有业务SQLite文件

将LangGraph表与KnowFlow AI业务表放入同一个数据库文件。虽然少一个文件，但会增加锁竞争、迁移和排障耦合，不采用。

### 方案C：直接使用Postgres checkpointer

适合多worker和多实例服务，但会增加Windows本地安装复杂度。等服务器扩展为多实例时再迁移，不在本阶段使用。

## 架构

```text
登录用户请求
   ↓
extensions校验user_id并创建agent_run
   ↓
得到durable_run_id
   ↓
AgentEngine.run(user_id, run_id, ...)
   ↓
LangGraph配置thread_id=run_id
   ↓
SqliteSaver
   ↓
data/langgraph/checkpoints.sqlite3
```

`AgentEngine.run()`增加必需的`user_id`和`run_id`参数。`CurrentAgentEngine`接收但不使用这两个参数，现有行为保持不变。`LangGraphAgentEngine`使用这两个参数配置checkpoint和运行身份。

所有恢复入口必须先使用`user_id + run_id`查询现有`agent_run`。查询失败返回404，checkpoint数据库本身不提供前端直连或不带用户校验的读取接口。

## 配置与生命周期

新增环境变量：

```dotenv
KNOWFLOW_LANGGRAPH_CHECKPOINT_DB=./data/langgraph/checkpoints.sqlite3
```

相对路径以项目目录为基准解析。只有显式启用`KNOWFLOW_AGENT_ENGINE=langgraph`并实际运行LangGraph时，才创建父目录和数据库文件。

当前路由会为每次执行构建一个带取消感知网关的执行引擎。`LangGraphAgentEngine`因此在一次`run()`生命周期内打开SQLite连接、使用`SqliteSaver`编译图、执行或恢复图，最后关闭连接。不同请求可以通过不同连接访问同一个SQLite文件；SQLite等待超时必须有限，应用层不做无限重试。

## 图状态与运行时上下文

checkpoint中的图状态只包含：

```text
schema_version
messages
answer
```

图状态必须保持为JSON兼容的字典、列表、字符串和基础数值。以下内容不得写入checkpoint：

- API Key；
- OAuth Token；
- Cookie和请求头；
- 模型配置完整对象；
- 数据库连接；
- trace对象和回调函数；
- 其他任意Python运行时对象。

`user_id`、模型配置、网关、trace和事件回调继续通过运行时上下文传入。`run_id`同时作为执行参数和LangGraph`thread_id`使用。

## 首次运行数据流

1. 路由验证登录用户并创建`agent_run`；
2. 路由将`user_id`和`durable_run_id`传给执行引擎；
3. LangGraph使用`{"configurable": {"thread_id": run_id}}`运行；
4. 官方checkpointer保存输入、节点边界和最终状态；
5. 模型回答继续按原流程保存到`chat_message`；
6. 现有trace、SSE和前端运行面板协议保持不变。

checkpoint不替代聊天数据库，也不承担前端展示职责。

## 手动恢复数据流

本阶段不自动恢复。服务重启后继续沿用现有逻辑，将未完成任务标记为已中断，由用户主动点击继续执行。

继续执行时：

1. 使用`user_id + run_id`读取`agent_run`并确认归属；
2. 使用相同`thread_id`读取最新checkpoint；
3. 如果还有待执行节点，使用空输入从最近checkpoint继续；
4. 如果图已经到达`END`，直接返回保存的最终结果，不重复调用模型；
5. 如果checkpoint不存在、损坏或无法读取，明确失败，不偷偷从头执行。

当前图只有一个`model`节点。如果服务在模型请求中途退出，恢复会从`model`节点开头重新请求一次模型。这可能增加一次模型费用，但不会重复工具副作用，因为本阶段仍不开放工具。已经完成的模型节点不得再次执行。

浏览器刷新且后端进程仍在运行时，继续使用现有SSE重连机制，不依赖checkpoint恢复。

## 安全

- 固定使用已修复旧版SQL注入问题的`langgraph-checkpoint-sqlite==3.1.0`；
- 使用`JsonPlusSerializer(allowed_msgpack_modules=None, pickle_fallback=False)`；
- 不接受来自用户的checkpoint metadata查询键；
- checkpoint路径不通过静态服务或API公开；
- Linux下父目录权限设为`750`，数据库文件权限设为`600`；
- Windows沿用当前用户目录访问控制；
- 日志只记录异常类型、公开错误码和`run_id`，不记录checkpoint正文或敏感配置；
- `data/`继续由Git忽略，数据库文件不得进入版本控制。

## 错误处理

- 显式选择LangGraph但依赖缺失或checkpoint初始化失败时，返回明确错误，不回退当前执行器；
- 路径不可创建、文件不可写、数据库锁定、数据库损坏和反序列化失败均使用公开错误码；
- checkpoint不存在时不自动创建一条伪恢复任务；
- 模型节点失败后保留最近checkpoint，允许用户主动继续；
- 完成状态的`next`为空，重复继续只返回已有结果；
- SQLite连接等待超时有限，不在应用层无限重试。

## 清理

完成任务后保留checkpoint，使其生命周期与聊天会话一致。本阶段不增加后台定时清理器。

删除会话时：

1. 验证会话属于当前用户；
2. 查询该会话的全部`run_id`；
3. 取消仍在运行的任务；
4. 调用官方`delete_thread(run_id)`删除每个checkpoint thread；
5. 再删除`agent_run`、消息和会话记录。

checkpoint删除失败时停止会话删除并返回错误。已经删除的thread可以安全重复删除，因此用户重试不会产生额外副作用。

## 测试设计

### checkpoint专项测试

- 新运行创建SQLite文件和官方checkpoint表；
- `thread_id`与现有`run_id`完全一致；
- checkpoint状态不包含API Key、OAuth Token、Cookie或模型配置完整对象；
- 模型节点首次失败后，用第二个引擎实例和同一SQLite文件模拟服务重启，继续后成功完成；
- 模型节点已经完成后再次继续，不重复调用模型；
- checkpoint不存在、损坏、只读或路径不可创建时明确失败；
- 严格反序列化拒绝未允许的Python类型。

### 用户隔离与清理测试

- 用户A不能读取或继续用户B的`run_id`；
- 删除会话后，对应checkpoint thread全部消失；
- checkpoint删除失败时，业务会话记录保持可重试状态。

### 兼容性测试

- `current`模式不创建checkpoint文件；
- 当前工具、MCP、Skills、审批和Mem0测试继续通过；
- Windows相对路径和Linux绝对路径都能解析；
- 现有SSE事件、消息保存和运行状态语义不变；
- 前端不需要修改即可继续工作。

### 全量门禁

- 全部`tests/check_*.py`通过；
- 前端`npm run build`通过；
- `git diff --check`通过；
- 新依赖没有版本冲突；
- 敏感信息扫描通过；
- `.env`、数据库、上传文件、`frontend/dist`和`data`未被Git跟踪。

## 成功标准

- checkpoint真实持久化到独立SQLite文件；
- 使用新引擎实例可以从最近节点边界继续；
- 已完成节点不会重复执行；
- 跨用户访问被拒绝；
- 删除会话会同步清理checkpoint；
- 默认执行器及现有全部能力无回归；
- 生产环境仍可保持`KNOWFLOW_AGENT_ENGINE=current`。

## 非目标

- 不在服务启动后自动扫描或续跑任务；
- 不实现模型流式内容中途续传；
- 不迁移任何工具、MCP、Skills或审批；
- 不迁移Mem0召回和整理；
- 不增加checkpoint前端页面；
- 不增加定时保留策略；
- 不引入Postgres或自定义checkpointer；
- 不删除`CurrentAgentEngine`或`AgentRunner`。

## 参考

- LangGraph persistence：https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph interrupts：https://docs.langchain.com/oss/python/langgraph/interrupts
- LangGraph SQLite checkpointer：https://pypi.org/project/langgraph-checkpoint-sqlite/
- LangGraph SQLite安全公告：https://github.com/langchain-ai/langgraph/security/advisories/GHSA-9rwj-6rc7-p77c
