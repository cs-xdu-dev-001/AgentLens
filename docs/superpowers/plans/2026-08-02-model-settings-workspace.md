# Model Settings Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模型配置页精简为紧凑、可扫描且带内联连接反馈的工作台。

**Architecture:** 保留`SettingsPage`的数据请求和组件边界，在页面状态中增加单个连接检查结果；`ModelListPanel`只负责选择摘要，`ModelConfigDetails`负责能力标签、配置事实和操作层级。样式继续写入`frontend/refinement.css`并同步到React副本。

**Tech Stack:** React 18、原生`details`菜单、CSS、Python静态回归检查、Vite。

---

### Task 1: 建立回归门禁

**Files:**
- Create: `tests/check_frontend_model_settings_workspace.py`

- [ ] 写静态检查，要求内联连接状态、能力标签、更多菜单和纯白详情选择器存在，并禁止详情中直接渲染删除按钮。
- [ ] 运行`py -3 -u tests/check_frontend_model_settings_workspace.py`，确认因目标结构缺失而失败。

### Task 2: 收敛模型列表与详情

**Files:**
- Modify: `frontend/react/src/components/ModelListPanel.jsx`
- Modify: `frontend/react/src/components/ModelConfigDetails.jsx`
- Modify: `frontend/react/src/components/SettingsPage.jsx`

- [ ] 列表改为名称、模型ID、协议摘要、状态和默认短标签。
- [ ] 详情头部合并状态与默认标记，新增模型类型和协议能力标签。
- [ ] 使用`details`承载删除操作，主要操作保留检查连接。
- [ ] 在`SettingsPage`测量连接耗时并维护`checking/success/error`状态，将安全消息传给详情。
- [ ] 重跑定向检查并确认通过。

### Task 3: 实施纯白扁平样式

**Files:**
- Modify: `frontend/refinement.css`
- Modify: `frontend/react/src/refinement.css`

- [ ] 覆盖列表、详情、定义列表、能力标签、连接结果和更多菜单样式。
- [ ] 明确`dt`、`dd`和正文背景透明，状态色仅用于语义。
- [ ] 为900px和720px断点提供上下布局与可换行操作。
- [ ] 运行`npm run sync:styles`并确认两份样式一致。

### Task 4: 验证与提交

**Files:**
- Verify: `frontend/react/src/components/SettingsPage.jsx`
- Verify: `frontend/react/src/components/ModelConfigDetails.jsx`
- Verify: `frontend/react/src/components/ModelListPanel.jsx`
- Verify: `frontend/refinement.css`
- Verify: `tests/check_frontend_model_settings_workspace.py`

- [ ] 运行`npm run build`。
- [ ] 批量检查桌面和窄屏视觉结果，最多一轮集中修正和一轮确认。
- [ ] 按文件名运行全部`tests/check_*.py`。
- [ ] 运行`git diff --check`与敏感/生成物检查。
- [ ] 仅暂存上述实现文件和测试，提交`style: clarify model settings workspace`，不推送。
