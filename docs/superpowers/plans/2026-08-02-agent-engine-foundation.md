# Agent Engine Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变现有Agent行为的前提下建立统一执行引擎接口，并让所有现有Agent请求默认通过`CurrentAgentEngine`运行。

**Architecture:** 新增独立的`agent_engine.py`，用`AgentEngine`协议描述执行入口，用`CurrentAgentEngine`包装现有`AgentRunner`。`extensions.py`只依赖执行引擎工厂；`KNOWFLOW_AGENT_ENGINE`当前只允许`current`，任何未知值都安全回落到`current`，LangGraph实现留到下一份计划。

**Tech Stack:** 服务器Python 3.10、本地`py -3.13`、FastAPI、现有`AgentRunner`与`ToolRegistry`、PowerShell 7、现有`tests/check_*.py`检查体系。

---

## 文件结构

- 创建`backend/knowflow/services/agent_engine.py`：定义执行引擎协议、当前执行器适配器和严格的构造工厂。
- 创建`tests/check_agent_engine.py`：验证当前适配器完整转发模型事件、工具结果、trace和回调。
- 修改`backend/knowflow/config.py`：解析`KNOWFLOW_AGENT_ENGINE`，当前阶段仅接受`current`。
- 创建`tests/check_agent_engine_config.py`：在隔离子进程中验证默认值、大小写和未知值回落。
- 修改`backend/knowflow/routers/extensions.py`：通过工厂创建执行引擎，不再直接实例化`AgentRunner`。
- 创建`tests/check_agent_engine_wiring.py`：用AST检查路由层只依赖执行引擎接口。
- 修改`backend/.env.example`和`README.md`：说明当前阶段的引擎开关和回退规则。

## Task 1：记录迁移前基线

**Files:**
- Verify: `tests/check_agent_loop.py`
- Verify: `tests/check_agent_approval.py`
- Verify: `tests/check_task_planner.py`
- Verify: `tests/check_skill_runtime.py`
- Verify: `tests/check_agent_run_store.py`
- Verify: `tests/check_responses_streaming.py`

- [ ] **Step 1：确认工作区和基线提交**

Run:

```powershell
Get-Location
git status -sb
git log -1 --oneline
```

Expected：目录为`C:\Users\z2986\Desktop\KnowFlow AI`；除已知的`.codegraph/`外没有其他未提交文件；HEAD包含已确认的迁移设计提交。

- [ ] **Step 2：运行现有Agent核心检查**

Run:

```powershell
$checks = @(
  'tests/check_agent_loop.py',
  'tests/check_agent_approval.py',
  'tests/check_task_planner.py',
  'tests/check_skill_runtime.py',
  'tests/check_agent_run_store.py',
  'tests/check_responses_streaming.py'
)
foreach ($check in $checks) {
  py -3.13 $check
  if ($LASTEXITCODE -ne 0) { throw "Baseline failed: $check" }
}
```

Expected：6个检查均以退出码0完成。任一失败都停止实施，不修改代码。

- [ ] **Step 3：确认前端基线可构建**

Run:

```powershell
npm run build
```

Workdir：`frontend`

Expected：Vite生产构建成功。此任务只记录基线，不产生commit。

## Task 2：建立当前执行器适配器

**Files:**
- Create: `backend/knowflow/services/agent_engine.py`
- Create: `tests/check_agent_engine.py`

- [ ] **Step 1：写失败的执行引擎契约测试**

Create `tests/check_agent_engine.py`:

```python
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_engine import (
    AgentEngineSelectionError,
    CurrentAgentEngine,
    build_agent_engine,
)
from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder


class FakeGateway:
    def __init__(self):
        self.round = 0

    def complete(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        self.round += 1
        if self.round == 1:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_echo_1",
                        "type": "function",
                        "function": {
                            "name": "echo",
                            "arguments": '{"text":"hello"}',
                        },
                    }
                ],
            }
        if event_callback:
            event_callback({"type": "text_delta", "text": "done"})
        return {
            "role": "assistant",
            "content": "done",
            "tool_calls": [],
        }


def main() -> None:
    registry = ToolRegistry()
    registry.register(
        name="echo",
        description="Echo text.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        handler=lambda arguments: {"text": arguments["text"]},
    )
    trace = AgentTraceRecorder(run_id="run_engine_contract")
    executions = []
    model_events = []
    engine = build_agent_engine(
        "current",
        gateway=FakeGateway(),
        max_tool_rounds=3,
    )

    assert isinstance(engine, CurrentAgentEngine)
    assert engine.name == "current"
    result = engine.run(
        messages=[{"role": "user", "content": "Echo hello"}],
        config={"model_name": "fake"},
        registry=registry,
        trace=trace,
        parent_step_id="step_root",
        execution_callback=lambda execution, parent_id: executions.append(
            (execution, parent_id)
        ),
        model_event_callback=model_events.append,
    )

    assert result.answer == "done"
    assert len(result.executions) == 1
    assert result.executions[0].tool_name == "echo"
    assert executions[0][0] is result.executions[0]
    assert model_events == [{"type": "text_delta", "text": "done"}]
    assert result.trace == trace.snapshot()
    assert [step["kind"] for step in result.trace] == [
        "model",
        "tool",
        "model",
    ]

    try:
        build_agent_engine("langgraph", gateway=FakeGateway())
        raise AssertionError("unsupported engine should fail explicitly")
    except AgentEngineSelectionError as exc:
        assert exc.engine_name == "langgraph"

    print("current agent engine preserves the existing runner contract")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2：运行测试并确认缺少模块**

Run:

```powershell
py -3.13 tests/check_agent_engine.py
```

Expected：FAIL，错误包含`No module named 'knowflow.services.agent_engine'`。

- [ ] **Step 3：实现最小执行引擎接口和当前适配器**

Create `backend/knowflow/services/agent_engine.py`:

```python
from __future__ import annotations

from typing import Any, Callable, Protocol

from .agent_loop import (
    AgentRunResult,
    AgentRunner,
    ToolExecution,
    ToolRegistry,
)


ExecutionCallback = Callable[[ToolExecution, str | None], None]
ModelEventCallback = Callable[[dict[str, Any]], None]


class AgentEngine(Protocol):
    name: str

    def run(
        self,
        *,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        approval_gate=None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback: ExecutionCallback | None = None,
        model_event_callback: ModelEventCallback | None = None,
    ) -> AgentRunResult:
        ...


class AgentEngineSelectionError(ValueError):
    def __init__(self, engine_name: str):
        self.engine_name = engine_name
        super().__init__(f"Unsupported Agent engine: {engine_name}")


class CurrentAgentEngine:
    name = "current"

    def __init__(self, *, gateway, max_tool_rounds: int = 3):
        self._runner = AgentRunner(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
        )

    def run(
        self,
        *,
        messages,
        config,
        registry: ToolRegistry,
        trace=None,
        parent_step_id: str | None = None,
        approval_gate=None,
        skill_snapshot: dict[str, Any] | None = None,
        execution_callback: ExecutionCallback | None = None,
        model_event_callback: ModelEventCallback | None = None,
    ) -> AgentRunResult:
        return self._runner.run(
            messages=messages,
            config=config,
            registry=registry,
            trace=trace,
            parent_step_id=parent_step_id,
            approval_gate=approval_gate,
            skill_snapshot=skill_snapshot,
            execution_callback=execution_callback,
            model_event_callback=model_event_callback,
        )


def build_agent_engine(
    engine_name: str,
    *,
    gateway,
    max_tool_rounds: int = 3,
) -> AgentEngine:
    normalized = str(engine_name or "").strip().lower()
    if normalized == "current":
        return CurrentAgentEngine(
            gateway=gateway,
            max_tool_rounds=max_tool_rounds,
        )
    raise AgentEngineSelectionError(normalized or "unknown")
```

- [ ] **Step 4：运行新契约测试和原循环测试**

Run:

```powershell
py -3.13 tests/check_agent_engine.py
py -3.13 tests/check_agent_loop.py
```

Expected：两项均PASS；适配器的answer、工具执行、模型事件和trace与当前`AgentRunner`一致。

- [ ] **Step 5：提交执行器适配器**

Run:

```powershell
git add backend/knowflow/services/agent_engine.py tests/check_agent_engine.py
git commit -m "refactor: add current agent engine adapter"
```

Expected：commit只包含上述两个文件，不包含`.codegraph/`。

## Task 3：增加安全的引擎配置

**Files:**
- Modify: `backend/knowflow/config.py:41-45,129-131`
- Create: `tests/check_agent_engine_config.py`

- [ ] **Step 1：写失败的配置隔离测试**

Create `tests/check_agent_engine_config.py`:

```python
from pathlib import Path
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def read_engine(value: str) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    env["KNOWFLOW_AGENT_ENGINE"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from knowflow.config import AGENT_ENGINE; print(AGENT_ENGINE)",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().splitlines()[-1]


assert read_engine("") == "current"
assert read_engine("current") == "current"
assert read_engine("CURRENT") == "current"
assert read_engine("langgraph") == "current"
assert read_engine("typo") == "current"

print("agent engine configuration defaults safely to current")
```

- [ ] **Step 2：运行测试并确认配置尚不存在**

Run:

```powershell
py -3.13 tests/check_agent_engine_config.py
```

Expected：FAIL，子进程错误表明`AGENT_ENGINE`尚未定义。

- [ ] **Step 3：实现配置归一化**

Add after `env_float()` in `backend/knowflow/config.py`:

```python
def normalize_agent_engine_name(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "current":
        return normalized
    return "current"
```

Add after `MODEL_TRUST_ENV`:

```python
AGENT_ENGINE = normalize_agent_engine_name(
    os.getenv("KNOWFLOW_AGENT_ENGINE", "current")
)
```

当前阶段故意不接受`langgraph`。这样即使服务器提前写入错误值，也只会继续使用当前执行器，不会让服务启动失败。

- [ ] **Step 4：运行配置测试**

Run:

```powershell
py -3.13 tests/check_agent_engine_config.py
py -3.13 tests/check_runtime_split_and_upload_limits.py
```

Expected：两项均PASS。

- [ ] **Step 5：提交配置开关**

Run:

```powershell
git add backend/knowflow/config.py tests/check_agent_engine_config.py
git commit -m "refactor: add safe agent engine setting"
```

Expected：commit只包含配置解析和隔离测试。

## Task 4：让现有请求通过执行引擎接口

**Files:**
- Modify: `backend/knowflow/routers/extensions.py:11,794-926`
- Create: `tests/check_agent_engine_wiring.py`

- [ ] **Step 1：写失败的路由接线检查**

Create `tests/check_agent_engine_wiring.py`:

```python
from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
source = EXTENSIONS.read_text(encoding="utf-8")
tree = ast.parse(source)

agent_loop_imports = set()
agent_engine_imports = set()
for node in ast.walk(tree):
    if isinstance(node, ast.ImportFrom) and node.module == "services.agent_loop":
        agent_loop_imports.update(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom) and node.module == "services.agent_engine":
        agent_engine_imports.update(alias.name for alias in node.names)

factory_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "build_agent_engine"
]
engine_run_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Attribute)
    and isinstance(node.func.value, ast.Name)
    and node.func.value.id == "engine"
    and node.func.attr == "run"
]

assert "ToolRegistry" in agent_loop_imports
assert "AgentRunner" not in agent_loop_imports
assert "build_agent_engine" in agent_engine_imports
assert len(factory_calls) == 1
assert len(engine_run_calls) == 2
assert "AGENT_ENGINE" in source

print("agent routes depend on the engine interface")
```

- [ ] **Step 2：运行测试并确认路由仍直接依赖AgentRunner**

Run:

```powershell
py -3.13 tests/check_agent_engine_wiring.py
```

Expected：FAIL，至少包含`AgentRunner`仍在导入或`build_agent_engine`不存在。

- [ ] **Step 3：替换路由导入**

Replace in `backend/knowflow/routers/extensions.py`:

```python
from ..services.agent_loop import AgentRunner, ToolRegistry
```

with:

```python
from ..services.agent_engine import build_agent_engine
from ..services.agent_loop import ToolRegistry
```

- [ ] **Step 4：通过工厂创建当前执行器**

Replace the runner construction near line 794:

```python
runner = AgentRunner(
    gateway=_CancellationAwareGateway(
        gateway,
        cancel_event,
    ),
    max_tool_rounds=3,
)
```

with:

```python
engine = build_agent_engine(
    AGENT_ENGINE,
    gateway=_CancellationAwareGateway(
        gateway,
        cancel_event,
    ),
    max_tool_rounds=3,
)
```

Replace both calls in the same function:

```python
run_result = runner.run(
```

and:

```python
step_result = runner.run(
```

with:

```python
run_result = engine.run(
```

and:

```python
step_result = engine.run(
```

Do not change any argument, callback, exception branch, trace operation or plan-step logic.

- [ ] **Step 5：运行结构检查和行为回归**

Run:

```powershell
$checks = @(
  'tests/check_agent_engine_wiring.py',
  'tests/check_agent_engine.py',
  'tests/check_agent_loop.py',
  'tests/check_agent_approval.py',
  'tests/check_task_planner.py',
  'tests/check_skill_runtime.py',
  'tests/check_responses_streaming.py'
)
foreach ($check in $checks) {
  py -3.13 $check
  if ($LASTEXITCODE -ne 0) { throw "Engine wiring failed: $check" }
}
```

Expected：7项全部PASS，审批、任务计划、Skills和Responses流式行为不变。

- [ ] **Step 6：提交路由接线**

Run:

```powershell
git add backend/knowflow/routers/extensions.py tests/check_agent_engine_wiring.py
git commit -m "refactor: route agent runs through engine interface"
```

Expected：commit不包含工具、MCP、审批、Mem0或前端行为修改。

## Task 5：记录配置并执行完整门禁

**Files:**
- Modify: `backend/.env.example:52-53`
- Modify: `README.md:177-217`

- [ ] **Step 1：更新环境变量示例**

Replace the Agent task-state comment in `backend/.env.example` with:

```dotenv
# Agent execution engine. Phase 1 supports only "current"; unknown values
# safely fall back to current until the LangGraph engine is implemented.
KNOWFLOW_AGENT_ENGINE=current

# Agent task state is persisted in the database, but active execution is process-local.
# Run one backend worker; after a service restart, users resume interrupted tasks manually.
```

- [ ] **Step 2：将引擎开关加入README环境变量表**

Insert after the `KNOWFLOW_SECRET_KEY` row in `README.md`:

```markdown
| `KNOWFLOW_AGENT_ENGINE` | Agent execution engine; phase 1 supports only `current` | `current` |
```

- [ ] **Step 3：更新README运行说明**

Insert after the current Agent execution and restart paragraph in `README.md`:

```markdown
The backend now routes Agent requests through an internal execution-engine interface. `KNOWFLOW_AGENT_ENGINE=current` remains the only enabled engine in this phase and preserves the existing `AgentRunner` behavior. Unknown values fall back to `current`; LangGraph is not enabled until its own model-only implementation and tests land in a later phase.
```

- [ ] **Step 4：运行全部后端检查**

Run:

```powershell
$checks = Get-ChildItem 'tests/check_*.py' | Sort-Object Name
foreach ($check in $checks) {
  Write-Host "RUN $($check.Name)"
  py -3.13 $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "Check failed: $($check.Name)" }
}
```

Expected：全部检查按文件名顺序通过；任一失败立即停止，不继续构建或提交。

- [ ] **Step 5：运行前端生产构建**

Run:

```powershell
npm run build
```

Workdir：`frontend`

Expected：Vite生产构建成功。由于本阶段不改前端，构建产物不得加入Git。

- [ ] **Step 6：检查diff和禁止提交内容**

Run:

```powershell
git diff --check
$tracked = git ls-files
$forbidden = $tracked | Where-Object {
  $_ -eq 'backend/.env' -or
  $_ -match '^data/' -or
  $_ -match '^backend/(data|uploads)/' -or
  $_ -match '\.(db|sqlite|sqlite3)$' -or
  $_ -match '^frontend/dist/'
}
if ($forbidden) {
  $forbidden | ForEach-Object { Write-Host $_ }
  throw 'Forbidden runtime files are tracked.'
}
git status -sb
```

Expected：`git diff --check`无输出；禁止列表为空；`.codegraph/`仍为未跟踪且没有进入暂存区。

- [ ] **Step 7：提交文档**

Run:

```powershell
git add backend/.env.example README.md
git commit -m "docs: describe current agent engine setting"
git status -sb
```

Expected：实现阶段形成4个小commit；工作区除`.codegraph/`外无未提交修改。此时仍未安装LangGraph，线上默认行为不变。
