# Chat Empty State Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把新会话页收拢为紧凑、清晰的欢迎语与输入框组合，并避免空运行抽屉和鼠标焦点框干扰主任务。

**Architecture:** 继续由`ChatMessages`维护`.chat-empty`状态，不引入新组件和后端接口。用一个位于样式表末尾的高优先级空态样式块统一覆盖历史规则，并在`startNewChat()`中复用现有抽屉关闭事件。

**Tech Stack:** React、CSS Grid、浏览器CustomEvent、Python静态契约检查、Vite、Selenium

---

## 文件结构

- Create: `tests/check_frontend_chat_empty_state_polish.py`，锁定空态布局、抽屉关闭和键盘焦点契约。
- Modify: `frontend/react/src/controller/chatFlow.js`，新建会话时关闭运行抽屉。
- Modify: `frontend/styles.css`，追加唯一的空态收口样式块。
- Generated: `frontend/react/src/styles.css`，由`npm --prefix frontend run sync:assets`同步生成。

### Task 1: 建立失败的空态契约检查

**Files:**
- Create: `tests/check_frontend_chat_empty_state_polish.py`

- [ ] **Step 1: 写入失败检查**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(f"missing {label} in {path}: {needle}")


def main() -> None:
    require(
        "frontend/react/src/controller/chatFlow.js",
        'window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close"));',
        "new chat drawer close",
    )
    for stylesheet in ("frontend/styles.css", "frontend/react/src/styles.css"):
        require(stylesheet, "/* Chat empty state final polish. */", "empty state contract")
        require(stylesheet, "grid-template-rows: minmax(64px, 0.76fr) auto 26px auto minmax(88px, 1.24fr)", "compact vertical composition")
        require(stylesheet, "#page-chat.chat-empty .chat-topbar-actions", "empty topbar actions")
        require(stylesheet, "display: none !important", "empty action hiding")
        require(stylesheet, "max-width: 880px !important", "composer width")
        require(stylesheet, "min-height: 66px !important", "composer height")
        require(stylesheet, ":focus:not(:focus-visible)", "mouse focus suppression")
        require(stylesheet, "@media (max-width: 520px)", "mobile contract")
        require(stylesheet, "grid-template-columns: 14px minmax(0, 1fr) 14px", "mobile safe area")
    print("chat empty state is compact, accessible, and drawer-safe")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行检查并确认RED**

Run: `py -3 tests/check_frontend_chat_empty_state_polish.py`

Expected: FAIL，提示缺少`new chat drawer close`或`empty state contract`。

- [ ] **Step 3: 提交测试**

```powershell
git add tests/check_frontend_chat_empty_state_polish.py
git commit -m "test: define chat empty state polish"
```

### Task 2: 实现空态收口与抽屉关闭

**Files:**
- Modify: `frontend/react/src/controller/chatFlow.js:192-208`
- Modify: `frontend/styles.css:12143`
- Generated: `frontend/react/src/styles.css`
- Test: `tests/check_frontend_chat_empty_state_polish.py`

- [ ] **Step 1: 在新建会话流程关闭运行抽屉**

在`requestComposerReset({ focus: true });`前加入：

```js
window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close"));
```

- [ ] **Step 2: 在主样式表末尾追加最终空态规则**

```css
/* Chat empty state final polish. */
#page-chat.chat-empty .chat-panel {
  grid-template-columns: minmax(28px, 1fr) minmax(0, 880px) minmax(28px, 1fr) !important;
  grid-template-rows: minmax(64px, 0.76fr) auto 26px auto minmax(88px, 1.24fr) !important;
}

#page-chat.chat-empty .chat-topbar {
  display: flex !important;
  height: 54px !important;
  min-height: 54px !important;
  padding: 0 !important;
  border: 0 !important;
  background: transparent !important;
  opacity: 1 !important;
  pointer-events: auto !important;
}

#page-chat.chat-empty .chat-topbar h1,
#page-chat.chat-empty .chat-topbar-actions {
  display: none !important;
}

#page-chat.chat-empty .messages,
#page-chat.chat-empty #chat-form.composer {
  width: 100% !important;
  max-width: 880px !important;
}

#page-chat.chat-empty .welcome-card h2 {
  font-size: clamp(30px, 2.35vw, 38px) !important;
  font-weight: 430 !important;
  transform: none !important;
}

#page-chat.chat-empty #chat-form.composer .composer-shell {
  min-height: 66px !important;
  border-radius: 22px !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 12px 30px rgba(0, 0, 0, 0.07) !important;
}

#page-chat.chat-empty button:focus:not(:focus-visible),
#page-chat.chat-empty textarea:focus:not(:focus-visible),
#page-chat.chat-empty [tabindex]:focus:not(:focus-visible) {
  outline: none !important;
}

@media (max-width: 520px) {
  #page-chat.chat-empty .chat-panel {
    grid-template-columns: 14px minmax(0, 1fr) 14px !important;
    grid-template-rows: minmax(56px, 0.7fr) auto 22px auto minmax(72px, 1.3fr) !important;
  }

  #page-chat.chat-empty .welcome-card h2 {
    font-size: clamp(27px, 8.2vw, 31px) !important;
  }

  #page-chat.chat-empty #chat-form.composer .composer-shell {
    min-height: 64px !important;
    border-radius: 20px !important;
  }
}
```

- [ ] **Step 3: 同步React样式副本**

Run: `npm --prefix frontend run sync:assets`

Expected: `frontend/react/src/styles.css`与`frontend/styles.css`同步包含最终空态规则。

- [ ] **Step 4: 运行目标检查并确认GREEN**

Run: `py -3 tests/check_frontend_chat_empty_state_polish.py`

Expected: PASS并输出`chat empty state is compact, accessible, and drawer-safe`。

- [ ] **Step 5: 运行关联回归检查**

```powershell
py -3 tests/check_frontend_chat_flow_module.py
py -3 tests/check_frontend_composer_chrome_react.py
py -3 tests/check_frontend_composer_model_picker.py
py -3 tests/check_frontend_shell_layout_react.py
```

Expected: 全部退出码为0。

- [ ] **Step 6: 提交实现**

```powershell
git add frontend/react/src/controller/chatFlow.js frontend/styles.css frontend/react/src/styles.css
git commit -m "feat: polish chat empty state"
```

### Task 3: 真实浏览器与发布门禁

**Files:**
- Verify: `frontend/react/src/components/ChatMessages.jsx`
- Verify: `frontend/react/src/components/ChatComposerForm.jsx`
- Verify: `frontend/react/src/components/ChatEvidenceDrawer.jsx`

- [ ] **Step 1: 启动本地前后端**

后端使用`127.0.0.1:8010`，前端使用`127.0.0.1:5173`，测试结束后仅关闭本轮启动的监听进程。

- [ ] **Step 2: 验证1440×900空态**

用Selenium断言：欢迎语底部到composer顶部间距在22至32px；composer宽度不超过880px；视觉组中心位于内容区高度的38%至55%；“运行”和“刷新”不可见；页面无横向溢出。

- [ ] **Step 3: 验证抽屉和新会话**

展开运行抽屉后点击“新对话”，断言抽屉收起、页面回到`.chat-empty`且输入框获得焦点。

- [ ] **Step 4: 验证375×812窄屏**

断言`document.documentElement.scrollWidth <= 375`、左右安全边距至少14px、模型按钮与发送按钮不溢出、标题和composer仍为紧凑同组。

- [ ] **Step 5: 验证焦点语义**

鼠标点击主题按钮、模型按钮和输入框后不出现双层outline；使用Tab导航时`:focus-visible`轮廓可见。

- [ ] **Step 6: 执行完整门禁**

```powershell
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { py -3 $_.FullName; if ($LASTEXITCODE -ne 0) { throw "failed: $($_.Name)" } }
npm --prefix frontend ci
npm --prefix frontend audit
npm --prefix frontend run build
git diff --check
```

Expected: 所有检查通过、audit为0个已知漏洞、生产构建成功、`git diff --check`无输出。

- [ ] **Step 7: 检查发布卫生并提交**

确认不跟踪`.env`、数据库、上传文件、`frontend/dist`、`data/mem0`、Token或Key；随后提交剩余验证性变更并推送`origin/main`。
