# Frontend Deep Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变KnowFlow AI现有信息架构和黑白视觉方向的前提下，统一前端排版、控件、运行面板、管理页面和响应式体验。

**Architecture:** 保留现有React组件和`frontend/styles.css`兼容层，新增一个职责明确的`frontend/refinement.css`作为规范化样式源，并由现有同步脚本复制到React源码后最后导入。功能行为继续由现有组件负责；只在运行状态语义和可访问性确有缺口时做最小JSX修改。

**Tech Stack:** React 18、原生CSS、Vite、Python静态契约检查、现有`tests/check_*.py`发布门禁。

---

## File Structure

- Create `frontend/refinement.css`: 当前设计规范的唯一精修层，包含基础token、通用控件、聊天、运行面板、设置、管理页面和响应式规则。
- Modify `frontend/scripts/sync-assets.mjs`: 同步`refinement.css`到React源码。
- Create `frontend/react/src/refinement.css`: 由同步脚本生成并参与构建，不手工维护。
- Modify `frontend/react/src/main.jsx`: 在兼容样式之后导入精修层。
- Modify `frontend/react/src/components/ChatEvidenceDrawer.jsx`: 为运行状态区域补充实时播报语义。
- Modify `frontend/react/src/components/AgentTraceView.jsx`: 为当前步骤和展开详情补充稳定状态语义。
- Modify `frontend/react/src/components/SettingsPage.jsx`: 只保留兼容参数，不重新暴露温度和Top P。
- Modify `frontend/react/src/components/ModelConfigForm.jsx`: 保持必要字段的紧凑表单结构。
- Modify `frontend/react/src/components/SkillsPage.jsx`: 统一列表状态与行级操作语义。
- Modify `frontend/react/src/components/MemoryPage.jsx`: 统一记忆列表状态与更新时间显示语义。
- Modify `frontend/react/src/components/ToolsPage.jsx`: 统一工具概览和MCP工作区结构。
- Create `tests/check_frontend_refinement_system.py`: 检查规范层同步、导入顺序、关键token、页面覆盖和禁止项。

### Task 1: 建立精修样式源和同步契约

**Files:**
- Create: `tests/check_frontend_refinement_system.py`
- Create: `frontend/refinement.css`
- Modify: `frontend/scripts/sync-assets.mjs`
- Modify: `frontend/react/src/main.jsx`

- [ ] **Step 1: 写入失败的样式源契约测试**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    source = read("frontend/refinement.css")
    main_js = read("frontend/react/src/main.jsx")
    sync = read("frontend/scripts/sync-assets.mjs")
    assert '["refinement.css", "react/src/refinement.css"]' in sync
    assert 'import "./refinement.css";' in main_js
    assert main_js.index('import "./styles.css";') < main_js.index('import "./refinement.css";')
    for token in (
        "--kf-type-page",
        "--kf-type-title",
        "--kf-type-body",
        "--kf-radius-control",
        "--kf-space-4",
        "/* KnowFlow refinement: foundation */",
    ):
        assert token in source, f"missing refinement token: {token}"
    print("frontend refinement system is wired")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示`frontend/refinement.css`不存在。

- [ ] **Step 3: 添加样式源、同步和导入**

```js
// frontend/scripts/sync-assets.mjs
const assets = [
  ["styles.css", "react/src/styles.css"],
  ["refinement.css", "react/src/refinement.css"],
];
```

```js
// frontend/react/src/main.jsx
import "./styles.css";
import "./refinement.css";
```

```css
/* frontend/refinement.css */
/* KnowFlow refinement: foundation */
:root {
  --kf-type-page: 28px;
  --kf-type-title: 18px;
  --kf-type-body: 16px;
  --kf-type-label: 14px;
  --kf-radius-control: 10px;
  --kf-radius-panel: 14px;
  --kf-space-1: 4px;
  --kf-space-2: 8px;
  --kf-space-3: 12px;
  --kf-space-4: 16px;
  --kf-space-6: 24px;
  --kf-space-8: 32px;
}
```

- [ ] **Step 4: 同步并确认契约通过**

Run: `cd frontend; npm run sync:styles; cd ..; python tests/check_frontend_refinement_system.py`

Expected: PASS，输出`frontend refinement system is wired`。

- [ ] **Step 5: 提交**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css frontend/react/src/main.jsx frontend/scripts/sync-assets.mjs tests/check_frontend_refinement_system.py
git commit -m "refactor: establish frontend refinement layer"
```

### Task 2: 收敛全局排版、控件和工作区密度

**Files:**
- Modify: `tests/check_frontend_refinement_system.py`
- Modify: `frontend/refinement.css`

- [ ] **Step 1: 扩充失败的基础视觉契约**

在测试的token循环后增加：

```python
    for token in (
        "/* KnowFlow refinement: shell and controls */",
        "body {",
        ":focus-visible",
        ".workspace-page",
        ".settings-header",
        ".icon-button",
        ".secondary-button",
    ):
        assert token in source, f"missing foundation rule: {token}"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示缺少`shell and controls`规则。

- [ ] **Step 3: 写入统一基础规则**

```css
/* KnowFlow refinement: shell and controls */
body {
  font-size: var(--kf-type-body);
  line-height: 1.6;
  text-rendering: optimizeLegibility;
}

:where(button, input, textarea, select, [tabindex]):focus-visible {
  outline: 2px solid var(--text);
  outline-offset: 2px;
}

.workspace-page {
  min-height: 100vh;
  background: var(--workspace-bg);
  color: var(--text);
}

.settings-header {
  min-height: 72px;
  padding: 0 var(--kf-space-6);
  border-bottom: 1px solid var(--control-border);
}

.settings-header h1 {
  margin: 0;
  font-size: var(--kf-type-page);
  line-height: 1.25;
  letter-spacing: -0.02em;
}

.icon-button,
.secondary-button {
  min-height: 38px;
  border: 1px solid var(--control-border);
  border-radius: var(--kf-radius-control);
  background: var(--control-bg);
  box-shadow: none;
}
```

- [ ] **Step 4: 运行契约和现有专业度检查**

Run: `python tests/check_frontend_refinement_system.py; python tests/check_frontend_professional.py`

Expected: 两项均PASS。

- [ ] **Step 5: 提交**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css tests/check_frontend_refinement_system.py
git commit -m "style: unify workspace typography and controls"
```

### Task 3: 精修聊天输入框和运行面板

**Files:**
- Modify: `tests/check_frontend_refinement_system.py`
- Modify: `frontend/refinement.css`
- Modify: `frontend/react/src/components/ChatEvidenceDrawer.jsx`
- Modify: `frontend/react/src/components/AgentTraceView.jsx`

- [ ] **Step 1: 写入失败的聊天与轨迹契约**

```python
    drawer = read("frontend/react/src/components/ChatEvidenceDrawer.jsx")
    trace = read("frontend/react/src/components/AgentTraceView.jsx")
    assert 'aria-live={"polite"}' in drawer
    assert 'aria-atomic={"true"}' in drawer
    assert 'aria-label={"Agent运行步骤"}' in trace
    for token in (
        "/* KnowFlow refinement: composer */",
        "/* KnowFlow refinement: run drawer */",
        ".composer-shell",
        ".composer-model-popover",
        ".agent-trace-node",
        ".agent-trace-step-detail",
    ):
        assert token in source, f"missing chat refinement: {token}"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示运行摘要缺少实时播报语义或精修规则。

- [ ] **Step 3: 补充最小实时状态语义**

```jsx
<aside className={"evidence-drawer"} id={"evidence-drawer"}>
  <div className={"drawer-header"} aria-live={"polite"} aria-atomic={"true"}>
    <AgentRunSummary trace={trace} run={run} />
    <button
      className={"icon-button"}
      id={"inspector-close"}
      type={"button"}
      title={"收起运行面板"}
      aria-label={"收起运行面板"}
      onClick={handleDrawerClose}
    >
      <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
        <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
      </svg>
    </button>
  </div>
</aside>
```

- [ ] **Step 4: 收敛输入框和运行轨迹样式**

```css
/* KnowFlow refinement: composer */
#chat-form.composer .composer-shell {
  border: 1px solid var(--control-border) !important;
  border-radius: 18px !important;
  background: var(--panel-bg) !important;
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.06) !important;
}

#chat-form.composer textarea {
  color: var(--text);
  font-size: 15px !important;
  line-height: 24px !important;
}

/* KnowFlow refinement: run drawer */
.evidence-drawer {
  border-left: 1px solid var(--control-border);
  background: var(--panel-bg);
}

.agent-trace-node {
  min-height: 64px;
  border-radius: var(--kf-radius-panel);
  padding: 11px 12px;
}

.agent-trace-node.selected {
  border-color: var(--line-strong);
  background: var(--panel-bg-soft);
}

.agent-trace-step-detail {
  margin: 4px 0 10px;
  border: 1px solid var(--control-border);
  border-radius: var(--kf-radius-panel);
  background: var(--panel-bg-soft);
  padding: var(--kf-space-4);
}
```

- [ ] **Step 5: 运行聊天相关检查**

Run: `python tests/check_frontend_refinement_system.py; python tests/check_frontend_composer_compact_layout.py; python tests/check_frontend_composer_model_picker.py; python tests/check_frontend_evidence_drawer_react.py; python tests/check_frontend_agent_trace_react.py`

Expected: 全部PASS。

- [ ] **Step 6: 提交**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css frontend/react/src/components/ChatEvidenceDrawer.jsx frontend/react/src/components/AgentTraceView.jsx tests/check_frontend_refinement_system.py
git commit -m "style: clarify composer and agent run details"
```

### Task 4: 精修设置页和已保存模型列表

**Files:**
- Modify: `tests/check_frontend_refinement_system.py`
- Modify: `frontend/refinement.css`
- Modify: `frontend/react/src/components/ModelConfigForm.jsx`

- [ ] **Step 1: 写入失败的设置页契约**

```python
    form = read("frontend/react/src/components/ModelConfigForm.jsx")
    for field in ('name={"temperature"}', 'name={"topP"}'):
        assert field not in form, f"non-essential field returned: {field}"
    for token in (
        "/* KnowFlow refinement: settings */",
        ".settings-workspace-shell",
        ".model-config-item",
        ".model-config-details",
        ".model-config-form",
    ):
        assert token in source, f"missing settings refinement: {token}"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示缺少设置精修规则。

- [ ] **Step 3: 收敛设置工作区**

```css
/* KnowFlow refinement: settings */
.settings-workspace-shell {
  grid-template-columns: 300px minmax(0, 1fr);
  margin: 20px 24px 24px;
  border: 1px solid var(--control-border);
  border-radius: var(--kf-radius-panel);
  box-shadow: none;
}

.model-config-item {
  min-height: 76px;
  padding: 11px 12px;
}

.model-config-details,
.model-config-form {
  gap: 18px;
  padding: 22px 24px 26px;
}

.model-config-detail-grid > div {
  padding: 12px 0;
}
```

- [ ] **Step 4: 运行设置相关检查**

Run: `python tests/check_frontend_refinement_system.py; python tests/check_frontend_model_settings_react.py; python tests/check_frontend_model_list_data_react.py`

Expected: 全部PASS。

- [ ] **Step 5: 提交**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css frontend/react/src/components/ModelConfigForm.jsx tests/check_frontend_refinement_system.py
git commit -m "style: simplify model settings workspace"
```

### Task 5: 统一知识库、Skills、记忆和MCP管理页面

**Files:**
- Modify: `tests/check_frontend_refinement_system.py`
- Modify: `frontend/refinement.css`
- Modify: `frontend/react/src/components/KnowledgePage.jsx`
- Modify: `frontend/react/src/components/SkillsPage.jsx`
- Modify: `frontend/react/src/components/MemoryPage.jsx`
- Modify: `frontend/react/src/components/ToolsPage.jsx`

- [ ] **Step 1: 写入失败的管理页面契约**

```python
    for token in (
        "/* KnowFlow refinement: management pages */",
        "#page-knowledge",
        "#page-skills",
        "#page-memory",
        "#page-tools",
        ".skills-list-row",
        ".memory-item",
        ".mcp-server-card",
    ):
        assert token in source, f"missing management refinement: {token}"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示缺少管理页面精修规则。

- [ ] **Step 3: 写入统一管理页面规则**

```css
/* KnowFlow refinement: management pages */
:where(#page-knowledge, #page-skills, #page-memory, #page-tools) .workspace-page {
  background: var(--workspace-bg);
}

:where(.knowledge-tabbar, .skills-tabs, .memory-toolbar) {
  min-height: 48px;
  border-bottom: 1px solid var(--control-border);
}

:where(.skills-list-row, .memory-item, .mcp-server-card) {
  border: 0;
  border-bottom: 1px solid var(--control-border);
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

:where(.skills-list-row, .memory-item, .mcp-server-card):hover {
  background: var(--control-bg-hover);
}

:where(.skills-list-state, .memory-empty, .empty-state) {
  color: var(--muted);
  font-size: var(--kf-type-body);
}
```

- [ ] **Step 4: 运行管理页面检查**

Run: `python tests/check_frontend_refinement_system.py; python tests/check_frontend_knowledge_list_react.py; python tests/check_frontend_skills_page_react.py; python tests/check_frontend_memory_react.py; python tests/check_frontend_mcp_settings_react.py; python tests/check_frontend_tool_settings_react.py`

Expected: 全部PASS。

- [ ] **Step 5: 提交**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css frontend/react/src/components/KnowledgePage.jsx frontend/react/src/components/SkillsPage.jsx frontend/react/src/components/MemoryPage.jsx frontend/react/src/components/ToolsPage.jsx tests/check_frontend_refinement_system.py
git commit -m "style: unify agent management workspaces"
```

### Task 6: 响应式、无障碍、全量验证和发布

**Files:**
- Modify: `tests/check_frontend_refinement_system.py`
- Modify: `frontend/refinement.css`

- [ ] **Step 1: 写入失败的响应式契约**

```python
    for token in (
        "/* KnowFlow refinement: responsive */",
        "@media (max-width: 1180px)",
        "@media (max-width: 900px)",
        "@media (max-width: 720px)",
        "@media (prefers-reduced-motion: reduce)",
    ):
        assert token in source, f"missing responsive rule: {token}"
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `python tests/check_frontend_refinement_system.py`

Expected: FAIL，提示缺少响应式规则。

- [ ] **Step 3: 完成响应式和减少动效规则**

```css
/* KnowFlow refinement: responsive */
@media (max-width: 1180px) {
  :root { --drawer-width: min(380px, 38vw); }
}

@media (max-width: 900px) {
  .settings-workspace-shell { grid-template-columns: minmax(0, 1fr); }
  .model-config-list { max-height: 300px; border-right: 0; }
}

@media (max-width: 720px) {
  .settings-header { min-height: 64px; padding-inline: 16px; }
  .settings-header h1 { font-size: 24px; }
  .settings-workspace-shell { margin: 12px 14px 18px; }
  .agent-trace-node { grid-template-columns: 8px 44px minmax(0, 1fr); }
  .agent-trace-node-time { grid-column: 3; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 4: 同步并运行所有静态检查**

Run:

```powershell
Push-Location frontend
npm run sync:styles
Pop-Location
$checks = Get-ChildItem tests/check_*.py | Sort-Object Name
foreach ($check in $checks) {
  python $check.FullName
  if ($LASTEXITCODE -ne 0) { throw "Failed: $($check.Name)" }
}
```

Expected: 所有`check_*.py`均以0退出。

- [ ] **Step 5: 构建并执行代码卫生检查**

Run:

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
git diff --check
node C:\Users\z2986\.codex\skills\impeccable\scripts\detect.mjs --json frontend/refinement.css frontend/react/src/components/ChatComposerForm.jsx frontend/react/src/components/ChatEvidenceDrawer.jsx frontend/react/src/components/SettingsPage.jsx frontend/react/src/components/SkillsPage.jsx frontend/react/src/components/MemoryPage.jsx frontend/react/src/components/ToolsPage.jsx
```

Expected: 构建成功，`git diff --check`无输出，检测器没有需要修复的高置信问题。

- [ ] **Step 6: 浏览器视觉验收**

在1440px、1180px、900px和390px宽度检查：

- 聊天空状态、长回答、代码块、模型选择和Skill选择。
- 运行面板的等待、运行、完成、失败、审批和展开详情。
- 设置页列表、详情、新建和编辑。
- 知识库、Skills、记忆、工具与MCP的加载、空、成功和失败状态。
- 键盘Tab顺序、焦点环、Escape关闭和暗色主题。

Expected: 不改变现有结构，无横向溢出，无核心信息依赖低对比小字，移动端核心操作可完成。

- [ ] **Step 7: 最终提交并推送**

```powershell
git add frontend/refinement.css frontend/react/src/refinement.css frontend/react/src/main.jsx frontend/scripts/sync-assets.mjs frontend/react/src/components tests/check_frontend_refinement_system.py
git commit -m "style: complete frontend deep refinement"
git push origin main
```

Expected: `origin/main`包含本轮全部精修提交，工作树除已有`.codegraph/`外干净。
