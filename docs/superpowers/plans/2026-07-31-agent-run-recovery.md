# Agent Run Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有Agent运行状态机上增加脱敏失败分类和右侧运行栏恢复操作，不重复实现执行器。

**Architecture:** 后端新增纯函数失败分类器，执行路径保存具体错误码和固定公开摘要，`AgentRunStore`从持久化步骤或trace派生`failure`。前端新增`AgentRecoveryPanel`，复用既有`resume`和页面导航；整轮重启由后端复制已持久化请求创建替代run，刷新后仍可用。

**Tech Stack:** Python 3.10+、FastAPI、SQLAlchemy、React 18、SSE、项目现有`tests/check_*.py`契约测试。

---

## 文件结构

- Create: `backend/knowflow/services/agent_failure.py`，失败分类和快照恢复元数据。
- Modify: `backend/knowflow/services/agent_run_store.py`，在run快照中派生`failure`。
- Modify: `backend/knowflow/routers/agent_runs.py`，提供用户隔离的整轮重启接口。
- Modify: `backend/knowflow/routers/extensions.py`，保留具体步骤错误并写入公开摘要。
- Create: `frontend/react/src/components/AgentRecoveryPanel.jsx`，失败原因和恢复动作。
- Modify: `frontend/react/src/components/ChatEvidenceDrawer.jsx`，挂载恢复面板。
- Modify: `frontend/react/src/components/AgentTaskPlan.jsx`，避免重复恢复按钮。
- Modify: `frontend/react/src/components/agentTracePresentation.js`，失败输出显示为失败原因。
- Modify: `frontend/styles.css`和同步目标样式，增加紧凑恢复面板样式。
- Create: `tests/check_agent_failure_recovery.py`，后端分类、快照和执行契约。
- Create: `tests/check_frontend_agent_recovery.py`，前端交互契约。

### Task 1: 后端失败分类器

- [ ] **Step 1: 写失败测试**

创建`tests/check_agent_failure_recovery.py`，直接断言：

```python
assert classify_agent_failure(code="web_search_timeout")["retryable"] is True
assert classify_agent_failure(code="resource_unauthorized")["target"] == "tools"
assert classify_agent_failure(code="invalid_api_key")["target"] == "settings"
assert recovery_from_snapshot("completed", [], []) is None
```

- [ ] **Step 2: 验证测试因模块缺失而失败**

Run: `py -3.13 tests/check_agent_failure_recovery.py`
Expected: FAIL，缺少`agent_failure`模块。

- [ ] **Step 3: 实现纯函数分类器**

`agent_failure.py`提供：

```python
def classify_agent_failure(error=None, *, code=None, source="agent") -> dict[str, object]:
    normalized = normalize_failure_code(error, code, source)
    policy = FAILURE_POLICIES.get(normalized, FAILURE_POLICIES["agent_run_failed"])
    return {"code": normalized, **policy}

def recovery_from_snapshot(status, steps, trace) -> dict[str, object] | None:
    if status not in {"failed", "interrupted", "cancelled"}:
        return None
    candidate = latest_failure(steps, trace, status)
    return classify_agent_failure(code=candidate["code"], source=candidate["source"])
```

只返回固定英文公开摘要，不返回`str(error)`。

- [ ] **Step 4: 验证分类器测试通过**

Run: `py -3.13 tests/check_agent_failure_recovery.py`
Expected: PASS。

### Task 2: 持久化具体错误与恢复快照

- [ ] **Step 1: 扩展失败测试**

在测试中建立内存数据库run，失败步骤使用`upstream_timeout`和公开摘要，断言：

```python
snapshot["failure"] == {
    "code": "upstream_timeout",
    "summary": "The upstream service timed out.",
    "retryable": True,
    "target": None,
}
```

并静态检查`extensions.py`不再用`agent_step_failed`覆盖`failed_execution.error_code`。

- [ ] **Step 2: 验证测试因快照缺少failure而失败**

Run: `py -3.13 tests/check_agent_failure_recovery.py`
Expected: FAIL，快照缺少`failure`。

- [ ] **Step 3: 更新store和执行路径**

在`AgentRunStore._normalize_run`中调用`recovery_from_snapshot`。在`execute_agent_chat`中保存分类后的`errorCode`和固定`outputSummary`，根trace同步保存同一信息。

- [ ] **Step 4: 验证后端相关检查**

Run: `py -3.13 tests/check_agent_failure_recovery.py && py -3.13 tests/check_agent_run_store.py && py -3.13 tests/check_agent_task_execution.py`
Expected: PASS。

### Task 3: 前端恢复面板

- [ ] **Step 1: 写前端失败契约**

创建`tests/check_frontend_agent_recovery.py`，要求：

```python
require("AgentRecoveryPanel.jsx", "从失败步骤继续")
require("AgentRecoveryPanel.jsx", "重新运行本轮")
require("AgentRecoveryPanel.jsx", "knowflow:react-agent-run-action")
require("AgentRecoveryPanel.jsx", 'action: "restart"')
require("AgentRecoveryPanel.jsx", "knowflow:react-page-activated")
```

- [ ] **Step 2: 验证测试因组件缺失而失败**

Run: `py -3.13 tests/check_frontend_agent_recovery.py`
Expected: FAIL，组件不存在。

- [ ] **Step 3: 实现恢复组件**

组件接收`run`和`messageId`，只在失败、已中断或已取消时渲染。计划失败主操作派发`resume`；“重新运行本轮”调用后端`restart`，不依赖页面内存。目标按钮只导航，不自动更改配置。

- [ ] **Step 4: 接入右侧运行栏**

在`ChatEvidenceDrawer`的过程页首部挂载恢复面板；从`AgentTaskPlan`移除重复的失败恢复按钮，保留开始、重新规划和停止。

- [ ] **Step 5: 验证前端契约**

Run: `py -3.13 tests/check_frontend_agent_recovery.py && py -3.13 tests/check_frontend_agent_task_plan.py && py -3.13 tests/check_frontend_agent_trace_react.py`
Expected: PASS。

### Task 4: 样式和信息层级

- [ ] **Step 1: 为恢复面板补CSS契约**

要求存在`.agent-recovery-panel`、`.agent-recovery-actions`、失败状态边框和520px按钮换行规则。

- [ ] **Step 2: 验证CSS契约失败**

Run: `py -3.13 tests/check_frontend_agent_recovery.py`
Expected: FAIL，缺少恢复样式。

- [ ] **Step 3: 写源样式并同步**

只编辑`frontend/styles.css`，使用1px边框、正文级字号和现有危险/主色token；运行`npm --prefix frontend run sync:assets`生成React样式副本。

- [ ] **Step 4: 构建验证**

Run: `npm --prefix frontend run build`
Expected: Vite构建成功。

### Task 5: 发布门禁与Git同步

- [ ] **Step 1: 运行全部检查**

Run: 按文件名排序执行所有`tests/check_*.py`。
Expected: 全部通过。

- [ ] **Step 2: 运行前端发布门禁**

Run: `npm --prefix frontend ci && npm --prefix frontend audit --audit-level=high && npm --prefix frontend run build`
Expected: 依赖安装、审计和构建通过。

- [ ] **Step 3: 检查差异与敏感信息**

Run: `git diff --check`，并确认未提交`.env`、数据库、上传文件、`frontend/dist`、`data/mem0`、Key或Token。
Expected: 无异常。

- [ ] **Step 4: 提交并推送**

```text
feat: add actionable agent run recovery
```

先`git fetch origin main`确认可fast-forward，再推送`origin/main`。
