# Codex式纯白侧栏与知识库实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留全部导航和数据功能的前提下，把左侧栏与知识库页面统一为Codex式纯白单色界面。

**Architecture:** 保持现有React状态和事件数据流，只调整`Sidebar`的搜索/刷新布局，并在独立`refinement.css`中追加最终视觉契约。源样式通过现有`sync:assets`同步到React目录，避免直接修改生成副本。

**Tech Stack:** React、CSS、Python静态契约检查、Vite

---

### Task 1: 建立纯白侧栏和知识库回归门禁

**Files:**
- Create: `tests/check_frontend_white_sidebar_knowledge.py`

- [ ] **Step 1: 写失败测试**

测试同时读取`frontend/refinement.css`与`frontend/react/src/refinement.css`，要求存在以下契约：

```python
for stylesheet in ("frontend/refinement.css", "frontend/react/src/refinement.css"):
    source = read(stylesheet)
    require(source, "/* KnowFlow refinement: Codex white sidebar and knowledge */", "visual contract")
    require(source, "--sidebar-width: 252px;", "expanded sidebar width")
    require(source, "--sidebar-collapsed-width: 56px;", "collapsed sidebar width")
    require(source, "background: #fff !important;", "white surfaces")
    require(source, "background: #f5f5f5 !important;", "hover state")
    require(source, "background: #ececec !important;", "selected state")
```

测试读取`Sidebar.jsx`，要求存在`sidebar-search-row`和`sidebar-refresh-button`，并禁止旧的`sidebar-heading-row`。

- [ ] **Step 2: 验证测试按预期失败**

Run: `py -3 -u tests/check_frontend_white_sidebar_knowledge.py`

Expected: FAIL，提示缺少纯白侧栏视觉契约。

- [ ] **Step 3: 暂不修改生产代码**

本任务只建立失败门禁，后续任务负责使其通过。

### Task 2: 精简侧栏结构并保留刷新能力

**Files:**
- Modify: `frontend/react/src/components/Sidebar.jsx:345-356`
- Test: `tests/check_frontend_white_sidebar_knowledge.py`

- [ ] **Step 1: 将搜索和刷新合并为一行**

用以下结构替换旧搜索标签与“历史记录/刷新”标题行：

```jsx
<div className={"sidebar-search-row"}>
  <label className={"sidebar-search"}>
    <span>{"搜索会话"}</span>
    <input
      id={"sidebar-session-search"}
      placeholder={"搜索聊天"}
      value={searchQuery}
      onChange={handleSessionSearch}
    />
  </label>
  <button
    className={"sidebar-refresh-button"}
    type={"button"}
    aria-label={"刷新会话"}
    title={"刷新会话"}
    onClick={loadSessions}
  >
    <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
      <path d={"M20 11a8 8 0 1 0-2.34 5.66"} />
      <path d={"M20 5v6h-6"} />
    </svg>
  </button>
</div>
```

- [ ] **Step 2: 运行结构门禁**

Run: `py -3 -u tests/check_frontend_white_sidebar_knowledge.py`

Expected: 仍FAIL，但组件结构相关断言通过，仅缺样式契约。

### Task 3: 实施纯白单色视觉系统

**Files:**
- Modify: `frontend/refinement.css`
- Generated: `frontend/react/src/refinement.css`
- Test: `tests/check_frontend_white_sidebar_knowledge.py`

- [ ] **Step 1: 追加侧栏尺寸和纯白表面契约**

在`frontend/refinement.css`追加`/* KnowFlow refinement: Codex white sidebar and knowledge */`区块：

```css
:root {
  --sidebar-width: 252px;
  --sidebar-collapsed-width: 56px;
}

:root:not([data-theme="mono-dark"]) :where(
  .sidebar,
  #page-knowledge,
  #page-knowledge .workspace-page,
  #page-knowledge .knowledge-hero,
  #page-knowledge .knowledge-shell,
  #page-knowledge .knowledge-rail,
  #page-knowledge .knowledge-primary,
  #page-knowledge .knowledge-tabbar,
  #page-knowledge .knowledge-tab-panel
) {
  background: #fff !important;
}
```

- [ ] **Step 2: 统一侧栏密度和状态**

将品牌、导航、会话、搜索、账号行收敛到36px主节奏；移除卡片阴影和大面积灰底。悬停统一`#f5f5f5`，当前项统一`#ececec`，折叠栏保持56px并居中图标。

- [ ] **Step 3: 统一知识库页面层级**

顶栏、左栏、标签栏、表单与空状态使用白底；仅保留`#e7e7e7`分隔线。标签当前态使用底边，搜索框与选择器使用白底细边框，虚线空状态改为无卡片正文。

- [ ] **Step 4: 保留深色和移动端语义**

所有纯白规则限制在`:root:not([data-theme="mono-dark"])`；760px以下保留现有顶部导航布局，只覆盖尺寸和点击区域，不改变路由或折叠事件。

- [ ] **Step 5: 同步样式并验证门禁通过**

Run: `cd frontend; npm run sync:styles; cd ..; py -3 -u tests/check_frontend_white_sidebar_knowledge.py`

Expected: PASS并输出`sidebar and knowledge surfaces are white, compact, and accessible`。

### Task 4: 视觉验收和发布门禁

**Files:**
- Verify: `frontend/react/src/components/Sidebar.jsx`
- Verify: `frontend/refinement.css`
- Verify: `frontend/react/src/refinement.css`
- Verify: `tests/check_frontend_white_sidebar_knowledge.py`

- [ ] **Step 1: 构建生产前端**

Run: `cd frontend; npm run build`

Expected: Vite构建成功，无错误。

- [ ] **Step 2: 批量视觉核验**

用同一轮截图检查展开侧栏、折叠知识库页面和420px窄屏：纯白表面、252/56px宽度、会话截断、图标对齐、悬停/当前态、无横向溢出。

- [ ] **Step 3: 运行全部回归检查**

Run:

```powershell
$tests = Get-ChildItem tests -Filter 'check_*.py' | Sort-Object Name
foreach ($test in $tests) {
  py -3 -u $test.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
```

Expected: 全部检查通过。

- [ ] **Step 4: 检查发布卫生**

Run: `git diff --check; git status -sb`

Expected: 无空白错误；`.codegraph/`保持未跟踪且不进入提交范围。

- [ ] **Step 5: 提交实现**

```powershell
git add -- frontend/react/src/components/Sidebar.jsx frontend/refinement.css frontend/react/src/refinement.css tests/check_frontend_white_sidebar_knowledge.py
git commit -m "style: refine white sidebar workspace"
```
