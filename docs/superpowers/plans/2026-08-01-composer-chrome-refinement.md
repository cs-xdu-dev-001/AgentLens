# Composer Chrome Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将聊天composer收成紧凑的正文行加底部工具栏，消除悬空控件和虚胖留白。

**Architecture:** 保留`ChatComposerForm`现有DOM、状态和事件。CSS将`.composer-input-stack`设为`display: contents`，让textarea、`+`、模型选择器和发送按钮进入同一个两行Grid；选中Skill时通过`:has()`增加一行，不引入新的React状态或组件。

**Tech Stack:** React、CSS Grid/Flexbox、Python静态契约检查、Vite、Selenium

---

## 文件结构

- Create: `tests/check_frontend_composer_compact_layout.py`，锁定紧凑Grid和控件尺寸契约。
- Modify: `frontend/styles.css`，追加唯一的composer最终收口规则。
- Generated: `frontend/react/src/styles.css`，通过`npm --prefix frontend run sync:assets`同步。

### Task 1: 建立失败的紧凑composer契约

**Files:**
- Create: `tests/check_frontend_composer_compact_layout.py`

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
    for stylesheet in ("frontend/styles.css", "frontend/react/src/styles.css"):
        require(stylesheet, "/* Compact composer chrome. */", "compact composer contract")
        require(stylesheet, "grid-template-rows: minmax(24px, auto) 36px", "two-row layout")
        require(stylesheet, "display: contents !important", "input stack grid lift")
        require(stylesheet, "grid-row: 2 !important", "toolbar row")
        require(stylesheet, "width: 36px !important", "compact action size")
        require(stylesheet, "border-radius: 18px !important", "compact shell radius")
        require(stylesheet, ":has(.selected-skill-pill)", "selected Skill expansion")
        require(stylesheet, "@media (max-width: 520px)", "mobile contract")
    print("composer chrome is compact and aligned")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行检查并确认RED**

Run: `py -3 tests/check_frontend_composer_compact_layout.py`

Expected: FAIL，提示缺少`compact composer contract`。

- [ ] **Step 3: 提交测试**

```powershell
git add tests/check_frontend_composer_compact_layout.py
git commit -m "test: define compact composer layout"
```

### Task 2: 用最终Grid规则压缩composer

**Files:**
- Modify: `frontend/styles.css`
- Generated: `frontend/react/src/styles.css`
- Test: `tests/check_frontend_composer_compact_layout.py`

- [ ] **Step 1: 在主样式表末尾追加最终规则**

```css
/* Compact composer chrome. */
#chat-form.composer .composer-shell {
  grid-template-columns: 36px minmax(0, 1fr) 36px !important;
  grid-template-rows: minmax(24px, auto) 36px !important;
  column-gap: 4px !important;
  row-gap: 1px !important;
  min-height: 0 !important;
  padding: 7px 9px 7px 12px !important;
  border-radius: 18px !important;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04), 0 8px 22px rgba(0, 0, 0, 0.06) !important;
}

#chat-form.composer .composer-input-stack {
  display: contents !important;
}

#chat-form.composer .composer-input-stack textarea {
  grid-column: 1 / -1 !important;
  grid-row: 1 !important;
  min-height: 24px !important;
  padding: 0 3px !important;
  font-size: 15px !important;
  line-height: 24px !important;
}

#chat-form.composer .composer-plus {
  grid-column: 1 !important;
  grid-row: 2 !important;
  width: 36px !important;
  height: 36px !important;
  border-radius: 12px !important;
  background: transparent !important;
}

#chat-form.composer .composer-model-picker {
  grid-column: 2 !important;
  grid-row: 2 !important;
  align-self: center;
}

#chat-form.composer #chat-submit-btn.composer-send-button {
  grid-column: 3 !important;
  grid-row: 2 !important;
  width: 36px !important;
  min-width: 36px !important;
  max-width: 36px !important;
  height: 36px !important;
  min-height: 36px !important;
  border-radius: 12px !important;
}

#chat-form.composer .composer-shell:has(.selected-skill-pill) {
  grid-template-rows: auto minmax(24px, auto) 36px !important;
}

#chat-form.composer .composer-shell:has(.selected-skill-pill) .selected-skill-pill {
  grid-column: 1 / -1 !important;
  grid-row: 1 !important;
}

#chat-form.composer .composer-shell:has(.selected-skill-pill) textarea {
  grid-row: 2 !important;
}

#chat-form.composer .composer-shell:has(.selected-skill-pill) .composer-plus,
#chat-form.composer .composer-shell:has(.selected-skill-pill) .composer-model-picker,
#chat-form.composer .composer-shell:has(.selected-skill-pill) #chat-submit-btn {
  grid-row: 3 !important;
}

@media (max-width: 520px) {
  #chat-form.composer .composer-shell {
    padding: 7px 8px 7px 10px !important;
    border-radius: 17px !important;
  }
}
```

- [ ] **Step 2: 同步样式副本**

Run: `npm --prefix frontend run sync:assets`

Expected: 两份样式表都包含`Compact composer chrome`规则。

- [ ] **Step 3: 运行目标与关联检查**

```powershell
py -3 tests/check_frontend_composer_compact_layout.py
py -3 tests/check_frontend_composer_input_react.py
py -3 tests/check_frontend_composer_menu_react.py
py -3 tests/check_frontend_composer_model_picker.py
py -3 tests/check_frontend_skill_picker_react.py
```

Expected: 全部退出码为0。

- [ ] **Step 4: 提交实现**

```powershell
git add frontend/styles.css frontend/react/src/styles.css
git commit -m "feat: refine composer chrome"
```

### Task 3: 浏览器与发布门禁

**Files:**
- Verify: `frontend/styles.css`
- Verify: `frontend/react/src/components/ChatComposerForm.jsx`

- [ ] **Step 1: 验证1440px空态和消息态**

用Selenium断言composer外框高度在70至78px；`+`和模型选择器处于同一水平基线；发送按钮为36px；正文输入位于工具栏上方；鼠标与键盘焦点语义不退化。

- [ ] **Step 2: 验证375×812**

断言无横向滚动，composer保持左右14px安全边距，长模型名截断，工具栏不换行，发送按钮不溢出。

- [ ] **Step 3: 执行完整门禁**

```powershell
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { py -3 $_.FullName; if ($LASTEXITCODE -ne 0) { throw "failed: $($_.Name)" } }
npm --prefix frontend ci
npm --prefix frontend audit
npm --prefix frontend run build
git diff --check
```

Expected: 所有检查通过，audit为0个已知漏洞，生产构建成功。

- [ ] **Step 4: 发布卫生与同步**

确认不提交`.env`、数据库、上传文件、`frontend/dist`、`data/mem0`、Token或Key；提交剩余变更并推送`origin/main`。
