# Memory Reliability and Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable Mem0 write operations with safe retries, restart recovery, per-message activity, and compact `MEMORY` trace visibility without blocking chat responses.

**Architecture:** A new `memory_operation` table is the source of truth for recall and write status. `MemoryOperationStore` owns persistence and user-scoped projections, while `MemoryOperationRunner` polls due writes inside the existing single-worker process and updates message or Agent trace projections. The React UI consumes one compact activity summary and reuses the existing Agent trace drawer for detail.

**Tech Stack:** FastAPI, SQLAlchemy Core, SQLite/MySQL, Mem0 2.0.14, React 18, Vite, plain CSS, repository `tests/check_*.py` scripts.

---

## File structure

- Create `backend/knowflow/services/memory_operations.py`: operation store, error classification, background runner, trace projection helpers.
- Modify `backend/knowflow/db_schema.py`: SQLite/MySQL table and indexes.
- Modify `backend/knowflow/database.py`: schema version 8 description.
- Modify `backend/knowflow/services/memory.py`: synchronous result-returning write entry point and safe prompt rule.
- Modify `backend/knowflow/runtime.py`: construct/start/close operation runtime and attach activity to normalized messages.
- Modify `backend/knowflow/app.py`: startup recovery and ordered shutdown.
- Modify `backend/knowflow/routers/chat.py`: record recall result, enqueue write, expose message activity.
- Modify `backend/knowflow/routers/extensions.py`: add `MEMORY` trace steps and enqueue durable write.
- Modify `backend/knowflow/routers/memories.py`: retry endpoint and operation-summary cleanup.
- Modify `backend/knowflow/schemas.py`: retry request only if an explicit body becomes necessary; prefer bodyless retry.
- Modify `frontend/react/src/api/client.js`: memory activity and retry API methods.
- Modify `frontend/react/src/controller/chatFlow.js`: populate and poll message memory activity.
- Modify `frontend/react/src/components/ChatMessages.jsx`: compact activity line and retry action.
- Modify `frontend/react/src/components/AgentTraceView.jsx`: `MEMORY` label and memory-specific detail.
- Modify `frontend/react/src/styles.css`: compact states, memory kind, responsive behavior.
- Create `tests/check_memory_operations.py`: schema, store, retry, recovery, isolation, cleanup.
- Modify `tests/check_memory_chat_flow.py`: route sequencing and non-blocking behavior.
- Modify `tests/check_agent_trace.py`: memory step projection.
- Modify `tests/check_memory_api.py`: activity ownership and retry.
- Modify `tests/check_release_hygiene.py` only if the repository requires registering the new check explicitly.

### Task 1: Add the durable operation schema

**Files:**
- Modify: `backend/knowflow/db_schema.py`
- Modify: `backend/knowflow/database.py`
- Create: `tests/check_memory_operations.py`

- [ ] **Step 1: Write the failing schema check**

Create an isolated SQLite database and assert:

```python
expected = {
    "id", "user_id", "session_id", "message_id", "agent_run_id",
    "kind", "status", "attempt_count", "next_attempt_at",
    "result_json", "error_code", "error_message",
    "started_at", "finished_at", "created_at", "updated_at",
}
rows = db.engine.connect().execute(text("PRAGMA table_info(memory_operation)"))
assert expected <= {row._mapping["name"] for row in rows}
assert CURRENT_SCHEMA_VERSION == 8
```

- [ ] **Step 2: Run the check and confirm failure**

Run: `python tests/check_memory_operations.py`
Expected: failure because `memory_operation` does not exist.

- [ ] **Step 3: Add SQLite and MySQL DDL**

Use `TEXT` IDs for SQLite and `VARCHAR(64)` for MySQL. Add:

```sql
UNIQUE (user_id, message_id, kind)
```

and indexes for:

```sql
(status, next_attempt_at)
(user_id, message_id)
(user_id, created_at)
```

Increment `CURRENT_SCHEMA_VERSION` to `8` and set the description to `Add durable memory operation tracking and retries.`

- [ ] **Step 4: Run schema checks**

Run: `python tests/check_memory_operations.py`
Expected: schema section passes.

- [ ] **Step 5: Commit**

```powershell
git add backend/knowflow/db_schema.py backend/knowflow/database.py tests/check_memory_operations.py
git commit -m "feat: add durable memory operation schema"
```

### Task 2: Implement the operation store

**Files:**
- Create: `backend/knowflow/services/memory_operations.py`
- Modify: `tests/check_memory_operations.py`

- [ ] **Step 1: Add failing store tests**

Use two users and assert:

```python
recall_id, write_id = store.create_for_message(
    user_id=7,
    session_id="session-a",
    message_id=11,
    agent_run_id=None,
    recalled=[{"id": "m1", "memory": "默认使用Python"}],
)
activity = store.activity_for_message(user_id=7, message_id=11)
assert activity["summary"]["recalled"] == 1
assert activity["operations"][1]["status"] == "queued"
assert store.activity_for_message(user_id=8, message_id=11) is None
```

Also assert duplicate creation returns the existing rows rather than creating more rows.

- [ ] **Step 2: Run and confirm failure**

Run: `python tests/check_memory_operations.py`
Expected: import or attribute failure for `MemoryOperationStore`.

- [ ] **Step 3: Implement store primitives**

Implement:

```python
class MemoryOperationStore:
    def create_for_message(...)->tuple[str, str]: ...
    def activity_for_message(*, user_id: int, message_id: int)->dict[str, Any] | None: ...
    def activity_map_for_messages(*, user_id: int, message_ids: list[int])->dict[int, dict[str, Any]]: ...
    def claim_due(self, *, now: datetime)->dict[str, Any] | None: ...
    def mark_succeeded(self, operation_id: str, result: list[dict[str, Any]])->None: ...
    def reschedule(self, operation_id: str, *, error_code: str, error_message: str, next_attempt_at: datetime)->None: ...
    def mark_failed(self, operation_id: str, *, error_code: str, error_message: str)->None: ...
    def retry_failed(self, *, user_id: int, operation_id: str)->dict[str, Any]: ...
    def recover_interrupted(self, *, stale_before: datetime)->int: ...
    def redact_memory(self, *, user_id: int, memory_id: str)->None: ...
    def redact_user(self, *, user_id: int)->None: ...
    def purge_expired(self, *, before: datetime)->int: ...
```

Normalize API fields to camelCase. Keep SQL parameters bound and include `user_id` in every user-facing read or mutation.

- [ ] **Step 4: Add atomic claim and cleanup tests**

Assert only one caller can change the same queued row to running, `attempt_count` increments once, stale running rows recover to queued, and 30-day purge does not touch Mem0 records.

- [ ] **Step 5: Run tests**

Run: `python tests/check_memory_operations.py`
Expected: all store tests pass.

- [ ] **Step 6: Commit**

```powershell
git add backend/knowflow/services/memory_operations.py tests/check_memory_operations.py
git commit -m "feat: persist user-scoped memory operations"
```

### Task 3: Add classified retries and restart recovery

**Files:**
- Modify: `backend/knowflow/services/memory.py`
- Modify: `backend/knowflow/services/memory_operations.py`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/app.py`
- Modify: `tests/check_memory_operations.py`
- Modify: `tests/check_memory_provider.py`

- [ ] **Step 1: Write failing runner tests**

Test a fake provider sequence:

```python
provider.outcomes = [TimeoutError(), FakeHttpError(503), [{"event": "ADD", "id": "m2"}]]
runner.run_once()
clock.advance(seconds=5)
runner.run_once()
clock.advance(seconds=30)
runner.run_once()
assert provider.calls == 3
assert store.get(write_id)["status"] == "succeeded"
```

Test 401 and 400 fail after one call, while 429, timeouts, connection failures and 5xx reschedule. Test shutdown stops claiming before closing the provider.

- [ ] **Step 2: Run and confirm failure**

Run: `python tests/check_memory_operations.py`
Expected: failure because the runner and classifier are absent.

- [ ] **Step 3: Expose a synchronous manager write**

Add:

```python
def remember_now(
    self, *, user_id: int, session_id: str, message_id: int,
    question: str, answer: str, operation_id: str | None = None,
) -> list[dict[str, Any]]:
```

Return the provider result. Include `operation_id` in Mem0 metadata. Keep `remember_async()` as a compatibility wrapper until both call sites migrate.

- [ ] **Step 4: Implement classifier and runner**

Add:

```python
RETRY_DELAYS = (5, 30)

def classify_memory_error(exc: Exception) -> tuple[str, bool, str]:
    status = getattr(exc, "status_code", None)
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return "memory_upstream_unavailable", True, "记忆服务暂时不可用。"
    if status == 429:
        return "memory_rate_limited", True, "记忆服务请求过多。"
    if isinstance(status, int) and status >= 500:
        return "memory_upstream_unavailable", True, "记忆服务暂时不可用。"
    if status in {401, 403}:
        return "memory_auth_failed", False, "记忆服务认证失败。"
    return "memory_request_rejected", False, "记忆写入未完成。"
```

`MemoryOperationRunner` uses one daemon thread, polls due work, loads the user and assistant messages by `session_id` and `message_id`, performs at most three attempts, and writes only safe error text.

- [ ] **Step 5: Wire lifecycle**

Construct store and runner in `runtime.py`. On app startup recover stale running rows and start the runner. On shutdown stop the runner, wait for the active call, then close `MemoryManager` and its provider.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
python tests/check_memory_operations.py
python tests/check_memory_provider.py
```

Expected: both pass.

- [ ] **Step 7: Commit**

```powershell
git add backend/knowflow/services/memory.py backend/knowflow/services/memory_operations.py backend/knowflow/runtime.py backend/knowflow/app.py tests/check_memory_operations.py tests/check_memory_provider.py
git commit -m "feat: retry and recover memory writes"
```

### Task 4: Integrate chat, Agent trace, and APIs

**Files:**
- Modify: `backend/knowflow/routers/chat.py`
- Modify: `backend/knowflow/routers/extensions.py`
- Modify: `backend/knowflow/routers/memories.py`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/services/memory_operations.py`
- Modify: `tests/check_memory_chat_flow.py`
- Modify: `tests/check_agent_trace.py`
- Modify: `tests/check_memory_api.py`

- [ ] **Step 1: Write failing route tests**

Assert the ordinary chat sequence is:

```text
recall -> generate -> save assistant -> create recall/write operations
```

Assert `/api/messages/{message_id}/memory-activity` returns 404 for another user. Assert retry accepts only an owned failed write and returns 409 for queued, running, or succeeded writes.

- [ ] **Step 2: Run and confirm failure**

Run:

```powershell
python tests/check_memory_chat_flow.py
python tests/check_memory_api.py
python tests/check_agent_trace.py
```

Expected: new assertions fail.

- [ ] **Step 3: Integrate ordinary chat**

After saving the assistant message, replace `remember_async()` with:

```python
memory_operation_store.create_for_message(
    user_id=user_id,
    session_id=session_id,
    message_id=message_id,
    agent_run_id=None,
    recalled=memories,
)
memory_operation_runner.wake()
```

Include the initial activity in the chat result and `done` SSE event. Add `memoryActivity` to session message normalization using one batch query per session, not one query per message.

- [ ] **Step 4: Integrate Agent trace**

Wrap recall in a `kind="memory"` trace step and emit its completed state. Before returning the final snapshot, add a queued write step with a stable `stepId` derived from the operation. When the runner updates the write operation, project the latest write status into both `chat_message.trace_json` and `agent_run.trace_json`.

- [ ] **Step 5: Add user-scoped endpoints**

Add:

```python
GET /api/messages/{message_id}/memory-activity
POST /api/memory/operations/{operation_id}/retry
```

Return 404 for non-owned rows, 409 for invalid state, and a safe 503 only when the memory backend is unavailable.

- [ ] **Step 6: Redact operation summaries on memory deletion**

After successful single delete call `redact_memory(user_id, memory_id)`. After clear-all call `redact_user(user_id)`.

- [ ] **Step 7: Run focused backend checks**

Run the three checks from Step 2.
Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add backend/knowflow/routers/chat.py backend/knowflow/routers/extensions.py backend/knowflow/routers/memories.py backend/knowflow/runtime.py tests/check_memory_chat_flow.py tests/check_memory_api.py tests/check_agent_trace.py
git commit -m "feat: expose memory activity in chat runs"
```

### Task 5: Add compact React activity and `MEMORY` nodes

**Files:**
- Modify: `frontend/react/src/api/client.js`
- Modify: `frontend/react/src/controller/chatFlow.js`
- Modify: `frontend/react/src/components/ChatMessages.jsx`
- Modify: `frontend/react/src/components/AgentTraceView.jsx`
- Modify: `frontend/react/src/styles.css`
- Create: `tests/check_memory_frontend.py`

- [ ] **Step 1: Write the failing frontend source check**

Assert source contains:

```text
memoryApi.activity
memoryApi.retryOperation
memory-activity
MEMORY
knowflow:react-memory-activity-open
```

and rejects a separate full-screen memory run component.

- [ ] **Step 2: Run and confirm failure**

Run: `python tests/check_memory_frontend.py`
Expected: failure for missing API and component tokens.

- [ ] **Step 3: Add client and polling**

Add:

```javascript
activity: (messageId) => apiRequest(`/api/messages/${messageId}/memory-activity`),
retryOperation: (operationId) =>
  apiRequest(`/api/memory/operations/${encodeURIComponent(operationId)}/retry`, { method: "POST" }),
```

After the `done` event, keep a bounded poll only while a write is queued or running. Stop on terminal status, navigation, abort, or unmount.

- [ ] **Step 4: Render the compact status**

`ChatMessages.jsx` renders the line only when activity has a visible recall, change, or failure. Use:

```text
参考了N条记忆 · 正在整理记忆…
参考了N条记忆 · 新增N条
记忆写入失败 · 重试
```

Clicking dispatches `knowflow:react-agent-trace-open` with memory steps and selects the write step. Retry calls the API and returns the line to running.

- [ ] **Step 5: Extend trace display**

Map `kind === "memory"` to `MEMORY`. Render item actions and safe error summaries using the existing trace detail block. Do not add a new drawer or permanent card.

- [ ] **Step 6: Add styles**

Use existing CSS variables. The status is transparent by default, gets `surface-muted` only on hover, and uses success/running/failed dots. Add `prefers-reduced-motion` and a 375px rule that prevents horizontal overflow.

- [ ] **Step 7: Run frontend checks**

Run:

```powershell
python tests/check_memory_frontend.py
npm run build
```

Workdir for build: `frontend`
Expected: check passes and Vite production build succeeds.

- [ ] **Step 8: Commit**

```powershell
git add frontend/react/src/api/client.js frontend/react/src/controller/chatFlow.js frontend/react/src/components/ChatMessages.jsx frontend/react/src/components/AgentTraceView.jsx frontend/react/src/styles.css tests/check_memory_frontend.py
git commit -m "feat: show reliable memory activity"
```

### Task 6: Prevent false success language

**Files:**
- Modify: `backend/knowflow/runtime.py`
- Create: `tests/check_memory_response_contract.py`

- [ ] **Step 1: Write failing prompt-contract checks**

Assert the system prompt contains a language-independent rule that the model must not claim a long-term memory write succeeded and must defer to the UI status.

- [ ] **Step 2: Run and confirm failure**

Run: `python tests/check_memory_response_contract.py`
Expected: prompt-contract assertion fails.

- [ ] **Step 3: Add the contract**

Append to the memory system instruction:

```text
Long-term memory writes happen after this response. Never claim that a memory
was saved, remembered, or updated successfully. If the user explicitly asks
you to remember something, say that KnowFlow will attempt it and that the
result appears below the answer.
```

Apply the rule whenever memory is enabled, even when no memories were recalled.

- [ ] **Step 4: Run checks**

Run:

```powershell
python tests/check_memory_response_contract.py
python tests/check_memory_chat_flow.py
```

Expected: both pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/knowflow/runtime.py tests/check_memory_response_contract.py
git commit -m "fix: make memory write status authoritative"
```

### Task 7: Full release verification and publish

**Files:**
- Modify: `README.md` only if API or operational behavior needs a short operator note.
- Modify: `backend/.env.example` only if a new retention or polling environment variable is introduced; prefer constants to avoid unnecessary configuration.

- [ ] **Step 1: Run all Python checks in filename order**

```powershell
$checks = Get-ChildItem tests/check_*.py | Sort-Object Name
foreach($check in $checks){ python $check.FullName; if($LASTEXITCODE -ne 0){ exit $LASTEXITCODE } }
```

Expected: every check passes.

- [ ] **Step 2: Run frontend install audit and build**

```powershell
npm ci
npm audit --audit-level=high
npm run build
```

Workdir: `frontend`
Expected: install, audit and build pass.

- [ ] **Step 3: Run release hygiene**

```powershell
git diff --check
git status -sb
git ls-files backend/.env frontend/dist data
git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|api[_-]?key[[:space:]]*=[[:space:]]*[^\"'[:space:]]+)"
```

Expected: no whitespace errors, no prohibited tracked artifacts, no real Key or Token.

- [ ] **Step 4: Inspect final diff**

Confirm every changed file belongs to this feature and no existing user changes were reverted.

- [ ] **Step 5: Commit final documentation adjustments**

```powershell
git add README.md backend/.env.example
git commit -m "docs: document reliable memory operations"
```

Skip this commit if neither file changed.

- [ ] **Step 6: Push**

```powershell
git push origin main
```

Expected: `origin/main` advances to the verified local HEAD.
