from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "react" / "src"


def extract_function(source: str, name: str) -> str:
    match = re.search(rf"function\s+{re.escape(name)}\s*\(", source)
    assert match, f"missing JavaScript function: {name}"
    opening = source.find("{", match.end())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
    raise AssertionError(f"unclosed JavaScript function: {name}")


def check_memory_time(page: str) -> None:
    function = extract_function(page, "memoryTime")
    script = textwrap.dedent(
        f"""
        import assert from "node:assert/strict";
        {function}
        assert.equal(
          memoryTime(
            {{ updated_at: "2026-07-29T13:52:49.490239+00:00" }},
            "Asia/Shanghai",
          ),
          "2026年07月29日 21:52",
        );
        assert.match(
          memoryTime(
            {{ created_at: "2026-07-29 13:52:49" }},
            "Asia/Shanghai",
          ),
          /^2026年07月29日 \\d{{2}}:52$/,
        );
        assert.equal(memoryTime({{ updated_at: "not-a-date" }}), "");
        assert.equal(memoryTime({{}}), "");
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def main() -> None:
    page = (SRC / "components" / "MemoryPage.jsx").read_text(
        encoding="utf-8"
    )
    app = (SRC / "App.jsx").read_text(encoding="utf-8")
    navigation = (SRC / "data" / "navigation.js").read_text(
        encoding="utf-8"
    )
    client = (SRC / "api" / "client.js").read_text(
        encoding="utf-8"
    )
    sidebar = (SRC / "components" / "Sidebar.jsx").read_text(
        encoding="utf-8"
    )
    settings_page = (SRC / "components" / "SettingsPage.jsx").read_text(
        encoding="utf-8"
    )
    knowledge_rail = (SRC / "components" / "KnowledgeRail.jsx").read_text(
        encoding="utf-8"
    )
    catalog = (SRC / "controller" / "catalogSync.js").read_text(
        encoding="utf-8"
    )
    styles = (SRC / "styles.css").read_text(encoding="utf-8")
    source_styles = (ROOT / "frontend" / "styles.css").read_text(
        encoding="utf-8"
    )

    assert 'import { memoryApi } from "../api/client.js"' in page
    assert 'id={"page-memory"}' in page
    assert 'role={"switch"}' in page
    assert "memoryApi.settings()" in page
    assert "memoryApi.setEnabled(" in page
    assert "memoryApi.list()" in page
    assert "memoryApi.update(" in page
    assert "memoryApi.delete(" in page
    assert "memoryApi.clear()" in page
    assert "清空全部" in page
    assert "长期记忆" in page
    assert "Mem0" in page
    delete_guard = (
        'if (!window.confirm("删除这条长期记忆？此操作无法撤销。")) '
        "return;"
    )
    assert delete_guard in page
    delete_handler = page[page.index("const handleDelete"):]
    assert delete_handler.index(delete_guard) < delete_handler.index(
        "await memoryApi.delete(memoryId)"
    )
    assert (
        "const interactionLocked = loading || memoriesLoading || Boolean(busy);"
        in page
    )
    assert "正在读取配置..." in page
    assert "正在读取记忆..." in page
    assert "disabled={!settings?.configured || interactionLocked}" in page
    assert "disabled={!memories.length || interactionLocked}" in page
    assert "disabled={!draft.trim() || interactionLocked}" in page
    assert page.count("disabled={interactionLocked}") >= 4
    editor_field = page[page.index("<textarea"):page.index("/>", page.index("<textarea"))]
    assert "disabled={interactionLocked}" in editor_field
    assert "autoFocus" in editor_field
    assert "maxLength={12000}" in editor_field
    for pending_copy in [
        "正在更新长期记忆状态",
        "清空中...",
        "保存中...",
        "删除中...",
    ]:
        assert pending_copy in page
    assert 'aria-busy={interactionLocked}' in page
    check_memory_time(page)

    assert 'const MemoryPage = lazyNamed("memory", "MemoryPage")' in app
    assert '"memory"' in app
    assert '<MemoryPage active={activePage === "memory"} />' in app
    assert 'label: "记忆"' in navigation
    assert 'icon: "memory"' in navigation
    assert 'page: "memory"' in navigation
    assert 'type === "memory"' in sidebar

    assert "await Promise.all([" in catalog
    assert "knowflow:react-model-options-updated" in settings_page
    assert "useEffect(() => {\n    loadModels();" not in settings_page
    assert "knowflow:react-knowledge-options-updated" in knowledge_rail
    assert "useEffect(() => {\n    loadKnowledgeBases();" not in knowledge_rail

    assert "export const memoryApi" in client
    for path in [
        '"/api/memory/settings"',
        '"/api/memories"',
    ]:
        assert path in client

    assert ".memory-workspace" in styles
    assert ".memory-item-content" in styles
    assert "font-size: 14px" in styles
    assert "@media (max-width: 760px)" in styles
    assert ".memory-toolbar button:not(:disabled):hover," in source_styles
    assert ".memory-item-meta button:not(:disabled):hover," in source_styles
    assert ".memory-editor button:not(:disabled):hover" in source_styles
    assert "\n.memory-toolbar button:hover," not in source_styles

    print("React memory management is visible and operable")


if __name__ == "__main__":
    main()
