# Agent Detail Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让Skill选择、任务步骤和持久化Agent运行在加载、空数据与异常关闭时都给出准确反馈。

**Architecture:** 前端用显式状态而不是空数组推断请求结果；任务步骤详情保持ARIA与视觉一致。后端在协调器关闭事件处读取持久化快照并生成稳定终态事件，前端据此收尾，不新增数据库结构。

**Tech Stack:** React、FastAPI、Python静态检查脚本、SSE、Vite

---

### Task 1: Skill选择器请求状态与无障碍语义

**Files:**
- Modify: `tests/check_frontend_skill_picker_react.py`
- Modify: `frontend/react/src/components/ChatComposerForm.jsx`
- Modify: `frontend/react/src/components/SkillPicker.jsx`

- [ ] **Step 1: 写入失败检查**

在`check_frontend_skill_picker_react.py`要求组件出现`skillsStatus`、`onRetry`、`aria-label={"消息"}`、`aria-haspopup={"listbox"}`、加载文案和失败重试文案，并禁止catch分支把`skillsLoadedRef.current`设为成功。

- [ ] **Step 2: 运行检查并确认失败**

Run: `python tests/check_frontend_skill_picker_react.py`

Expected: FAIL，指出缺少`skillsStatus`或`onRetry`。

- [ ] **Step 3: 实现最小状态机**

在`ChatComposerForm`增加：

```jsx
const [skillsStatus, setSkillsStatus] = useState("idle");

const loadAvailableSkills = useCallback(async () => {
  const requestId = ++requestGenerationRef.current;
  setSkillsStatus("loading");
  try {
    const skills = await skillApi.list();
    if (!mountedRef.current || requestId !== requestGenerationRef.current) return;
    setAvailableSkills(normalizeAvailableSkills(skills));
    skillsLoadedRef.current = true;
    setSkillsStatus("ready");
  } catch {
    if (!mountedRef.current || requestId !== requestGenerationRef.current) return;
    skillsLoadedRef.current = false;
    setSkillsStatus("error");
  }
}, []);
```

向`SkillPicker`传入`status={skillsStatus}`和`onRetry={loadAvailableSkills}`。加载中只显示“正在加载Skills…”，失败时显示“Skills加载失败”和“重试”，仅`ready`且结果为空时显示安装入口。textarea增加`aria-label={"消息"}`和`aria-haspopup={"listbox"}`，listbox使用`aria-busy={status === "loading"}`。

- [ ] **Step 4: 运行检查并确认通过**

Run: `python tests/check_frontend_skill_picker_react.py`

Expected: `React composer Skill picker checks passed`

### Task 2: 任务步骤空详情反馈

**Files:**
- Modify: `tests/check_frontend_agent_task_plan.py`
- Modify: `frontend/react/src/components/AgentTaskPlan.jsx`
- Modify: `frontend/react/src/styles.css`

- [ ] **Step 1: 写入失败检查**

要求`AgentTaskPlan.jsx`包含`暂无执行记录`和`role={"status"}`，要求样式包含`.agent-task-step-empty`。

- [ ] **Step 2: 运行检查并确认失败**

Run: `python tests/check_frontend_agent_task_plan.py`

Expected: FAIL，指出缺少空详情反馈。

- [ ] **Step 3: 实现展开反馈**

```jsx
{selected ? (
  <div className={"agent-task-step-trace"}>
    {selectedTrace.length ? (
      <AgentTraceView trace={selectedTrace} />
    ) : (
      <p className={"agent-task-step-empty"} role={"status"}>暂无执行记录</p>
    )}
  </div>
) : null}
```

空态采用次要文字色和紧凑内边距，不新增卡片层级。

- [ ] **Step 4: 运行检查并确认通过**

Run: `python tests/check_frontend_agent_task_plan.py`

Expected: `frontend Agent task plan checks passed`

### Task 3: 持久化运行SSE终态收敛

**Files:**
- Modify: `tests/check_agent_run_api.py`
- Modify: `backend/knowflow/routers/agent_runs.py`
- Modify: `frontend/react/src/controller/chatFlow.js`
- Modify: `tests/check_frontend_agent_task_plan.py`

- [ ] **Step 1: 写入后端失败检查**

新增协调器target直接抛异常的场景，订阅`/api/agent/runs/{id}/events`后断言事件流包含`event: error`、公开错误码`agent_run_failed`，且重新读取run得到`status == "failed"`。

- [ ] **Step 2: 运行后端检查并确认失败**

Run: `python tests/check_agent_run_api.py`

Expected: FAIL，当前流在`stream_closed`处无事件退出或run仍为活动态。

- [ ] **Step 3: 增加统一终态事件函数**

在`agent_runs.py`增加私有函数：

```python
def _closed_run_event(
    user_id: int,
    run_id: str,
) -> tuple[str, dict[str, Any]] | None:
    snapshot = _snapshot_or_404(user_id, run_id)
    if snapshot["status"] in ACTIVE_RUN_STATUSES:
        try:
            snapshot = agent_runs.transition_run(user_id, run_id, "failed")
        except AgentRunStoreError:
            snapshot = _snapshot_or_404(user_id, run_id)
    if snapshot["status"] == "completed":
        return "done", {"type": "done", "run": snapshot}
    if snapshot["status"] == "cancelled":
        return "cancelled", {"type": "cancelled", "run": snapshot}
    if snapshot["status"] == "failed":
        return "error", {
            "type": "error",
            "code": "agent_run_failed",
            "message": "Agent run failed.",
            "run": snapshot,
        }
    return None
```

从`agent_run_store`导入`ACTIVE_RUN_STATUSES`和`AgentRunStoreError`。`subscriber is None`和`stream_closed`两个分支都调用该函数；返回值不为空时yield一次终态事件。这样正常完成、取消和失败均有明确收尾，同时`waiting_start`、`interrupted`等可恢复状态只返回快照。错误事件不暴露异常文本。

- [ ] **Step 4: 前端处理失败与取消**

在`reconnectAgentRun`事件循环中：

```js
if (eventPayload.type === "error") {
  renderAgentRun(message, eventPayload.run || null);
  state.activeRunId = null;
  state.activeRunMessageId = null;
  setMessageContent(message, "assistant", `请求失败：${eventPayload.message || "Agent运行失败。"}`);
}
if (eventPayload.type === "cancelled") {
  renderAgentRun(message, eventPayload.run || null);
  state.activeRunId = null;
  state.activeRunMessageId = null;
  setMessageContent(message, "assistant", answerBuffer || "生成已停止。");
}
```

静态检查要求两种事件均显式处理并清理活动run。

- [ ] **Step 5: 运行相关检查并确认通过**

Run: `python tests/check_agent_run_api.py`

Run: `python tests/check_frontend_agent_task_plan.py`

Expected: 两项均通过。

### Task 4: 发布验证

**Files:**
- Verify: `tests/check_*.py`
- Verify: `frontend/package-lock.json`

- [ ] **Step 1: 运行全部Python检查**

Run: `$files = Get-ChildItem tests/check_*.py | Sort-Object Name; foreach ($file in $files) { python $file.FullName; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }`

Expected: 所有检查退出码为0。

- [ ] **Step 2: 运行前端审计和构建**

Run: `npm audit`

Run: `npm run build`

Working directory: `frontend`

Expected: 0 vulnerabilities；Vite构建成功。

- [ ] **Step 3: 运行Git卫生检查**

Run: `git diff --check`

Run: `git status -sb`

Expected: 无空白错误，仅包含本计划文件和预期源码、检查文件。

- [ ] **Step 4: 提交并推送**

```powershell
git add -- frontend/react/src/components/ChatComposerForm.jsx frontend/react/src/components/SkillPicker.jsx frontend/react/src/components/AgentTaskPlan.jsx frontend/react/src/controller/chatFlow.js frontend/react/src/styles.css backend/knowflow/routers/agent_runs.py tests/check_frontend_skill_picker_react.py tests/check_frontend_agent_task_plan.py tests/check_agent_run_api.py docs/superpowers/specs/2026-07-29-agent-detail-polish-design.md
git add -f -- docs/superpowers/plans/2026-07-29-agent-detail-polish.md
git commit -m "fix: clarify agent interaction states"
git push origin main
```

Expected: `main -> main`
