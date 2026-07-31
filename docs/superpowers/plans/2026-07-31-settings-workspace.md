# Settings Workspace Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模型设置页改为配置列表与详情双栏工作区，移除低频采样参数输入，并建立全局基础排版token。

**Architecture:** `SettingsPage`继续拥有API和工作区状态，`ModelListPanel`只负责选择配置，新增`ModelConfigDetails`负责只读详情与操作，`ModelConfigForm`负责右侧新建和编辑。温度、Top P和最大token数保留在表单状态与payload中，但不再渲染输入控件。

**Tech Stack:** React 18、原生CSS变量、现有`modelConfigApi`、Python源码契约检查、Vite。

---

## 文件结构

- Modify: `frontend/react/src/components/SettingsPage.jsx`，管理选中项、详情和表单模式。
- Modify: `frontend/react/src/components/SettingsHeader.jsx`，提供紧凑标题与新建操作。
- Modify: `frontend/react/src/components/ModelListPanel.jsx`，改为可选择的紧凑列表。
- Create: `frontend/react/src/components/ModelConfigDetails.jsx`，展示配置详情与相关操作。
- Modify: `frontend/react/src/components/ModelConfigForm.jsx`，移除低频输入并压缩字段。
- Delete: `frontend/react/src/components/SettingsSidePanel.jsx`，删除无作用的说明侧栏。
- Modify: `frontend/styles.css`，增加排版token与设置工作区样式。
- Sync: `frontend/react/src/styles.css`，由`npm run sync:assets`生成。
- Modify: `tests/check_frontend_model_settings_react.py`，覆盖新工作区、兼容参数和安全详情。
- Modify: `tests/check_frontend_professional.py`，确认基础排版token存在。

### Task 1: 建立失败的设置工作区契约

**Files:**
- Modify: `tests/check_frontend_model_settings_react.py`
- Modify: `tests/check_frontend_professional.py`

- [ ] **Step 1: 添加双栏工作区契约**

要求`SettingsPage.jsx`包含`selectedModelId`、`workspaceMode`和`ModelConfigDetails`，要求`ModelListPanel.jsx`包含`aria-selected`与`onModelSelect`，并禁止继续引用`SettingsSidePanel`。

```python
require(settings, "selectedModelId", "selected model state")
require(settings, "workspaceMode", "details and form mode")
require(settings, "ModelConfigDetails", "model details surface")
require(list_panel, "aria-selected", "accessible selected row")
require(list_panel, "onModelSelect", "model selection callback")
forbid(settings, "SettingsSidePanel", "obsolete settings note")
```

- [ ] **Step 2: 添加精简表单与兼容payload契约**

禁止表单渲染`temperature`、`topP`和`maxTokens`输入，同时保留`SettingsPage.jsx`的三个payload字段和旧配置读取逻辑。

```python
for field in ("temperature", "topP", "maxTokens"):
    forbid(form, f'name={{"{field}"}}', f"hidden {field} input")
    require(settings, f"{field}:", f"compatible {field} payload")
require(form, 'providerKey === "custom"', "custom-only provider identifier")
```

- [ ] **Step 3: 添加排版和响应式契约**

```python
for token in (
    "--font-size-page-title",
    "--font-size-body",
    "--control-height",
    ".settings-workspace-shell",
    ".model-config-details",
):
    require(styles, token, f"settings design token {token}")
```

- [ ] **Step 4: 运行测试确认失败**

Run:

```powershell
py -3.13 tests/check_frontend_model_settings_react.py
py -3.13 tests/check_frontend_professional.py
```

Expected: FAIL，缺少双栏组件、排版token或精简表单契约。

### Task 2: 实现配置选择与详情组件

**Files:**
- Modify: `frontend/react/src/components/ModelListPanel.jsx`
- Create: `frontend/react/src/components/ModelConfigDetails.jsx`

- [ ] **Step 1: 将配置列表改为选择器**

`ModelListPanel`接收`selectedModelId`和`onModelSelect`。每项使用真实按钮，展示配置名、模型名、协议、状态和默认标记。

```jsx
<button
  className={selected ? "model-config-item selected" : "model-config-item"}
  type={"button"}
  aria-selected={selected}
  onClick={() => onModelSelect(model.id)}
>
  <span className={"model-config-item-copy"}>...</span>
  <span className={"model-config-item-state"}>...</span>
</button>
```

- [ ] **Step 2: 新增只读详情组件**

`ModelConfigDetails`接收`model`、`busy`和四个操作回调。只渲染后端返回的脱敏密钥，不接收真实Key。

```jsx
export function ModelConfigDetails({
  model,
  busy = false,
  onDelete,
  onEdit,
  onSetDefault,
  onTest,
}) {
  if (!model) return <div className={"settings-detail-empty"}>...</div>;
  return (
    <section className={"model-config-details"}>
      <div className={"model-config-detail-actions"}>...</div>
      <dl className={"model-config-detail-grid"}>...</dl>
    </section>
  );
}
```

- [ ] **Step 3: 运行设置契约测试**

Run: `py -3.13 tests/check_frontend_model_settings_react.py`

Expected: 仍失败于`SettingsPage`尚未接线。

### Task 3: 精简配置表单并保留兼容参数

**Files:**
- Modify: `frontend/react/src/components/ModelConfigForm.jsx`

- [ ] **Step 1: 删除三个低频输入控件**

删除温度、Top P和最大token数对应的三个`label`，不改`formValues`结构。

- [ ] **Step 2: 只对自定义提供商显示标识输入**

```jsx
{providerKey === "custom" ? (
  <label>
    {"提供商标识"}
    <input name={"provider"} value={formValues.provider} required onChange={onFieldChange} />
  </label>
) : null}
```

- [ ] **Step 3: 调整表单容器语义**

表单使用`model-config-form`类，标题和保存/取消操作保持可访问，API密钥输入提示改为“留空则沿用现有密钥”或“输入API密钥”。

- [ ] **Step 4: 运行设置契约测试**

Run: `py -3.13 tests/check_frontend_model_settings_react.py`

Expected: 表单契约通过，工作区接线仍失败。

### Task 4: 接入双栏工作区状态

**Files:**
- Modify: `frontend/react/src/components/SettingsPage.jsx`
- Modify: `frontend/react/src/components/SettingsHeader.jsx`
- Delete: `frontend/react/src/components/SettingsSidePanel.jsx`

- [ ] **Step 1: 增加选择和模式状态**

```jsx
const [selectedModelId, setSelectedModelId] = useState(null);
const [workspaceMode, setWorkspaceMode] = useState("details");
```

`loadModels(preferredId)`优先保留指定或当前选择，其次选择默认聊天模型，最后选择第一项。

- [ ] **Step 2: 实现新建、选择、编辑和取消转换**

```jsx
const handleCreateModel = () => {
  setEditingModelId(null);
  setFormValues(formValuesFromPreset("deepseek", 0));
  setWorkspaceMode("form");
};

const handleModelSelect = (modelId) => {
  setSelectedModelId(modelId);
  setWorkspaceMode("details");
};
```

编辑加载成功后选择该配置并进入`form`，取消时回到`details`。

- [ ] **Step 3: 保存后回到详情且保持选择**

保存API返回的配置ID作为`preferredId`传给`loadModels`。现有`payloadFromFormValues`继续提交`temperature`、`topP`和`maxTokens`，编辑旧配置不会丢值。

- [ ] **Step 4: 增加删除确认和选择回退**

```jsx
if (!window.confirm(`删除“${model.name}”配置？`)) return;
```

删除成功后重新加载列表，当前项不存在时选择默认项或第一项。

- [ ] **Step 5: 组合工作区**

```jsx
<SettingsHeader onCreate={handleCreateModel} />
<div className={"settings-workspace-shell"}>
  <ModelListPanel ... />
  <div className={"settings-workspace-detail"}>
    {workspaceMode === "form" ? <ModelConfigForm ... /> : <ModelConfigDetails ... />}
  </div>
</div>
```

- [ ] **Step 6: 运行设置相关检查**

Run:

```powershell
py -3.13 tests/check_frontend_model_settings_react.py
py -3.13 tests/check_model_api_mode.py
py -3.13 tests/check_model_provider_presets.py
```

Expected: PASS。

### Task 5: 建立排版token和工作区样式

**Files:**
- Modify: `frontend/styles.css`
- Sync: `frontend/react/src/styles.css`

- [ ] **Step 1: 在当前主题变量中增加语义token**

```css
:root {
  --font-size-page-title: 26px;
  --font-size-section-title: 17px;
  --font-size-body: 14px;
  --font-size-meta: 12px;
  --line-height-body: 1.5;
  --control-height: 40px;
  --control-height-compact: 32px;
}
```

- [ ] **Step 2: 应用到框架与通用控件**

统一`.page-header h1`、`.settings-header h1`、侧栏导航、`button`、`input`和`select`的基础尺寸，避免覆盖聊天消息和代码块局部排版。

- [ ] **Step 3: 编写设置双栏样式**

为`.settings-workspace-shell`、`.model-config-list`、`.model-config-item`、`.model-config-details`、`.model-config-form`编写平整表面和分隔线样式。选中项使用左侧强调线，不使用厚边框。

- [ ] **Step 4: 编写900px和375px响应式规则**

900px以下改为上下布局，表单字段单列，操作按钮允许换行，列表和详情不产生横向滚动。

- [ ] **Step 5: 同步React样式**

Run: `npm --prefix frontend run sync:assets`

Expected: `frontend/react/src/styles.css`与`frontend/styles.css`一致。

- [ ] **Step 6: 运行样式与前端构建检查**

Run:

```powershell
py -3.13 tests/check_frontend_professional.py
npm --prefix frontend run build
```

Expected: PASS，Vite生产构建成功。

### Task 6: 回归验证与发布准备

**Files:**
- Verify only

- [ ] **Step 1: 运行受影响检查**

```powershell
py -3.13 tests/check_frontend_model_settings_react.py
py -3.13 tests/check_frontend_model_list_data_react.py
py -3.13 tests/check_frontend_option_fallbacks_react.py
py -3.13 tests/check_model_api_mode.py
py -3.13 tests/check_model_provider_presets.py
```

- [ ] **Step 2: 运行全部检查**

按文件名顺序运行所有`tests/check_*.py`，任何失败立即停止。

- [ ] **Step 3: 运行前端门禁**

```powershell
npm --prefix frontend ci
npm --prefix frontend audit --audit-level=high
npm --prefix frontend run build
```

- [ ] **Step 4: 运行Git与敏感信息检查**

执行`git diff --check`，确认不提交`backend/.env`、数据库、上传文件、`frontend/dist`、`data/mem0`、Key或Token。

- [ ] **Step 5: 提交实现**

```powershell
git add frontend/react/src/components/SettingsPage.jsx frontend/react/src/components/SettingsHeader.jsx frontend/react/src/components/ModelListPanel.jsx frontend/react/src/components/ModelConfigDetails.jsx frontend/react/src/components/ModelConfigForm.jsx frontend/react/src/components/SettingsSidePanel.jsx frontend/styles.css frontend/react/src/styles.css tests/check_frontend_model_settings_react.py tests/check_frontend_professional.py
git commit -m "feat: simplify model settings workspace"
```

- [ ] **Step 6: 用户要求Git同步时推送**

```powershell
git push origin main
```

Expected: 本地HEAD与`origin/main`一致，`.superpowers/`和`.codegraph/`不进入提交。
