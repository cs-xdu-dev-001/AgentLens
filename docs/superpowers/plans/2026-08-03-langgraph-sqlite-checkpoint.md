# LangGraph SQLite Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为LangGraph纯模型执行引擎接入官方SQLite checkpoint，使用户主动继续任务时能从最近节点边界恢复，并在删除会话时清理对应checkpoint。

**Architecture:** 使用独立的`LangGraphCheckpointStore`封装官方`SqliteSaver`、严格序列化、连接和文件权限。路由将现有`user_id`和`run_id`传给统一执行引擎，LangGraph以`run_id`作为`thread_id`；恢复入口仍先通过`agent_run`完成用户归属校验。

**Tech Stack:** Python 3.10、FastAPI、LangGraph 1.2.10、langgraph-checkpoint-sqlite 3.1.0、SQLite、PowerShell 7

## Global Constraints

- `KNOWFLOW_AGENT_ENGINE=current`继续是默认值。
- 固定使用`langgraph-checkpoint-sqlite==3.1.0`。
- checkpoint默认路径为`./data/langgraph/checkpoints.sqlite3`。
- `thread_id`必须与现有`run_id`完全一致。
- 不自动扫描或续跑任务，只支持用户主动继续。
- 不迁移工具、MCP、Skills、审批或Mem0节点。
- checkpoint不得保存API Key、OAuth Token、Cookie、请求头、数据库连接或Python回调。
- `JsonPlusSerializer`必须使用`allowed_msgpack_modules=None`和`pickle_fallback=False`。
- `current`模式不得创建checkpoint文件。
- 不修改现有SSE事件、前端协议或业务数据库schema。
- 不提交`.env`、数据库、上传文件、`frontend/dist`、`data`或密钥。

---

### Task 1: 固定依赖并增加checkpoint路径配置

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/knowflow/config.py`
- Modify: `backend/.env.example`
- Test: `tests/check_langgraph_checkpoint_config.py`

**Interfaces:**
- Produces: `config.LANGGRAPH_CHECKPOINT_DB: pathlib.Path`
- Produces: 安装依赖`langgraph-checkpoint-sqlite==3.1.0`

- [ ] **Step 1: 写配置失败测试**

创建`tests/check_langgraph_checkpoint_config.py`，在隔离环境导入配置并断言：

```python
assert config.LANGGRAPH_CHECKPOINT_DB == (
    config.PROJECT_DIR / "data" / "langgraph" / "checkpoints.sqlite3"
).resolve()
assert not config.LANGGRAPH_CHECKPOINT_DB.exists()
```

再设置绝对临时路径并重新导入，断言配置保留该绝对路径且导入配置不会创建父目录或数据库文件。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_langgraph_checkpoint_config.py`

Expected: FAIL，`config`尚无`LANGGRAPH_CHECKPOINT_DB`。

- [ ] **Step 3: 实现最小配置**

在`backend/knowflow/config.py`中增加：

```python
LANGGRAPH_CHECKPOINT_DB = Path(
    os.getenv(
        "KNOWFLOW_LANGGRAPH_CHECKPOINT_DB",
        str(DATA_DIR / "langgraph" / "checkpoints.sqlite3"),
    )
).expanduser()
if not LANGGRAPH_CHECKPOINT_DB.is_absolute():
    LANGGRAPH_CHECKPOINT_DB = (
        PROJECT_DIR / LANGGRAPH_CHECKPOINT_DB
    ).resolve()
```

不要在配置导入阶段创建目录或文件。

在`backend/requirements.txt`增加：

```text
langgraph-checkpoint-sqlite==3.1.0
```

在`backend/.env.example`增加：

```dotenv
KNOWFLOW_LANGGRAPH_CHECKPOINT_DB=./data/langgraph/checkpoints.sqlite3
```

- [ ] **Step 4: 运行配置测试和依赖解析检查**

Run: `python tests/check_langgraph_checkpoint_config.py`

Expected: PASS。

Run: `python -m pip install --dry-run -r backend/requirements.txt`

Expected: 依赖可解析，没有版本冲突。

- [ ] **Step 5: 提交配置任务**

```powershell
git add backend/requirements.txt backend/knowflow/config.py backend/.env.example tests/check_langgraph_checkpoint_config.py
git commit -m "build: add langgraph sqlite checkpoints"
```

### Task 2: 封装官方SQLite checkpointer和安全边界

**Files:**
- Create: `backend/knowflow/services/langgraph_checkpoint.py`
- Create: `tests/check_langgraph_checkpoint_store.py`

**Interfaces:**
- Produces: `LangGraphCheckpointStore(path: Path, timeout_seconds: float = 30.0)`
- Produces: `LangGraphCheckpointStore.open(*, create: bool = True) -> ContextManager[SqliteSaver]`
- Produces: `LangGraphCheckpointStore.delete_threads(run_ids: Iterable[str]) -> None`
- Produces: `LangGraphCheckpointError(code: str, message: str)`

- [ ] **Step 1: 写存储层失败测试**

测试使用临时目录并覆盖这些行为：

```python
store = LangGraphCheckpointStore(temp_path / "checkpoints.sqlite3")
assert not store.path.exists()

with store.open() as saver:
    assert saver is not None
    assert saver.serde.pickle_fallback is False

assert store.path.exists()
```

再验证：

- `open(create=False)`在文件不存在时返回空上下文或明确的“不存在”结果，且不创建文件；
- Linux下父目录模式为`750`、文件模式为`600`；
- `delete_threads(["run_a"])`调用官方`delete_thread`后无法再读取该thread；
- 重复删除同一thread不报错；
- 不可创建路径被转换为`LangGraphCheckpointError("langgraph_checkpoint_unavailable", ...)`；
- `allowed_msgpack_modules is None`且`pickle_fallback is False`。

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_langgraph_checkpoint_store.py`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现checkpoint存储封装**

实现懒加载，保证`current`模式不因可选LangGraph模块导入失败而无法启动：

```python
class LangGraphCheckpointError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class LangGraphCheckpointStore:
    def __init__(self, path: Path, timeout_seconds: float = 30.0):
        self.path = Path(path)
        self.timeout_seconds = max(1.0, float(timeout_seconds))

    @contextmanager
    def open(self, *, create: bool = True):
        if not create and not self.path.exists():
            yield None
            return
        self._prepare_path()
        conn = sqlite3.connect(
            str(self.path),
            timeout=self.timeout_seconds,
            check_same_thread=False,
        )
        try:
            from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
            from langgraph.checkpoint.sqlite import SqliteSaver

            serializer = JsonPlusSerializer(
                allowed_msgpack_modules=None,
                pickle_fallback=False,
            )
            yield SqliteSaver(conn, serde=serializer)
        except LangGraphCheckpointError:
            raise
        except Exception as exc:
            raise LangGraphCheckpointError(
                "langgraph_checkpoint_unavailable",
                "LangGraph execution progress is unavailable.",
            ) from exc
        finally:
            conn.close()
```

`_prepare_path()`只在`create=True`时创建目录和文件；POSIX权限使用`os.chmod`固定为目录`0o750`、文件`0o600`。`delete_threads()`先以`create=False`打开现有数据库，再逐个调用官方`saver.delete_thread(run_id)`。

- [ ] **Step 4: 运行存储测试**

Run: `python tests/check_langgraph_checkpoint_store.py`

Expected: PASS。

- [ ] **Step 5: 提交存储封装**

```powershell
git add backend/knowflow/services/langgraph_checkpoint.py tests/check_langgraph_checkpoint_store.py
git commit -m "feat: add langgraph checkpoint store"
```

### Task 3: 将checkpoint身份、首次运行和恢复接入执行引擎

**Files:**
- Modify: `backend/knowflow/services/agent_engine.py`
- Modify: `backend/knowflow/services/langgraph_agent_engine.py`
- Modify: `backend/knowflow/routers/extensions.py`
- Modify: `tests/check_agent_engine.py`
- Modify: `tests/check_langgraph_agent_engine.py`
- Modify: `tests/check_agent_run_api.py`

**Interfaces:**
- Consumes: `LangGraphCheckpointStore`
- Modifies: `AgentEngine.run(..., user_id: int, run_id: str, resume_from_checkpoint: bool = False)`
- Modifies: `build_agent_engine(..., checkpoint_db_path: Path | None = None)`

- [ ] **Step 1: 扩展执行引擎接口测试**

在`tests/check_agent_engine.py`中更新所有调用，显式传入：

```python
user_id=17,
run_id="run_test",
resume_from_checkpoint=False,
```

断言`CurrentAgentEngine`行为和结果不变，并且不会创建checkpoint文件。

- [ ] **Step 2: 写LangGraph持久化和恢复失败测试**

在`tests/check_langgraph_agent_engine.py`使用临时SQLite文件和计数网关覆盖：

```python
first = LangGraphAgentEngine(
    gateway=failing_once_gateway,
    checkpoint_db_path=checkpoint_path,
)
try:
    first.run(
        user_id=17,
        run_id="run_resume",
        messages=[{"role": "user", "content": "hello"}],
        config=safe_config,
        registry=registry,
    )
except ExpectedGatewayError:
    pass
else:
    raise AssertionError("The first model call must fail")

second = LangGraphAgentEngine(
    gateway=failing_once_gateway,
    checkpoint_db_path=checkpoint_path,
)
result = second.run(
    user_id=17,
    run_id="run_resume",
    messages=[],
    config=safe_config,
    registry=registry,
    resume_from_checkpoint=True,
)
assert result.answer == "recovered"
assert failing_once_gateway.calls == 2
```

再覆盖：

- 首次运行保存的checkpoint配置中`thread_id == run_id`；
- 完成后使用新引擎再次恢复，直接返回答案且网关调用次数不增加；
- 不存在的checkpoint抛出公开错误码`langgraph_checkpoint_not_found`；
- fake API Key不会出现在SQLite原始字节中；
- `schema_version`存在且值为`1`；
- Responses API和Chat Completions配置仍原样传给网关。
- 用户A调用用户B的继续执行接口时返回404，并且LangGraph网关调用次数保持不变。

- [ ] **Step 3: 运行专项测试并确认失败**

Run: `python tests/check_agent_engine.py`

Run: `python tests/check_langgraph_agent_engine.py`

Expected: FAIL，接口和checkpoint尚未接入。

- [ ] **Step 4: 扩展统一执行接口**

在`AgentEngine`、`CurrentAgentEngine`和`LangGraphAgentEngine`的`run()`中加入：

```python
user_id: int,
run_id: str,
resume_from_checkpoint: bool = False,
```

`CurrentAgentEngine`忽略这些参数后继续调用现有`AgentRunner`。`build_agent_engine()`接收`checkpoint_db_path`，仅在选择`langgraph`时传给`LangGraphAgentEngine`。

- [ ] **Step 5: 编译带checkpointer的图并实现恢复**

`LangGraphAgentEngine.run()`使用`LangGraphCheckpointStore.open()`取得官方saver，再调用：

```python
graph = builder.compile(checkpointer=saver)
graph_config = {"configurable": {"thread_id": run_id}}
```

首次运行输入：

```python
{
    "schema_version": 1,
    "messages": [dict(message) for message in messages],
    "answer": "",
}
```

恢复运行先读取`graph.get_state(graph_config)`：

- 没有有效checkpoint时抛`langgraph_checkpoint_not_found`；
- `snapshot.next`非空时使用`graph.invoke(None, graph_config, context=...)`；
- `snapshot.next`为空时直接从`snapshot.values["answer"]`构造`AgentRunResult`。

模型配置、网关、trace和回调继续只放在`LangGraphRunContext`，不得进入状态。

- [ ] **Step 6: 将身份和恢复意图从路由传入**

在`extensions.py`构建引擎时传入`LANGGRAPH_CHECKPOINT_DB`。所有`engine.run()`调用都传入：

```python
user_id=user_id,
run_id=durable_run_id,
```

当`run_action == "resume"`、当前引擎为`langgraph`且任务没有公开计划步骤时，调用引擎并设置：

```python
resume_from_checkpoint=True
```

现有计划执行和`current`模式分支保持原样。

- [ ] **Step 7: 运行执行引擎测试**

Run: `python tests/check_agent_engine.py`

Run: `python tests/check_langgraph_agent_engine.py`

Expected: PASS。

- [ ] **Step 8: 提交执行引擎接入**

```powershell
git add backend/knowflow/services/agent_engine.py backend/knowflow/services/langgraph_agent_engine.py backend/knowflow/routers/extensions.py tests/check_agent_engine.py tests/check_langgraph_agent_engine.py tests/check_agent_run_api.py
git commit -m "feat: checkpoint langgraph agent runs"
```

### Task 4: 会话删除清理、文档和发布门禁

**Files:**
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/routers/chat.py`
- Modify: `README.md`
- Create: `tests/check_session_delete_checkpoint.py`
- Modify: `tests/check_release_hygiene.py`

**Interfaces:**
- Consumes: `LangGraphCheckpointStore.delete_threads(run_ids)`
- Produces: `runtime.langgraph_checkpoints: LangGraphCheckpointStore`

- [ ] **Step 1: 写会话删除清理失败测试**

在`tests/check_session_delete_checkpoint.py`创建两个用户、两个会话和各自的`agent_run`。为两个`run_id`写入checkpoint，然后调用用户A的删除会话接口并断言：

```python
assert checkpoint_for_user_a is None
assert checkpoint_for_user_b is not None
assert session_for_user_a is None
assert session_for_user_b is not None
```

再注入一个抛出`LangGraphCheckpointError`的删除器，断言用户A的业务会话和`agent_run`仍保留，接口返回安全错误且不暴露文件路径。

- [ ] **Step 2: 运行清理测试并确认失败**

Run: `python tests/check_session_delete_checkpoint.py`

Expected: FAIL，删除会话尚未清理checkpoint。

- [ ] **Step 3: 接入运行时checkpoint服务**

在`runtime.py`创建：

```python
langgraph_checkpoints = LangGraphCheckpointStore(
    LANGGRAPH_CHECKPOINT_DB
)
```

该构造不得创建目录或文件。

在`chat.delete_session()`完成用户校验和运行取消后、删除业务记录前调用：

```python
langgraph_checkpoints.delete_threads(
    [str(row["id"]) for row in run_rows]
)
```

删除失败时中止后续业务删除。

- [ ] **Step 4: 更新文档和发布卫生检查**

在README环境变量表加入`KNOWFLOW_LANGGRAPH_CHECKPOINT_DB`，并将LangGraph说明更新为“纯模型模式已支持SQLite checkpoint和用户主动恢复，尚未支持工具”。

在`tests/check_release_hygiene.py`的检查清单中加入新增专项测试，确保`data/langgraph`和SQLite文件没有被Git跟踪。

- [ ] **Step 5: 运行专项和全量测试**

Run: `python tests/check_session_delete_checkpoint.py`

Expected: PASS。

Run all checks in PowerShell:

```powershell
$tests = Get-ChildItem tests\check_*.py | Sort-Object Name
foreach ($test in $tests) {
    python $test.FullName
    if ($LASTEXITCODE -ne 0) { throw "Failed: $($test.Name)" }
}
```

Expected: 全部通过。

- [ ] **Step 6: 运行前端和发布门禁**

```powershell
npm run build --prefix frontend
git diff --check
git status --short
git ls-files backend/.env frontend/dist data
```

Expected:

- 前端构建成功；
- `git diff --check`无输出；
- 只出现预期源码和文档修改；
- `.env`、`frontend/dist`和`data`没有被Git跟踪；
- 搜索新增diff没有真实Token、Key或凭据。

- [ ] **Step 7: 提交文档与清理逻辑**

```powershell
git add backend/knowflow/runtime.py backend/knowflow/routers/chat.py README.md tests/check_session_delete_checkpoint.py tests/check_release_hygiene.py
git commit -m "feat: clean langgraph checkpoints with sessions"
```

## 最终验证

- [ ] `git status -sb`除既有未跟踪`.codegraph/`外保持干净。
- [ ] `git log -6 --oneline`显示设计、计划和阶段实现提交。
- [ ] `KNOWFLOW_AGENT_ENGINE=current`仍是默认值。
- [ ] 不push、不部署，除非用户明确要求。
