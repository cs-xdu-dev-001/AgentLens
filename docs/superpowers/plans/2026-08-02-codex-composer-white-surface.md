# Codex式纯白聊天输入区实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将KnowFlow AI聊天工作区改为纯白画布，并把输入框调整为Codex式大输入面和左右分组工具条。

**Architecture:** 继续使用现有React组件和事件，不改DOM职责或后端接口。所有视觉调整进入`frontend/refinement.css`，再通过既有同步脚本生成React副本；静态回归检查锁定布局契约，桌面与420px截图验证真实几何关系。

**Tech Stack:** React、CSS Grid、Vite、Python静态契约检查、Microsoft Edge无头截图。

---

### Task 1: 锁定纯白Codex式输入区契约

**Files:**
- Modify: `tests/check_frontend_empty_composer_alignment.py`

- [ ] **Step 1: 写入失败检查**

在现有检查中要求以下契约同时出现在源样式与React同步样式：

```python
require(source, "/* KnowFlow refinement: Codex composer surface */", "Codex composer contract")
require(source, "--kf-empty-chat-column: min(860px, calc(100% - 32px));", "wide composer column")
require(source, "background: #fff !important;", "pure white chat surface")
require(source, "grid-template-rows: minmax(50px, auto) 36px !important;", "large input surface")
require(source, "justify-self: end;", "right aligned model picker")
```

- [ ] **Step 2: 确认检查按预期失败**

Run: `py -3 tests/check_frontend_empty_composer_alignment.py`

Expected: FAIL，提示缺少`Codex composer contract`。

### Task 2: 实现纯白画布和Codex式工具条

**Files:**
- Modify: `frontend/refinement.css`
- Generated: `frontend/react/src/refinement.css`

- [ ] **Step 1: 调整浅色聊天画布**

增加仅作用于浅色主题的规则：

```css
:root:not([data-theme="mono-dark"]) #page-chat,
:root:not([data-theme="mono-dark"]) #page-chat .chat-layout,
:root:not([data-theme="mono-dark"]) #page-chat .chat-panel,
:root:not([data-theme="mono-dark"]) #page-chat .messages {
  background: #fff !important;
}
```

- [ ] **Step 2: 扩大输入面并重排工具条**

将共享空状态列宽设为860px；输入框使用两行网格，上层最小50px，下层36px。加号固定左下，模型选择器`justify-self:end`，发送按钮位于最右侧。纯白输入框使用浅灰边框、22px圆角和单层柔和阴影。

- [ ] **Step 3: 处理窄屏和动态内容**

在720px以下保留12px页面边距，模型名称允许省略，工具条不换行；选中Skill或多行输入时只增加上层高度，不改变底部工具条位置。

- [ ] **Step 4: 同步样式并确认检查转绿**

Run: `cd frontend; npm run sync:styles; cd ..; py -3 tests/check_frontend_empty_composer_alignment.py`

Expected: PASS并输出`empty welcome and composer share one calm visual axis`。

- [ ] **Step 5: 提交实现**

```powershell
git add -- frontend/refinement.css frontend/react/src/refinement.css tests/check_frontend_empty_composer_alignment.py
git commit -m "style: adopt Codex composer surface"
```

### Task 3: 有界视觉验收与发布门禁

**Files:**
- Verify: `frontend/refinement.css`
- Verify: `frontend/react/src/refinement.css`

- [ ] **Step 1: 一批生成桌面和420px截图**

使用加载`styles.css`和`refinement.css`的临时真实类名页面，分别以1440×900和420×820生成截图。检查标题与输入框中心线、纯白背景、工具条左右分组和焦点轮廓；临时页面验收后删除。

- [ ] **Step 2: 运行布局扫描**

Run: `node C:\Users\z2986\.codex\skills\impeccable\scripts\detect.mjs --json --scope layout frontend/refinement.css frontend/react/src/refinement.css`

Expected: `[]`。

- [ ] **Step 3: 运行全量检查与生产构建**

Run: 按文件名排序执行全部`tests/check_*.py`。

Expected: 全部通过。

Run: `cd frontend; npm run build`

Expected: Vite生产构建退出码0。

- [ ] **Step 4: 执行发布检查并推送**

执行`git diff --check`、禁止提交项和敏感模式检查；确认只剩本地`.codegraph/`未跟踪后，将最终提交推送至`origin/main`。
