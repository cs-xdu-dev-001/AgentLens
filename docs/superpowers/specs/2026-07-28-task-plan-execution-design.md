# 任务计划与执行状态设计

## 目标

为KnowFlow AI增加可持久化、可恢复、可停止的任务计划，让多步骤Agent任务不再只是一次聊天请求中的临时trace。

本期目标：

- 简单问答继续直接回答，不增加计划负担。
- 多步骤任务由模型自主生成计划，用户也可通过`/plan`强制只规划。
- 计划和执行状态实时持久化，刷新页面后可以恢复查看并重新订阅。
- 服务重启后将未完成任务标记为已中断，由用户手动继续。
- 前端按计划步骤展示进度，当前步骤点亮；模型、工具、MCP、Skill和审批作为步骤详情。
- 延续现有用户隔离、审批、trace脱敏和工具审计能力。

本期不做：

- 独立任务队列、Redis或后台worker。
- 服务重启后的自动续跑。
- DAG、并行步骤或跨任务依赖。
- 展示模型思维链。
- 对结果不明确的写操作进行自动重放。

## 已确认的产品规则

### 计划触发

- 普通简单问答不生成计划。
- 自动模式下，模型可以为多步骤任务调用内部`create_task_plan`工具。
- 用户输入`/plan`时强制生成计划，但不立即执行。
- Skill可以声明任务必须先生成计划。

### 执行时机

- 自动模式生成计划后立即执行。
- `/plan`模式生成计划后等待用户点击“开始执行”。
- 只读工具直接运行。
- 写入、删除、发送等高风险工具继续使用现有审批机制。
- 用户可以随时停止任务。

### 恢复边界

- 页面刷新后从数据库恢复任务、计划和脱敏trace。
- 若原服务进程中的任务仍在执行，前端重新订阅实时事件。
- 服务重启后将残留的活动任务标记为`interrupted`。
- 用户手动继续时，从第一个未完成步骤开始。
- 已完成步骤不重复执行；结果不明确的写操作必须再次确认。

## 方案选择

采用“持久化任务＋进程内协调器”。

未采用只扩展trace的方案，因为trace只能描述过程，不能可靠支持开始、停止、继续和状态迁移。未采用独立后台任务系统，因为当前阶段不需要Redis、租约、心跳和分布式幂等带来的部署复杂度。

新增轻量`RunCoordinator`管理当前服务进程内的活动任务。它不承担最终事实存储；任务事实始终以数据库状态为准。后续如需迁移到独立worker，可以复用任务表、状态机和执行器接口。

## 数据模型

### agent_run

一行代表一次完整Agent任务。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `id` | `run_`前缀的公开任务ID |
| `user_id` | 所属用户 |
| `session_id` | 所属聊天会话 |
| `user_message_id` | 触发任务的用户消息 |
| `assistant_message_id` | 最终回答消息，可空 |
| `goal_summary` | 脱敏后的公开目标摘要 |
| `trigger_mode` | `auto`、`plan_only`或`skill_required` |
| `status` | 任务状态 |
| `current_step_id` | 当前计划步骤，可空 |
| `trace_json` | 最新脱敏trace快照 |
| `version` | 乐观并发版本 |
| `started_at` | 开始时间 |
| `finished_at` | 结束时间，可空 |
| `created_at` | 创建时间 |
| `updated_at` | 最近更新时间 |

任务状态：

- `planning`
- `waiting_start`
- `running`
- `waiting_approval`
- `interrupted`
- `completed`
- `failed`
- `cancelled`

合法主路径：

```text
planning → waiting_start → running → completed
     └───────────────→ running
running → waiting_approval → running
running → interrupted → running
running → failed
running → cancelled
```

### agent_run_step

一行代表一个用户可见的计划步骤。

建议字段：

| 字段 | 含义 |
| --- | --- |
| `id` | 步骤ID |
| `run_id` | 所属任务 |
| `position` | 线性顺序 |
| `title` | 公开步骤标题 |
| `status` | 步骤状态 |
| `kind` | `reasoning`、`tool`、`mcp`、`skill`或`answer` |
| `tool_name` | 预期或实际工具名，可空 |
| `input_summary` | 脱敏公开输入摘要 |
| `output_summary` | 脱敏公开结果摘要 |
| `error_code` | 稳定错误码，可空 |
| `attempt_count` | 尝试次数 |
| `started_at` | 开始时间，可空 |
| `finished_at` | 结束时间，可空 |
| `created_at` | 创建时间 |
| `updated_at` | 最近更新时间 |

步骤状态：

- `pending`
- `running`
- `waiting_approval`
- `completed`
- `failed`
- `skipped`
- `cancelled`

第一版计划限制为2～8个线性步骤，标题长度和摘要长度均设上限。

### 现有表关联

`agent_tool_call`增加：

- `run_id`
- `run_step_id`

实际工具调用因此可以追溯到任务和计划步骤。现有`chat_message.trace_json`继续保存最终消息的trace快照；任务执行期间的最新快照保存在`agent_run.trace_json`。

SQLite和MySQL建表、迁移及索引必须同步更新。所有查询必须通过当前用户校验任务归属。

## 计划生成

运行时注册内部工具`create_task_plan`，参数只允许：

- 2～8个步骤。
- 每步包含短标题和受限类型。
- 不接受用户ID、任务状态、工具凭据或任意数据库字段。

自动模式通过系统指令告诉模型：只有明显需要多个动作的任务才调用该工具。`/plan`模式强制规划。计划生成失败时任务进入`failed`，向用户提供重试，不静默退化为无计划执行。

模型提交的是公开任务动作，不是思维过程。计划内容经过现有trace脱敏规则和长度限制后才落库。

## 执行流程

```text
保存用户消息
→ 创建agent_run
→ 生成并持久化计划
→ 自动执行或等待开始
→ 逐步执行并持久化状态
→ 广播SSE事件
→ 保存最终assistant消息
→ 回填assistant_message_id和工具调用关联
→ 完成任务
```

每次状态变化遵循“先提交数据库，再广播事件”。前端状态不能成为任务事实来源。

`RunCoordinator`负责：

- 保证同一`run_id`只有一个执行实例。
- 保存活动任务的取消信号和SSE订阅者。
- 在模型调用、工具调用和步骤边界检查取消信号。
- 将执行器事件广播给当前订阅者。
- 在客户端刷新后允许重新订阅。

同一会话同一时间只允许一个活动任务，重复启动返回`409`。停止为协作式取消：正在等待的外部HTTP调用依赖既有超时返回，随后不再执行后续步骤。

继续执行使用已完成步骤的公开结果和必要上下文，从第一个未完成步骤开始。已完成步骤不可被普通恢复流程改回待执行。

## API

保留现有`POST /api/chat/stream`作为首次聊天入口，并在SSE中增加任务事件。

新增：

```text
GET  /api/agent/runs/{run_id}
GET  /api/agent/runs/{run_id}/events
POST /api/agent/runs/{run_id}/start
POST /api/agent/runs/{run_id}/resume
POST /api/agent/runs/{run_id}/cancel
```

建议SSE事件：

- `run_snapshot`
- `plan_created`
- `run_updated`
- `step_updated`
- `trace`
- `approval_required`
- `approval_resolved`
- `answer`
- `done`
- `error`

重新订阅时，服务先发送完整`run_snapshot`，再发送后续实时事件。第一版不要求持久化逐条事件日志，数据库快照负责恢复，实时广播负责低延迟更新。

所有任务接口必须同时校验`run_id`和当前用户。不存在和越权统一返回`404`。

## 前端交互

不新增独立任务页面，沿用现有聊天消息和“本次运行”抽屉。

### 聊天区

- Agent消息区域显示紧凑任务条，例如`3/6 · 正在检索资料`。
- 执行中发送按钮切换为停止按钮。
- 刷新恢复后显示“任务仍在执行”或“任务已中断，可继续”。
- `/plan`完成后显示计划卡片，仅保留“开始执行”和“重新规划”。
- 简单问答不显示空计划。

### 运行抽屉

计划步骤作为主层级：

```text
● 理解目标             已完成
│
● 搜索Notion资料       已完成
│  └ Notion MCP · 867ms
│
◉ 联网补充来源         执行中
│  └ web_search
│
○ 整理结果             等待
│
○ 生成最终回答         等待
```

- 当前步骤点亮并使用克制的动态反馈。
- 点击步骤后展开模型、工具、MCP、Skill和审批trace。
- trace不再作为平铺主列表。
- 失败或中断时显示直接操作，如“继续”或“重试”。
- 移动端使用全屏抽屉，信息结构不变。
- 状态不能只依赖颜色表达。

## 异常与安全

- SSE断开不修改任务事实。
- 模型或工具超时只终止当前步骤，保留已完成结果。
- 服务启动时将残留的`planning`、`running`、`waiting_approval`任务转为`interrupted`。
- 审批仍在原进程有效时可以继续；服务重启后的等待审批不恢复为原审批请求。
- 不自动重放结果不明确的写操作。
- 计划、步骤、trace和SSE均使用统一脱敏函数。
- API Key、OAuth Token、Authorization、Cookie、请求头和Secret不得进入公开状态。
- 工具输出不能直接修改任务状态，所有状态迁移由执行器控制。
- 状态更新使用版本条件或等价原子校验，防止重复启动。

## 测试与验收

### 后端

- 简单问答不创建计划。
- 自动模式创建计划并按顺序执行。
- `/plan`进入`waiting_start`，启动后才执行。
- 状态机拒绝非法迁移。
- 同一任务不能重复启动。
- 停止、失败、审批拒绝、审批超时和继续状态正确。
- 已完成步骤在恢复时不重复执行。
- 服务启动恢复将活动任务标记为`interrupted`。
- 工具调用正确关联`run_id`和`run_step_id`。
- SQLite和MySQL schema一致。
- 多用户越权读取、开始、继续和停止均返回`404`。
- 计划、trace和SSE不包含敏感信息。

### 前端

- 任务条、计划列表和当前步骤实时更新。
- `/plan`卡片可以开始和重新规划。
- 停止按钮状态正确。
- 刷新后可以恢复快照并重新订阅。
- 中断、失败、审批等待和完成状态清晰。
- 步骤展开后展示对应trace。
- 桌面端、窄屏和键盘操作可用。

### 发布验证

- 运行全部`tests/check_*.py`。
- 运行`frontend`的`npm run build`。
- 运行`npm audit`。
- 运行`git diff --check`。
- 扫描`.env`、数据库、上传文件、构建产物、Token和Key，确认不进入提交。

## 后续演进

任务表、状态机和执行器接口稳定后，可以逐步增加：

- 独立worker和任务队列。
- 心跳、租约和自动故障恢复。
- 并行步骤和DAG。
- 任务历史页和跨会话任务中心。
- 更细的步骤级重试、编辑和重新规划。

这些能力不进入本期实现。
