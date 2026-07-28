# Agent细节体验与运行收尾设计

## 目标

修复四个会让用户误判系统状态的细节：Skill列表加载失败被显示成“没有Skill”、消息输入框缺少稳定的无障碍名称、任务步骤展开后可能没有任何反馈，以及持久化Agent运行的SSE连接关闭后没有明确收敛到终态。

## 范围

### Skill选择器

`ChatComposerForm`维护`idle`、`loading`、`ready`、`error`四种加载状态。首次打开选择器时进入加载态；请求成功后区分有结果和确实为空；请求失败时保留错误态并提供原地重试，不再把失败解释为需要安装Skill。

`SkillPicker`只负责展示状态和触发`onRetry`、`onManage`、`onSelect`，不自行请求数据。消息输入框增加稳定的“消息”无障碍名称、`aria-haspopup="listbox"`，列表同步暴露加载状态。

### 任务步骤反馈

步骤展开后始终渲染详情区域。有trace时沿用`AgentTraceView`；没有trace时显示“暂无执行记录”。这样视觉内容与`aria-expanded`保持一致，不改变步骤选择和自动跟随当前步骤的逻辑。

### SSE终态收敛

持久化运行的事件流收到内部`stream_closed`时，后端重新读取数据库快照：

- `completed`返回`done`事件并携带最新run；
- `cancelled`返回`cancelled`事件；
- `failed`或其他非活动终态返回`error`事件；
- 仍为活动态说明worker异常退出但状态尚未写回，先将run收敛为`failed`，再返回脱敏的通用`error`事件。

前端重连流程显式处理`error`与`cancelled`，清除活动运行标记，并把失败或取消状态反馈到现有消息区域。错误事件只暴露稳定错误码和通用文案，不下发异常栈。

## 边界与兼容性

- 不新增表或字段，不改变正常SSE事件名称。
- 不重放完整答案增量；重连后的最终正文仍从已保存的assistant消息恢复。
- 不调整Skill安装、启用和用户隔离规则。
- 不重做任务计划布局或视觉主题。

## 验证

- 增加前端静态/组件检查，覆盖Skill加载、失败重试、输入框ARIA和无trace步骤反馈。
- 增加Agent运行检查，模拟worker异常关闭，断言run最终为`failed`且SSE包含`error`；覆盖正常完成和取消事件。
- 运行全部`tests/check_*.py`、`npm run build`、`npm audit`和`git diff --check`。

