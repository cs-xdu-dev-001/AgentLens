# LangGraph纯模型执行引擎实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增可通过全局环境变量启用的LangGraph纯模型执行引擎，同时保持现有Agent接口、模型网关、流式事件和默认`current`行为不变。

**Architecture:** 使用`StateGraph`建立`START → model → END`单节点图。图状态只保存消息和回答；模型配置、网关、trace和回调通过LangGraph运行时上下文传入。`agent_engine.py`继续承担引擎工厂职责，并仅在选择`langgraph`时延迟加载新实现。

**Tech Stack:** Python 3.10+、LangGraph 1.2.9、FastAPI、现有`ModelGateway`、`AgentTraceRecorder`、PowerShell 7、`tests/check_*.py`检查体系。

---

## 文件结构

- 创建`backend/knowflow/services/langgraph_agent_engine.py`：定义纯模型图状态、运行时上下文、模型节点和执行引擎。
- 修改`backend/knowflow/services/agent_engine.py`：延迟构造LangGraph引擎并提供明确的依赖不可用错误。
- 修改`backend/knowflow/config.py`：正式接受`langgraph`配置值，未知值仍回退`current`。
- 修改`backend/requirements.txt`：固定`langgraph==1.2.9`。
- 创建`tests/check_langgraph_agent_engine.py`：验证图结构、模型协议透传、流式回调、trace和失败路径。
- 修改`tests/check_agent_engine.py`：验证工厂能够选择LangGraph并保留当前执行器契约。
- 修改`tests/check_agent_engine_config.py`：验证环境变量可以选择LangGraph。
- 修改`backend/.env.example`和`README.md`：记录第3阶段能力和限制。

### Task 1：增加依赖和失败测试

**Files:**
- Modify: `backend/requirements.txt`
- Create: `tests/check_langgraph_agent_engine.py`
- Modify: `tests/check_agent_engine.py`
- Modify: `tests/check_agent_engine_config.py`

- [ ] **Step 1：固定并安装LangGraph依赖**

在`backend/requirements.txt`末尾增加：

```text
langgraph==1.2.9
```

Run:

```powershell
py -3.13 -m pip install langgraph==1.2.9
```

Expected：安装成功，`py -3.13 -c "import langgraph"`退出码为0。

- [ ] **Step 2：更新配置测试使LangGraph成为有效值**

将`tests/check_agent_engine_config.py`中的LangGraph断言改为：

```python
assert read_engine("langgraph") == "langgraph"
assert read_engine(" LANGGRAPH ") == "langgraph"
```

保留`typo`回退`current`的断言。

- [ ] **Step 3：增加工厂选择失败测试**

在`tests/check_agent_engine.py`中导入`LangGraphAgentEngine`，并将原来期待`langgraph`失败的分支替换为：

```python
langgraph_engine = build_agent_engine(
    "langgraph",
    gateway=FakeGateway(),
)
assert isinstance(langgraph_engine, LangGraphAgentEngine)
assert langgraph_engine.name == "langgraph"

try:
    build_agent_engine("unknown", gateway=FakeGateway())
    raise AssertionError("unsupported engine should fail explicitly")
except AgentEngineSelectionError as exc:
    assert exc.engine_name == "unknown"
```

- [ ] **Step 4：创建纯模型引擎契约测试**

创建`tests/check_langgraph_agent_engine.py`，测试代码必须覆盖：

```python
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.agent_trace import AgentTraceRecorder
from knowflow.services.langgraph_agent_engine import (
    LangGraphAgentEngine,
    LangGraphToolCallError,
)


class FakeGateway:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(
        self,
        messages,
        config,
        *,
        tools=None,
        tool_choice=None,
        event_callback=None,
    ):
        self.calls.append({
            "messages": messages,
            "config": config,
            "tools": tools,
            "tool_choice": tool_choice,
        })
        if event_callback:
            event_callback({"type": "text_delta", "text": "hello"})
        return self.response
```

主测试依次断言：普通回答为`hello`、`executions == []`、`tools is None`、`tool_choice is None`、Responses配置对象原样传入、模型事件透传、唯一trace步骤为成功的`model`且`details.engineName == "langgraph"`、注册工具的handler没有执行。随后分别用空内容和包含`tool_calls`的响应验证失败trace与`LangGraphToolCallError`。

- [ ] **Step 5：运行测试确认失败**

Run:

```powershell
py -3.13 tests/check_agent_engine_config.py
py -3.13 tests/check_agent_engine.py
py -3.13 tests/check_langgraph_agent_engine.py
```

Expected：至少因配置仍归一化为`current`、`LangGraphAgentEngine`尚不存在而失败。

### Task 2：实现纯模型LangGraph引擎

**Files:**
- Create: `backend/knowflow/services/langgraph_agent_engine.py`
- Modify: `backend/knowflow/services/agent_engine.py`
- Modify: `backend/knowflow/config.py`

- [ ] **Step 1：让配置接受LangGraph**

将`normalize_agent_engine_name()`实现改为：

```python
def normalize_agent_engine_name(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"current", "langgraph"}:
        return normalized
    return "current"
```

- [ ] **Step 2：实现图状态和运行时上下文**

在`backend/knowflow/services/langgraph_agent_engine.py`定义：

```python
from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .agent_loop import AgentRunResult, ToolExecution, ToolRegistry


class LangGraphState(TypedDict):
    messages: list[dict[str, Any]]
    answer: str


@dataclass(frozen=True)
class LangGraphRunContext:
    gateway: Any
    config: dict[str, Any] | None
    trace: Any = None
    parent_step_id: str | None = None
    model_event_callback: Callable[[dict[str, Any]], None] | None = None


class LangGraphToolCallError(RuntimeError):
    code = "langgraph_tools_not_supported"
```

- [ ] **Step 3：实现model节点和图编译**

`LangGraphAgentEngine.__init__()`保存网关，并构造：

```python
builder = StateGraph(
    LangGraphState,
    context_schema=LangGraphRunContext,
)
builder.add_node("model", self._call_model)
builder.add_edge(START, "model")
builder.add_edge("model", END)
self._graph = builder.compile()
```

`_call_model()`必须：创建现有格式的`model_completion` trace；在`details`中写入`modelName`、`apiMode`、`engineName`；调用`gateway.complete(..., tools=None, tool_choice=None)`；有回调时传入`event_callback`；任何`tool_calls`触发`LangGraphToolCallError`；空文本触发`ValueError`；成功时返回`{"answer": answer}`；所有失败路径先将trace标记为`failed`。

- [ ] **Step 4：实现AgentEngine契约转换**

`run()`接收与现有协议相同的全部关键字参数，调用：

```python
output = self._graph.invoke(
    {
        "messages": [dict(message) for message in messages],
        "answer": "",
    },
    context=LangGraphRunContext(
        gateway=self._gateway,
        config=config,
        trace=trace,
        parent_step_id=parent_step_id,
        model_event_callback=model_event_callback,
    ),
)
return AgentRunResult(
    answer=str(output["answer"]),
    executions=[],
    trace=trace.snapshot() if trace else [],
)
```

`registry`、`approval_gate`、`skill_snapshot`和`execution_callback`只为满足接口接收，不得使用。

- [ ] **Step 5：延迟加载LangGraph引擎**

在`agent_engine.py`中使用`importlib.import_module()`仅在`normalized == "langgraph"`时加载`.langgraph_agent_engine`并构造`LangGraphAgentEngine`。如果底层缺少`langgraph`包，转换为`AgentEngineUnavailableError("langgraph")`；其他导入异常原样抛出；未知引擎仍抛出`AgentEngineSelectionError`。

- [ ] **Step 6：运行专项测试**

Run:

```powershell
py -3.13 tests/check_agent_engine_config.py
py -3.13 tests/check_agent_engine.py
py -3.13 tests/check_langgraph_agent_engine.py
py -3.13 tests/check_agent_loop.py
```

Expected：4项全部PASS。

- [ ] **Step 7：提交核心实现**

Run:

```powershell
git add backend/requirements.txt backend/knowflow/config.py backend/knowflow/services/agent_engine.py backend/knowflow/services/langgraph_agent_engine.py tests/check_agent_engine.py tests/check_agent_engine_config.py tests/check_langgraph_agent_engine.py
git commit -m "feat: add model-only langgraph engine"
```

Expected：commit不包含`.codegraph/`和运行数据。

### Task 3：更新配置文档并验证路由兼容

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Verify: `tests/check_agent_engine_wiring.py`
- Verify: `tests/check_responses_streaming.py`

- [ ] **Step 1：更新环境变量示例**

将`KNOWFLOW_AGENT_ENGINE`注释改为：

```dotenv
# Agent execution engine: "current" or model-only "langgraph".
# Keep "current" for tools, MCP, Skills, approvals, and memory workflows.
KNOWFLOW_AGENT_ENGINE=current
```

- [ ] **Step 2：更新README配置表和说明**

将配置表说明改为“Agent execution engine: `current` or model-only `langgraph`”。将旧的“仅支持current”段落替换为：默认`current`保留全部能力；`langgraph`只支持普通模型问答，复用用户模型选择、Chat Completions、Responses API和流式输出；工具、MCP、Skills、审批、Mem0与checkpoint尚未迁移；未知值回退`current`。

- [ ] **Step 3：运行路由与协议回归**

Run:

```powershell
$checks = @(
  'tests/check_agent_engine_wiring.py',
  'tests/check_responses_streaming.py',
  'tests/check_agent_approval.py',
  'tests/check_task_planner.py',
  'tests/check_skill_runtime.py'
)
foreach ($check in $checks) {
  py -3.13 $check
  if ($LASTEXITCODE -ne 0) { throw "Regression failed: $check" }
}
```

Expected：5项全部PASS，现有路由和current执行器行为不变。

- [ ] **Step 4：提交文档**

Run:

```powershell
git add backend/.env.example README.md
git commit -m "docs: describe model-only langgraph mode"
```

### Task 4：执行完整发布门禁

**Files:**
- Verify: `tests/check_*.py`
- Verify: `frontend`
- Verify: Git index and diff

- [ ] **Step 1：运行全部后端检查**

Run:

```powershell
$checks = Get-ChildItem 'tests/check_*.py' | Sort-Object Name
foreach ($check in $checks) {
  Write-Host "RUN $($check.Name)"
  py -3.13 $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "Check failed: $($check.Name)" }
}
```

Expected：所有检查退出码为0；任一失败立即停止。

- [ ] **Step 2：运行前端生产构建**

Run：在`frontend`执行`npm run build`。

Expected：Vite构建成功；`frontend/dist`不进入Git。

- [ ] **Step 3：检查diff和禁止提交内容**

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
if ($forbidden) { throw "Forbidden runtime files are tracked." }
git status -sb
```

Expected：diff检查无输出；禁止列表为空；工作区仅允许未跟踪`.codegraph/`。

- [ ] **Step 4：核对提交历史**

Run:

```powershell
git log -5 --oneline
```

Expected：包含设计文档、实施计划、核心实现和配置文档的独立commit。验证通过后再由用户决定是否推送和部署。
