# Agent运行事件协议

Web、CLI/TUI和持久化运行订阅共享同一套Agent事件信封。后端是协议真源，客户端不得再根据执行引擎自行猜测事件语义。

## 稳定字段

每个公开Agent事件都包含：

- `schemaVersion`：当前为`1`。
- `eventName`：稳定的领域事件名，如`tool.started`、`step.failed`、`run.completed`。
- `eventId`、`occurredAt`：事件身份和UTC时间。
- `runId`，以及适用时的`stepId`、`toolCallId`。
- `category`、`phase`、`normalizedStatus`。
- 失败事件的`error`与`recoveryActions`。

旧`type`字段在迁移期保留，保证旧版Web和CLI仍可消费；新代码必须优先读取`eventName`。

## 事件族

- 运行：`run.started`、`run.updated`、`run.completed`、`run.cancelled`。
- 步骤：`step.started`、`step.updated`、`step.completed`、`step.failed`。
- 工具：`tool.started`、`tool.progress`、`tool.completed`、`tool.failed`。
- 审批：`approval.required`、`approval.resolved`。
- 记忆：`memory.started`、`memory.completed`、`memory.skipped`、`memory.failed`。
- 用量：`usage.updated`。
- 产物和错误：`artifact.created`、`artifact.updated`、`error.raised`。

协议归一化集中在`backend/knowflow/services/agent_event_protocol.py`。新增事件应先在这里定义语义，再分别补Web和TUI渲染，不得新增仅供单一客户端理解的同义事件。

## 持久化与重放

后端将关键事件追加写入`agent_run_event`，以`run_id + sequence`保证顺序和幂等。`message.delta`与`tool.progress`属于高频瞬时事件，不落盘；最终`message.completed`、步骤、工具结果、审批、记忆及运行终态会保留。

`GET /api/agent/runs/{runId}/events`先返回运行快照，再按序重放持久化事件，最后接入实时订阅。客户端可传`afterSequence`或标准`Last-Event-ID`继续缺失部分；SSE的`id`等于事件`sequence`。Web和TUI仍必须用`eventId`去重，不能假设网络只投递一次。

Web将事件归并为单一运行投影，初始POST流与恢复GET流不得分别维护状态逻辑。网络中断采用有上限的指数退避；认证、权限、参数等4xx业务错误不盲目重试。后端默认保留终态运行事件30天，每次清理至多处理100个运行；活动运行永不按时间清理，删除会话时立即删除对应事件。
