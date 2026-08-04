# LangGraph Skills与任务计划

LangGraph执行器复用现有Skill和任务计划协议，不复制用户数据、不执行Skill脚本，也不改变前端API。Skill仍由`SkillActivationSession`负责用户隔离、依赖校验和`references/`只读边界；任务计划仍持久化到现有`agent_run`与`agent_run_step`表。

```mermaid
flowchart TD
    A[模型] --> B{需要Skill?}
    B -- 是 --> C[activate_skill]
    C --> D[保存Skill版本快照]
    D --> E[刷新LangGraph工具白名单]
    E --> F[read_skill_resource或业务工具]
    B -- 否 --> G{需要多步计划?}
    G -- 是 --> H[create_task_plan]
    H --> I[(持久化公开计划)]
    I --> J[LangGraph计划执行子图]
    J --> P[选择下一可执行步骤]
    P --> Q[Agent步骤子图]
    Q --> K{写工具?}
    K -- 是 --> L[interrupt审批]
    L --> M[从同一checkpoint恢复]
    K -- 否 --> N[继续执行]
    M --> N
    F --> A
    N --> R{还有步骤?}
    R -- 是 --> P
    R -- 否 --> O[完成并保存结果]
```

## checkpoint恢复

独立的`skill_snapshot`状态只保存Skill安装ID、slug、版本和内容哈希。恢复时重新从当前用户的安装记录解析Skill，并严格比对完整快照；Skill被禁用、依赖缺失或内容变化都会终止恢复，不会悄悄换用其他版本。恢复成功后才重新注册`read_skill_resource`，并移除一次性的`activate_skill`。

模型消息checkpoint会保留本轮执行所需的Skill指令和对话内容，因此checkpoint数据库属于敏感业务数据，必须与主数据库采用相同的访问控制、备份和销毁策略，不得公开或提交到Git。前端Trace和工具审计仍只输出脱敏摘要，不暴露Skill正文。

工具白名单在每个模型节点和工具节点前动态计算，因此Skill激活后新增的资源工具立即可见，恢复后也不会沿用旧进程里的可变注册表。`create_task_plan`成功后立即结束本轮Agent步骤子图，并丢弃同一模型响应中排在它后面的工具调用；计划执行子图再从数据库快照选择下一可执行步骤，避免`/plan`误执行或重复建计划。

计划执行子图只负责控制流，不复制数据库。`agent_run`与`agent_run_step`仍是运行状态的事实来源；每步开始、完成、失败和等待审批都先写入现有持久化存储。进程中断后重新进入计划子图时，会从最新数据库快照重建轻量图状态，而不是依赖一份可能过期的内存计划。

## 当前边界

- `scripts/`只保存供检查，不执行。
- Skill不能创建新工具、绕过MCP配置或跳过写操作审批。
- 公开计划的步骤选择与循环由LangGraph计划执行子图负责，每个步骤内部继续使用LangGraph Agent子图。
- 持久化运行协调器仍负责并发互斥、取消、事件发布和数据库状态转换；这些可靠性职责不搬进模型图。
- Mem0召回已是主图首个节点；同一run的计划步骤复用checkpoint中的召回快照。
- 回答后的Mem0提取仍由现有持久队列异步执行，不阻塞图和用户响应。
