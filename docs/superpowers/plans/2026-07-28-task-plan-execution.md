# Task Plan and Execution State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable, user-isolated Agent task plans with live progress, stop, refresh recovery, interrupted-run resume, and a plan-first `/plan` mode.

**Architecture:** Store task-level truth in `agent_run` and `agent_run_step`, keep low-level trace as a sanitized snapshot, and use a process-local coordinator only for cancellation and live SSE subscribers. Extend the current Agent chat path rather than replacing it; existing tools, MCP, Skills, approvals, chat messages, and trace remain the execution primitives.

**Tech Stack:** FastAPI, Pydantic, SQLite/MySQL, Python threads and queues, SSE, React, Vitest-style Node checks, existing `tests/check_*.py` release checks.

---

## File structure

### Backend

- Create `backend/knowflow/services/agent_run_store.py`: task state constants, legal transitions, row normalization, database persistence, ownership checks, startup interruption recovery.
- Create `backend/knowflow/services/agent_run_coordinator.py`: process-local active-run registry, cancellation signals, subscriber queues, duplicate-start protection.
- Create `backend/knowflow/services/task_planner.py`: internal planning tool schema, plan validation, public plan prompt helpers.
- Create `backend/knowflow/routers/agent_runs.py`: snapshot, event subscription, start, replan, resume, and cancel endpoints.
- Modify `backend/knowflow/db_schema.py`: SQLite/MySQL task tables, indexes, and `agent_tool_call` task linkage.
- Modify `backend/knowflow/database.py`: additive migration columns and startup normalization hook support.
- Modify `backend/knowflow/schemas.py`: `/plan` execution mode and Agent run action payloads.
- Modify `backend/knowflow/services/agent_loop.py`: tool execution callback and plan-step context without changing ordinary tool behavior.
- Modify `backend/knowflow/routers/extensions.py`: create tasks, run planning phase, execute plan steps, persist state before SSE publication, associate tool calls and messages.
- Modify `backend/knowflow/routes.py`: register the Agent run router.
- Modify `backend/knowflow/app.py`: mark stale active runs interrupted during application startup.
- Modify `backend/knowflow/runtime.py`: accept optional `run_id` and `run_step_id` in `log_tool_call`.

### Frontend

- Create `frontend/react/src/components/AgentTaskPlan.jsx`: compact plan card and expandable plan-step timeline.
- Modify `frontend/react/src/api/client.js`: task snapshot, stream, start, resume, and cancel requests.
- Modify `frontend/react/src/controller/controllerState.js`: active run ID, snapshot, and reconnect controller.
- Modify `frontend/react/src/controller/messageEvents.js`: attach run snapshots to React messages.
- Modify `frontend/react/src/controller/knowflowController.js`: bridge run updates into the message and drawer state.
- Modify `frontend/react/src/controller/chatFlow.js`: parse task SSE events, stop via API, restore active runs, and handle `/plan`.
- Modify `frontend/react/src/components/ChatMessages.jsx`: render plan-only cards and task-aware trace strips.
- Modify `frontend/react/src/components/AgentTraceStrip.jsx`: show task progress and current public step.
- Modify `frontend/react/src/components/AgentRunSummary.jsx`: use durable run metrics rather than deriving all state from trace.
- Modify `frontend/react/src/components/ChatEvidenceDrawer.jsx`: show plan as the main process view and trace under the selected step.
- Modify `frontend/react/src/components/ChatComposerForm.jsx`: show stop while running and preserve `/plan` input semantics.
- Modify `frontend/react/src/styles.css`: task timeline, active state, plan card, reconnect state, and narrow-screen drawer.

### Tests and docs

- Create `tests/check_agent_run_store.py`: schema, transitions, user isolation, restart normalization, and tool linkage.
- Create `tests/check_task_planner.py`: 2–8-step validation, sanitization, plan-only behavior, and simple-answer bypass.
- Create `tests/check_agent_run_api.py`: snapshot, duplicate start, cancel, resume, owner isolation, and SSE snapshot.
- Create `tests/check_frontend_agent_task_plan.py`: component rendering and controller event handling.
- Modify `backend/.env.example`, `README.md`: document process-local execution and restart semantics without adding required secrets.

## Task 1: Durable run schema and state store

**Files:**
- Create: `tests/check_agent_run_store.py`
- Create: `backend/knowflow/services/agent_run_store.py`
- Modify: `backend/knowflow/db_schema.py`
- Modify: `backend/knowflow/database.py`
- Modify: `backend/knowflow/runtime.py`

- [ ] **Step 1: Write the failing persistence test**

Create a check that initializes an isolated SQLite database, creates a run with two steps, verifies the normalized snapshot, rejects an illegal `completed → running` transition, hides Alice's run from Bob, links a tool call to the run and step, and converts stale `running` rows to `interrupted`.

```python
run = store.create_run(
    user_id=alice,
    session_id=session_id,
    user_message_id=user_message_id,
    goal_summary="整理Notion资料",
    trigger_mode="auto",
)
steps = store.replace_plan(
    alice,
    run["id"],
    [
        {"title": "搜索资料", "kind": "mcp"},
        {"title": "整理回答", "kind": "answer"},
    ],
)
store.transition_run(alice, run["id"], "running")
store.transition_step(alice, run["id"], steps[0]["id"], "running")
assert store.get_snapshot(alice, run["id"])["steps"][0]["status"] == "running"
assert store.get_snapshot(bob, run["id"]) is None
with expect_value_error("illegal_run_transition"):
    store.transition_run(alice, run["id"], "completed")
    store.transition_run(alice, run["id"], "running")
assert store.interrupt_stale_runs() == 0
```

- [ ] **Step 2: Run the new check and verify it fails**

Run:

```powershell
python tests/check_agent_run_store.py
```

Expected: import or table failure because the store and schema do not exist.

- [ ] **Step 3: Add SQLite and MySQL schema**

Add `agent_run` and `agent_run_step` with foreign-key-compatible IDs, user/session indexes, unique `(run_id, position)`, status fields, timestamps, and sanitized JSON/text columns. Add nullable `run_id` and `run_step_id` to both SQLite and MySQL `agent_tool_call` definitions.

- [ ] **Step 4: Add additive migrations**

Extend `Database.migrate_schema()` so existing databases gain only missing task-link columns and indexes. Preserve existing user data and support repeated startup.

```python
self._ensure_column(conn, "agent_tool_call", "run_id", "TEXT")
self._ensure_column(conn, "agent_tool_call", "run_step_id", "TEXT")
```

- [ ] **Step 5: Implement the state store**

Define explicit transition maps and one public snapshot shape:

```python
RUN_TRANSITIONS = {
    "planning": {"waiting_start", "running", "failed", "cancelled"},
    "waiting_start": {"planning", "running", "cancelled"},
    "running": {"waiting_approval", "interrupted", "completed", "failed", "cancelled"},
    "waiting_approval": {"running", "interrupted", "failed", "cancelled"},
    "interrupted": {"running", "cancelled"},
    "completed": set(),
    "failed": {"running"},
    "cancelled": set(),
}
```

Every public method receives `user_id`; ownership misses return `None` and mutation methods raise a stable not-found error. Updates include `WHERE id=:id AND user_id=:user_id AND version=:version`, increment `version`, and fail cleanly on stale writes.

- [ ] **Step 6: Extend tool-call logging**

Change `log_tool_call(...)` to accept nullable `run_id` and `run_step_id`, write them in the insert, and keep existing callers compatible through default `None`.

- [ ] **Step 7: Run focused checks**

Run:

```powershell
python tests/check_agent_run_store.py
python tests/check_sqlite_db_url.py
python tests/check_schema_compatibility.py
```

Expected: all checks print success and exit 0.

- [ ] **Step 8: Commit**

```powershell
git add backend/knowflow/db_schema.py backend/knowflow/database.py backend/knowflow/runtime.py backend/knowflow/services/agent_run_store.py tests/check_agent_run_store.py
git commit -m "feat: persist agent task runs"
```

## Task 2: Validated planning tool and execution modes

**Files:**
- Create: `tests/check_task_planner.py`
- Create: `backend/knowflow/services/task_planner.py`
- Modify: `tests/check_skill_manifest.py`
- Modify: `backend/knowflow/schemas.py`
- Modify: `backend/knowflow/services/agent_loop.py`
- Modify: `backend/knowflow/services/skill_manifest.py`
- Modify: `backend/knowflow/services/skill_runtime.py`

- [ ] **Step 1: Write the failing planner test**

Cover valid two-step plans, rejection of one or nine steps, title length, unsupported kinds, secret redaction, `/plan` normalization, and a normal direct answer that never creates a plan.

```python
plan = TaskPlan.model_validate({
    "steps": [
        {"title": "搜索Notion资料", "kind": "mcp"},
        {"title": "整理结果", "kind": "answer"},
    ],
})
assert len(plan.steps) == 2
assert parse_execution_mode("/plan 整理资料") == ("plan_only", "整理资料")
assert parse_execution_mode("你好") == ("auto", "你好")
```

- [ ] **Step 2: Run the planner check and verify it fails**

Run:

```powershell
python tests/check_task_planner.py
```

Expected: import failure for `task_planner`.

- [ ] **Step 3: Implement strict plan models**

Use Pydantic literals and field limits:

```python
class TaskPlanStep(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    kind: Literal["reasoning", "tool", "mcp", "skill", "answer"]
    tool_name: str | None = Field(default=None, max_length=160)

class TaskPlan(BaseModel):
    steps: list[TaskPlanStep] = Field(min_length=2, max_length=8)
```

Normalize whitespace and pass every public title through the existing trace sanitizer before storage.

- [ ] **Step 4: Add execution mode to chat payload**

Add `executionMode: Literal["auto", "plan_only"] = "auto"` to `ChatRequest`. The frontend may send `/plan` as text; the backend strips the prefix and forces `plan_only`, so direct API callers and UI callers behave consistently.

- [ ] **Step 5: Add the Skill planning declaration**

Accept `metadata.knowflow.planning: required|auto`, default it to`auto`, and copy it through `SkillManifest`, the stored activation response, and `ActivatedSkill`. Add manifest checks for the valid required value and reject booleans, lists, and unknown strings. An explicitly activated Skill with`planning == "required"` forces planning even when the user did not enter`/plan`.

- [ ] **Step 6: Add an internal planning tool**

Provide `register_task_planner(registry, callback)` that registers `create_task_plan` as `internal=True`, `read_only=True`, and `remove_after_success=True`. Its handler validates and returns a sanitized plan snapshot.

- [ ] **Step 7: Add a tool execution callback**

Extend `AgentRunner.run()` with an optional `execution_callback(execution, trace_step_id)` invoked after each tool finishes. Keep default behavior unchanged. This callback allows the orchestration layer to detect the internal planner and persist ordinary tool calls against the active plan step.

- [ ] **Step 8: Run focused checks**

Run:

```powershell
python tests/check_task_planner.py
python tests/check_agent_loop.py
python tests/check_skill_manifest.py
python tests/check_skill_agent_runtime.py
```

Expected: all exit 0.

- [ ] **Step 9: Commit**

```powershell
git add backend/knowflow/schemas.py backend/knowflow/services/agent_loop.py backend/knowflow/services/task_planner.py backend/knowflow/services/skill_manifest.py backend/knowflow/services/skill_runtime.py tests/check_task_planner.py tests/check_skill_manifest.py
git commit -m "feat: add agent task planning protocol"
```

## Task 3: Process-local run coordination and task API

**Files:**
- Create: `tests/check_agent_run_api.py`
- Create: `backend/knowflow/services/agent_run_coordinator.py`
- Create: `backend/knowflow/routers/agent_runs.py`
- Modify: `backend/knowflow/routes.py`
- Modify: `backend/knowflow/app.py`

- [ ] **Step 1: Write failing coordinator and API checks**

Test one active execution per run, initial SSE snapshot, owner-only access, cancel signaling, invalid resume, and startup interruption.

```python
assert coordinator.start(run_id, target) is True
assert coordinator.start(run_id, target) is False
subscriber = coordinator.subscribe(run_id)
coordinator.publish(run_id, {"type": "step_updated", "step": {"id": "step_1"}})
assert subscriber.get(timeout=1)["type"] == "step_updated"
assert client.get(f"/api/agent/runs/{run_id}", cookies=bob_cookie).status_code == 404
```

- [ ] **Step 2: Run the API check and verify it fails**

Run:

```powershell
python tests/check_agent_run_api.py
```

Expected: missing coordinator/router failure.

- [ ] **Step 3: Implement the coordinator**

Use one lock-protected map containing `cancel_event`, subscriber queues, and thread reference. `publish()` copies safe event dictionaries to subscribers; `finish()` removes the active handle only after a terminal event. Do not store secrets or database connections in the coordinator.

- [ ] **Step 4: Implement owner-scoped endpoints**

`GET /runs/{id}` returns the durable snapshot. `GET /events` first emits `run_snapshot`, subscribes if the run is live, sends keep-alive comments, and terminates on a terminal event. `start`, `replan`, `resume`, and `cancel` validate legal current states before invoking coordinator actions. Replan is allowed only from `waiting_start`; it replaces pending steps atomically and returns to`waiting_start`.

- [ ] **Step 5: Register startup recovery**

During app startup, call `interrupt_stale_runs()` before serving requests. It changes only active statuses and any active step to `interrupted`/`failed` as specified by the store.

- [ ] **Step 6: Run focused checks**

Run:

```powershell
python tests/check_agent_run_api.py
python tests/check_agent_approval.py
python tests/check_agent_trace_stream.py
```

Expected: all exit 0.

- [ ] **Step 7: Commit**

```powershell
git add backend/knowflow/app.py backend/knowflow/routes.py backend/knowflow/routers/agent_runs.py backend/knowflow/services/agent_run_coordinator.py tests/check_agent_run_api.py
git commit -m "feat: expose durable agent run controls"
```

## Task 4: Integrate planning and durable state into Agent chat

**Files:**
- Modify: `tests/check_agent_trace_stream.py`
- Modify: `tests/check_agent_web_search_flow.py`
- Modify: `backend/knowflow/routers/extensions.py`
- Modify: `backend/knowflow/services/approval.py`

- [ ] **Step 1: Add failing end-to-end stream cases**

Add deterministic fake model cases for:

- direct answer with no plan;
- automatic `create_task_plan`, two completed steps, and final answer;
- `/plan` ending in `waiting_start`;
- approval moving run and step to `waiting_approval`;
- cancel ending subsequent work;
- tool records containing `run_id` and `run_step_id`;
- final assistant message containing the final trace and run snapshot link.

- [ ] **Step 2: Run the focused stream checks and verify failure**

Run:

```powershell
python tests/check_agent_trace_stream.py
python tests/check_agent_web_search_flow.py
```

Expected: assertions fail because task events and links are absent.

- [ ] **Step 3: Create and persist the run before execution**

In `execute_agent_chat`, save the user message once, create `agent_run`, and publish `run_snapshot`. Register `create_task_plan` only when planning is permitted. Keep the old direct-answer path valid.

- [ ] **Step 4: Persist plan and execute public steps**

On successful `create_task_plan`, replace the plan atomically and publish `plan_created`. In auto mode transition to `running`; in plan-only mode transition to `waiting_start` and return without executing tools.

The planning model call receives both the internal planner and ordinary tool schemas. Extend`AgentRunner` so an injected first model response can be resumed: an ordinary tool call follows the existing no-plan loop, while a successful`create_task_plan` returns control to the outer executor. Planned execution then invokes`AgentRunner` once per public step with the step title, completed public summaries, conversation context, and the same tool registry. Intermediate answers become sanitized step summaries; the final answer step becomes the assistant response.

For each active step:

```python
store.transition_step(user_id, run_id, step_id, "running")
publish_snapshot("step_updated")
result = execute_step(...)
store.transition_step(
    user_id,
    run_id,
    step_id,
    "completed",
    output_summary=result.public_summary,
)
publish_snapshot("step_updated")
```

- [ ] **Step 5: Persist before broadcasting**

Replace direct trace publication with an emitter that updates `agent_run.trace_json`, commits, and only then calls the coordinator. Approval hooks transition the run and active step to `waiting_approval` before emitting `approval_required`, then return both to `running` after approval.

- [ ] **Step 6: Finish and link records**

Pass `run_id` and current `run_step_id` to `log_tool_call`. After saving the assistant message, backfill `assistant_message_id`, finish the root trace, mark the run `completed`, and publish `done`. On cancel, error, or disconnect, use the legal terminal/interrupted transition and preserve completed steps.

- [ ] **Step 7: Make resume call the same executor**

Extract a shared `execute_persisted_run(user_id, run_id)` entry point used by initial auto execution, `start`, and `resume`. It loads the first unfinished step and never resets completed steps.

- [ ] **Step 8: Run focused Agent checks**

Run:

```powershell
python tests/check_agent_trace_stream.py
python tests/check_agent_web_search_flow.py
python tests/check_agent_approval.py
python tests/check_agent_loop.py
python tests/check_skill_agent_runtime.py
```

Expected: all exit 0.

- [ ] **Step 9: Commit**

```powershell
git add backend/knowflow/routers/extensions.py backend/knowflow/services/approval.py tests/check_agent_trace_stream.py tests/check_agent_web_search_flow.py
git commit -m "feat: execute durable agent task plans"
```

## Task 5: Frontend run state and plan presentation

**Files:**
- Create: `tests/check_frontend_agent_task_plan.py`
- Create: `frontend/react/src/components/AgentTaskPlan.jsx`
- Modify: `frontend/react/src/api/client.js`
- Modify: `frontend/react/src/controller/controllerState.js`
- Modify: `frontend/react/src/controller/messageEvents.js`
- Modify: `frontend/react/src/controller/knowflowController.js`
- Modify: `frontend/react/src/controller/chatFlow.js`
- Modify: `frontend/react/src/components/ChatMessages.jsx`
- Modify: `frontend/react/src/components/AgentTraceStrip.jsx`
- Modify: `frontend/react/src/components/AgentRunSummary.jsx`
- Modify: `frontend/react/src/components/ChatEvidenceDrawer.jsx`
- Modify: `frontend/react/src/components/ChatComposerForm.jsx`
- Modify: `frontend/react/src/styles.css`

- [ ] **Step 1: Write failing frontend checks**

Render fixtures for `waiting_start`, `running`, `waiting_approval`, `interrupted`, `failed`, and `completed`. Assert the public step title, `3/6` progress, start/resume/cancel controls, selected-step trace, and non-color status text. Add controller source assertions for the new task SSE events and reconnect endpoint.

- [ ] **Step 2: Run the frontend check and verify it fails**

Run:

```powershell
python tests/check_frontend_agent_task_plan.py
```

Expected: component import or expected text failure.

- [ ] **Step 3: Add API and message state**

Expose:

```javascript
export const agentRunApi = {
  get: (runId) => apiRequest(`/api/agent/runs/${runId}`),
  start: (runId) => apiRequest(`/api/agent/runs/${runId}/start`, { method: "POST" }),
  replan: (runId) => apiRequest(`/api/agent/runs/${runId}/replan`, { method: "POST" }),
  resume: (runId) => apiRequest(`/api/agent/runs/${runId}/resume`, { method: "POST" }),
  cancel: (runId) => apiRequest(`/api/agent/runs/${runId}/cancel`, { method: "POST" }),
};
```

Add `run` to normalized assistant message state and a `knowflow:react-message-run` bridge event.

- [ ] **Step 4: Parse task events and reconnect**

Handle `run_snapshot`, `plan_created`, `run_updated`, and `step_updated` by replacing the durable run snapshot on the active assistant message. Store `activeRunId`; on stream loss, fetch the snapshot and reconnect only when the server reports a live run. The stop action calls `cancel` before aborting the local stream.

- [ ] **Step 5: Render the task plan**

`AgentTaskPlan` receives `run`, `trace`, `compact`, and action callbacks. It renders ordered steps, an active marker, explicit status text, and expands only the selected step's matching trace. The plan-only variant renders “开始执行”和“重新规划”.

- [ ] **Step 6: Make existing run UI task-aware**

`AgentTraceStrip` uses the current durable step when available. `AgentRunSummary` uses `run.status`, step counts, timestamps, and tool-call count. The drawer places `AgentTaskPlan` before low-level details and filters details by selected plan step.

- [ ] **Step 7: Add composer controls**

While a durable run is active, the send button becomes a stop button with an accessible label. Preserve literal `/plan` submission; do not implement a second planning toggle.

- [ ] **Step 8: Add restrained responsive styling**

Use the existing border, radius, typography, and teal status tokens. Keep plan titles at normal body size, avoid a second large page heading, add a single vertical guide, and use motion only on the active marker. Under the narrow breakpoint, make the drawer full width and keep action buttons reachable.

- [ ] **Step 9: Run frontend checks and build**

Run:

```powershell
python tests/check_frontend_agent_task_plan.py
python tests/check_frontend_agent_trace_react.py
Push-Location frontend
npm run build
Pop-Location
```

Expected: checks exit 0 and Vite completes without errors.

- [ ] **Step 10: Commit**

```powershell
git add frontend/react/src tests/check_frontend_agent_task_plan.py
git commit -m "feat: show live agent task plans"
```

## Task 6: Documentation, release checks, and final publication

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Verify: all changed files

- [ ] **Step 1: Document runtime semantics**

Document that active tasks are process-local while durable state is database-backed, refresh can reconnect within the same process, service restart marks work interrupted, and the user must resume manually. Do not add new required secrets.

- [ ] **Step 2: Run all Python checks**

Run every sorted check independently and stop at the first failure:

```powershell
$checks = Get-ChildItem tests/check_*.py | Sort-Object Name
foreach ($check in $checks) {
  & python $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "Failed: $($check.Name)" }
}
```

Expected: every check exits 0.

- [ ] **Step 3: Run frontend release validation**

```powershell
Push-Location frontend
npm ci
npm audit
npm run build
Pop-Location
```

Expected: audit reports 0 vulnerabilities and build succeeds.

- [ ] **Step 4: Run repository hygiene checks**

```powershell
git diff --check
git status --short
git ls-files | Select-String -Pattern '(^|/)(backend/\.env|.*\.db|uploads/|frontend/dist/)'
git grep -n -I -E 'tvly-[A-Za-z0-9_-]+|ntn_[A-Za-z0-9_-]+|Bearer [A-Za-z0-9._~+/-]{16,}|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
```

Expected: no whitespace errors, no forbidden tracked artifacts, and no real credential matches.

- [ ] **Step 5: Perform manual smoke verification**

Verify:

1. “你好” answers without a plan.
2. `/plan 搜索我的Notion并结合联网资料整理三点结论` stops at the plan card.
3. “开始执行” advances steps and lights the current step.
4. Refresh restores the task and drawer.
5. A write tool waits for approval.
6. Stop prevents later steps.
7. Simulated restart shows “已中断” and resume skips completed steps.
8. Another login cannot access the run URL.

- [ ] **Step 6: Commit implementation**

```powershell
git add backend/.env.example README.md
git status --short
git commit -m "feat: add durable agent task execution"
```

If prior task commits already contain every implementation file, this final commit contains only documentation. Do not create an empty commit.

- [ ] **Step 7: Push**

```powershell
git push origin main
git status -sb
```

Expected: local `main` matches `origin/main` and the worktree is clean.
