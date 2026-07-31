# Composer Model Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在聊天输入框内增加Codex式模型切换器，并让模型选择在当前会话、历史会话和新会话之间保持一致。

**Architecture:** 新增独立React组件监听现有模型目录与选择事件，通过既有`knowflow:react-chat-model-change`事件更新控制器状态。会话侧栏在打开历史会话时携带保存的模型ID，后端`ensure_session`在后续发送时同步会话模型字段，不新增模型目录API。

**Tech Stack:** React 18、原生CustomEvent桥接、FastAPI运行时服务、SQLAlchemy文本查询、项目现有`tests/check_*.py`契约测试。

---

## 文件结构

- Create: `frontend/react/src/components/ComposerModelPicker.jsx`，负责模型胶囊、弹层、键盘与空状态。
- Modify: `frontend/react/src/components/ChatComposerForm.jsx`，把模型选择器接入输入框。
- Modify: `frontend/react/src/components/Sidebar.jsx`，打开历史会话时携带会话模型ID。
- Modify: `frontend/react/src/controller/bridgeBindings.js`，校验并恢复历史会话模型选择。
- Modify: `backend/knowflow/runtime.py`，已有会话发送时同步模型字段。
- Modify: `frontend/styles.css`和生成目标，提供输入框模型胶囊与弹层样式。
- Create: `tests/check_frontend_composer_model_picker.py`，验证组件、事件、键盘、空状态和样式契约。
- Create: `tests/check_chat_session_model_selection.py`，验证会话模型同步与用户隔离。

### Task 1: 会话模型持久化

**Files:**
- Modify: `backend/knowflow/runtime.py:871-900`
- Create: `tests/check_chat_session_model_selection.py`

- [ ] **Step 1: 写失败测试**

测试使用独立SQLite数据库初始化两个用户，创建用户1的会话后再次调用`ensure_session`切换模型，断言：

```python
session_id = runtime.ensure_session(None, None, 11, alice_id)
runtime.ensure_session(session_id, None, 22, alice_id)
row = runtime.fetch_one(
    "SELECT chat_model_config_id FROM chat_session WHERE id=:id",
    {"id": session_id},
)
assert int(row["chat_model_config_id"]) == 22
```

同时使用用户2访问同一会话ID，断言返回404且不会改变用户1的会话模型。

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_chat_session_model_selection.py`

Expected: FAIL，现有`ensure_session`不会更新已存在会话的`chat_model_config_id`。

- [ ] **Step 3: 实现最小更新逻辑**

`ensure_session`查询现有会话时读取当前模型字段。已存在且请求带有不同模型ID时，执行限定用户的更新：

```python
execute(
    """
    UPDATE chat_session
    SET chat_model_config_id=:chat_model_config_id,
        updated_at=:updated_at
    WHERE id=:id AND user_id=:user_id
    """,
    {
        "chat_model_config_id": chat_model_config_id,
        "updated_at": now_str(),
        "id": final_id,
        "user_id": user_id,
    },
)
```

`chat_model_config_id=None`时保留原值。

- [ ] **Step 4: 验证后端测试**

Run: `py -3.13 tests/check_chat_session_model_selection.py && py -3.13 tests/check_user_isolation_and_tasks.py && py -3.13 tests/check_chat_streaming.py`

Expected: PASS。

### Task 2: 输入框模型选择组件

**Files:**
- Create: `frontend/react/src/components/ComposerModelPicker.jsx`
- Modify: `frontend/react/src/components/ChatComposerForm.jsx`
- Create: `tests/check_frontend_composer_model_picker.py`

- [ ] **Step 1: 写组件失败契约**

测试要求组件包含：

```python
require(component, "knowflow:react-model-options-updated")
require(component, "knowflow:react-model-selection-updated")
require(component, "knowflow:react-chat-model-change")
require(component, 'role={"listbox"}')
require(component, 'event.key === "ArrowDown"')
require(component, 'event.key === "Escape"')
require(component, "配置模型")
require(component, "管理模型")
require(composer, "ComposerModelPicker")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_frontend_composer_model_picker.py`

Expected: FAIL，组件文件不存在。

- [ ] **Step 3: 实现组件**

组件内部状态：

```jsx
const [models, setModels] = useState([]);
const [selectedModelId, setSelectedModelId] = useState("");
const [open, setOpen] = useState(false);
const [activeIndex, setActiveIndex] = useState(-1);
```

只保留`model.modelType === "chat"`。选择时派发：

```jsx
window.dispatchEvent(new CustomEvent("knowflow:react-chat-model-change", {
  detail: { value: String(model.id) },
}));
```

没有模型时点击胶囊派发`knowflow:react-page-change`到`settings`。弹层使用真实按钮和`listbox`语义，并处理方向键、Enter、Escape、外部点击和焦点恢复。

- [ ] **Step 4: 接入composer**

在`ChatComposerForm`导入组件，并在textarea下方渲染：

```jsx
<ComposerModelPicker disabled={sending} inputRef={textareaRef} />
```

保持发送、附件和Skill选择逻辑不变。

- [ ] **Step 5: 验证组件契约**

Run: `py -3.13 tests/check_frontend_composer_model_picker.py && py -3.13 tests/check_frontend_composer_input_react.py && py -3.13 tests/check_frontend_context_selection_react.py`

Expected: PASS。

### Task 3: 历史会话恢复模型

**Files:**
- Modify: `frontend/react/src/components/Sidebar.jsx:220-228`
- Modify: `frontend/react/src/controller/bridgeBindings.js:106-108`
- Modify: `tests/check_frontend_composer_model_picker.py`

- [ ] **Step 1: 扩展失败契约**

要求侧栏会话继续事件携带`chatModelConfigId`，桥接层使用现有解析器并通知React：

```python
require(sidebar, "chat_model_config_id")
require(sidebar, "chatModelConfigId")
require(bridge, "resolveChatModelConfigId")
require(bridge, "notifyReactModelSelectionUpdated")
require(chat_flow, "retryRequest?.payload?.chatModelConfigId")
```

最后一项保护消息重试继续使用原始请求模型，不被当前胶囊选择覆盖。

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_frontend_composer_model_picker.py`

Expected: FAIL，会话继续事件只有`sessionId`。

- [ ] **Step 3: 恢复模型选择**

`Sidebar`从当前会话对象读取`chat_model_config_id`并随事件发送。桥接层在调用`continueSession`前执行：

```javascript
const modelId = resolveChatModelConfigId(
  event.detail?.chatModelConfigId || "",
);
state.selectedChatModelConfigId = modelId;
notifyReactModelSelectionUpdated(modelId);
```

新建会话不清空`selectedChatModelConfigId`，保持最近选择。

- [ ] **Step 4: 验证会话与选择回归**

Run: `py -3.13 tests/check_frontend_composer_model_picker.py && py -3.13 tests/check_frontend_session_history_react.py && py -3.13 tests/check_frontend_active_session_react.py`

Expected: PASS。

### Task 4: 输入框样式与响应式

**Files:**
- Modify: `frontend/styles.css`
- Generated: `frontend/react/src/styles.css`
- Modify: `tests/check_frontend_composer_model_picker.py`

- [ ] **Step 1: 添加样式失败契约**

要求存在：

```text
.composer-model-trigger
.composer-model-popover
.composer-model-option
.composer-model-option.selected
@media (max-width: 520px)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `py -3.13 tests/check_frontend_composer_model_picker.py`

Expected: FAIL，缺少样式选择器。

- [ ] **Step 3: 实现视觉样式**

使用现有CSS变量：1px边框、正文级模型名、辅助提供商信息、当前项勾选。弹层绝对定位在输入框上方，桌面宽度约300px，520px以下限制为composer可用宽度。暗色主题使用现有`--panel-bg`、`--control-bg`和`--control-border`，不新增渐变或高饱和颜色。

- [ ] **Step 4: 同步样式并构建**

Run: `npm --prefix frontend run sync:assets && npm --prefix frontend run build`

Expected: Vite构建成功，模型选择器无JSX或CSS错误。

### Task 5: 浏览器与发布门禁

**Files:**
- Verify only

- [ ] **Step 1: 浏览器验收**

在桌面宽度和375px视口验证：胶囊显示当前模型、弹层向上展开、当前项勾选、切换后下一次请求使用新ID、生成期间禁用、历史会话恢复、无模型跳设置页、长模型名不溢出。

- [ ] **Step 2: 运行全部检查**

Run: 按文件名排序执行全部`tests/check_*.py`。

Expected: 全部通过。

- [ ] **Step 3: 运行前端发布门禁**

Run: `npm --prefix frontend ci && npm --prefix frontend audit --audit-level=high && npm --prefix frontend run build`

Expected: 依赖安装、0个高危漏洞、生产构建通过。

- [ ] **Step 4: 检查差异与敏感信息**

Run: `git diff --check`，检查未提交`.env`、数据库、上传文件、`frontend/dist`、`data/mem0`、Key或Token。

Expected: 无异常，`.codegraph/`不进入提交。

- [ ] **Step 5: 提交并推送**

```text
feat: add composer model selector
```

先`git fetch origin main`确认没有远端分叉，再推送`origin/main`。
