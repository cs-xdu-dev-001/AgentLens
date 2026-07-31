# Agent Run Inspector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将右侧运行记录改成可原地展开的渐进式时间线，并安全展示模型、工具、MCP、记忆和Skill的必要公开信息。

**Architecture:** 后端只补充模型名称与接口协议两个白名单字段；前端把trace到人话展示模型的转换提取为纯函数，把交互详情拆成独立组件。`AgentTraceView`只管理时间线层级和选中状态，重试继续复用现有记忆API与消息重试事件。

**Tech Stack:** FastAPI、Python、React、Vite、原生CustomEvent、现有`tests/check_*.py`契约测试。

---

## 文件结构

- Create: `frontend/react/src/components/agentTracePresentation.js`：纯函数，负责安全标题、原因、字段、复制文本和可用操作。
- Create: `frontend/react/src/components/AgentTraceStepDetail.jsx`：渲染展开详情，执行复制、页面跳转和安全重试。
- Modify: `frontend/react/src/components/AgentTraceView.jsx`：改成单节点原地展开并管理用户选择。
- Modify: `frontend/react/src/components/AgentTaskPlan.jsx`：向嵌套时间线传递`messageId`。
- Modify: `frontend/react/src/components/ChatEvidenceDrawer.jsx`：向时间线传递`messageId`。
- Modify: `frontend/react/src/controller/memoryActivity.js`：统一发布记忆活动更新事件。
- Modify: `frontend/react/src/components/ChatMessages.jsx`：复用记忆活动发布函数。
- Modify: `frontend/react/src/styles.css`与`frontend/styles.css`：渐进式时间线、详情字段、操作按钮及窄屏样式。
- Modify: `backend/knowflow/services/agent_loop.py`：模型trace白名单补充`modelName`与`apiMode`。
- Modify: `tests/check_frontend_agent_trace_react.py`：验证纯展示函数、安全白名单、原地展开和交互事件。
- Modify: `tests/check_agent_trace.py`：验证模型公开details，不泄露配置中的密钥字段。

### Task 1: 写出失败的前端运行栏契约

- [ ] **Step 1: 在`tests/check_frontend_agent_trace_react.py`加入新文件与交互断言**

断言必须覆盖：

```python
require(
    "frontend/react/src/components/AgentTraceView.jsx",
    "AgentTraceStepDetail",
    "inline trace detail component",
)
require(view, "aria-expanded={expanded}", "node expansion state")
for token in (
    "为什么执行",
    "复制详情",
    "重新运行本轮",
    "管理长期记忆",
):
    require(
        "frontend/react/src/components/AgentTraceStepDetail.jsx",
        token,
        f"interactive detail {token}",
    )
for token in (
    "traceStepReason",
    "traceStepFields",
    "traceCopyText",
):
    require(
        "frontend/react/src/components/agentTracePresentation.js",
        token,
        f"trace presentation helper {token}",
    )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_frontend_agent_trace_react.py`

Expected: FAIL，缺少`AgentTraceStepDetail.jsx`或`agentTracePresentation.js`。

### Task 2: 提取安全展示纯函数

- [ ] **Step 1: 创建`agentTracePresentation.js`**

文件导出以下稳定接口：`safeText(value, fallback)`只允许字符串、数字和布尔值；`normalizeTraceStatus(status)`把`completed`映射为`success`、把`error`映射为`failed`；`traceStepTitle(step)`迁移现有全部人话标题分支；`traceStepReason(step)`按name/kind返回固定说明；`traceStepFields(step)`返回`[{ label, value }]`白名单字段；`traceMemoryItems(step)`只返回`action/content`；`traceCopyText(step)`只拼接上述公开信息；`traceStepTarget(step)`只返回`memory`、`skills`、`tools`或空字符串。

`traceStepFields()`只从`inputSummary`、`outputSummary`和以下details键读取数据：

```javascript
const SAFE_DETAIL_KEYS = new Set([
  "apiMode",
  "attemptCount",
  "displayName",
  "modelName",
  "operationId",
  "requiredMcp",
  "requiredTools",
  "risk",
  "serverName",
  "sourceKind",
  "toolName",
  "version",
]);
```

不得读取或序列化整个`details`对象。

- [ ] **Step 2: 把`AgentTraceView.jsx`原有标签和展示辅助函数迁移到纯函数文件**

组件只保留层级计算和React状态，原有`traceStepTitle`继续从新文件re-export，保证`AgentTraceStrip`兼容。

- [ ] **Step 3: 运行前端trace测试**

Run: `py -3.13 tests/check_frontend_agent_trace_react.py`

Expected: 旧fixture通过，新增组件断言仍失败。

### Task 3: 实现节点详情与安全操作

- [ ] **Step 1: 在`memoryActivity.js`导出统一发布函数**

```javascript
export function publishMemoryActivity(messageId, memoryActivity) {
  const detail = { messageId, memoryActivity };
  window.dispatchEvent(new CustomEvent(
    "knowflow:react-message-memory-activity",
    { detail },
  ));
  window.dispatchEvent(new CustomEvent(
    "knowflow:react-memory-activity-updated",
    { detail },
  ));
}
```

- [ ] **Step 2: 让`ChatMessages.jsx`复用`publishMemoryActivity()`**

保留组件本地`setActivity()`，删除重复的两次`dispatchEvent`。

- [ ] **Step 3: 创建`AgentTraceStepDetail.jsx`**

组件签名：

```jsx
export function AgentTraceStepDetail({ step, messageId = "" })
```

行为：

- 调用`traceStepReason()`、`traceStepFields()`、`traceMemoryItems()`；
- `navigator.clipboard.writeText(traceCopyText(step))`成功后Toast“已复制步骤详情”；
- memory/skills/tools通过`knowflow:react-page-activated`跳转；
- 失败的`memory_write`调用`memoryApi.retryOperation(operationId)`并发布活动；
- 其他失败节点派发`knowflow:react-message-retry`，detail携带`messageId`；
- 请求失败使用`notifyError()`。

- [ ] **Step 4: 运行定向测试**

Run:

```powershell
py -3.13 tests/check_frontend_agent_trace_react.py
py -3.13 tests/check_frontend_memory_activity_react.py
```

Expected: PASS。

### Task 4: 改造为渐进式时间线

- [ ] **Step 1: 修改`AgentTraceView.jsx`选中规则**

新增`userSelectedRef`。自动选择优先级为等待确认、失败、运行中、最后节点；用户点击后不再被普通trace刷新抢占。再次点击已展开节点时清空`selectedId`。

- [ ] **Step 2: 在每个`.agent-trace-row`内部渲染详情**

结构必须为：

```jsx
<div className={"agent-trace-row"}>
  <button
    aria-expanded={expanded}
    aria-controls={detailId}
    onClick={() => toggleStep(step.stepId)}
  >
    <span className={"agent-trace-node-dot"} aria-hidden={"true"} />
    <span className={"agent-trace-kind"}>{traceKindLabel(step.kind)}</span>
    <span className={"agent-trace-node-copy"}>
      <strong>{traceStepTitle(step)}</strong>
      <small>{traceStatusLabel(step.status)}</small>
    </span>
    <span className={"agent-trace-node-time"}>
      {traceDurationLabel(step.durationMs)}
    </span>
  </button>
  {expanded ? (
    <AgentTraceStepDetail
      id={detailId}
      step={step}
      messageId={messageId}
    />
  ) : null}
</div>
```

删除时间线末尾独立的`.agent-trace-detail`。

- [ ] **Step 3: 传递messageId**

`ChatEvidenceDrawer`、`AgentTaskPlan`两处调用均传入`messageId`。

- [ ] **Step 4: 运行相关契约测试**

Run:

```powershell
py -3.13 tests/check_frontend_agent_trace_react.py
py -3.13 tests/check_frontend_agent_task_plan.py
py -3.13 tests/check_frontend_memory_activity_react.py
```

Expected: PASS。

### Task 5: 补充模型公开trace信息

- [ ] **Step 1: 在`tests/check_agent_trace.py`写失败断言**

AgentRunner完成模型调用后，模型步骤details应等于：

```python
{
    "modelName": "gpt-test",
    "apiMode": "responses",
}
```

并断言`api_key_cipher`、`base_url`、headers均不进入snapshot。

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_agent_trace.py`

Expected: FAIL，模型步骤details为空。

- [ ] **Step 3: 最小修改`agent_loop.py`**

模型步骤使用：

```python
details={
    "modelName": str(config.get("model_name") or ""),
    "apiMode": str(
        config.get("api_mode") or "chat_completions"
    ),
},
```

不传递整个config。

- [ ] **Step 4: 运行Agent定向测试**

Run:

```powershell
py -3.13 tests/check_agent_trace.py
py -3.13 tests/check_agent_loop.py
py -3.13 tests/check_responses_streaming.py
```

Expected: PASS。

### Task 6: 视觉样式和响应式

- [ ] **Step 1: 修改源样式`frontend/styles.css`**

实现：

- 行内详情与节点共享边框；
- 展开箭头旋转；
- 原因、字段、记忆列表和操作按钮层级；
- 失败与等待节点强调；
- `overflow-wrap:anywhere`；
- 侧栏窄屏不横向滚动；
- `prefers-reduced-motion`关闭旋转动画。

- [ ] **Step 2: 同步React样式**

Run: `npm run sync:assets`

Expected: `frontend/react/src/styles.css`与源样式一致。

- [ ] **Step 3: 构建前端**

Run: `npm run build`

Expected: Vite生产构建成功。

### Task 7: 完整验证与发布

- [ ] **Step 1: 运行全部检查**

Run: 按文件名顺序执行全部`tests/check_*.py`。

Expected: 114项及新增检查全部通过。

- [ ] **Step 2: 运行发布卫生**

Run:

```powershell
git diff --check
git status -sb
npm audit --audit-level=high
```

Expected: 无格式错误、无高危漏洞；`.codegraph/`不提交。

- [ ] **Step 3: 提交并推送**

```powershell
git add backend/knowflow/services/agent_loop.py `
  frontend/styles.css `
  frontend/react/src/styles.css `
  frontend/react/src/components/AgentTraceView.jsx `
  frontend/react/src/components/AgentTraceStepDetail.jsx `
  frontend/react/src/components/agentTracePresentation.js `
  frontend/react/src/components/AgentTaskPlan.jsx `
  frontend/react/src/components/ChatEvidenceDrawer.jsx `
  frontend/react/src/components/ChatMessages.jsx `
  frontend/react/src/controller/memoryActivity.js `
  tests/check_agent_trace.py `
  tests/check_frontend_agent_trace_react.py
git commit -m "feat: make Agent run trace interactive"
git push origin main
```

Expected: 本地HEAD与`origin/main`一致。
