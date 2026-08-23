from __future__ import annotations

from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.session_portability import (  # noqa: E402
    available_export_path,
    render_session_markdown,
    safe_export_filename,
    unique_branch_title,
)


def main() -> None:
    title = unique_branch_title(
        "原会话",
        ["原会话（分支）", "原会话（分支 2）"],
    )
    assert title == "原会话（分支 3）", title
    custom = unique_branch_title("原会话", [], "  方案 B  ")
    assert custom == "方案 B", custom

    content = render_session_markdown(
        "安全导出",
        [
            {"role": "system", "content": "secret runtime prompt"},
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答", "trace": "hidden"},
        ],
    )
    assert "问题" in content and "回答" in content
    assert "secret runtime prompt" not in content
    assert "trace" not in content
    assert safe_export_filename("../报告?.md") == "报告.md"

    with tempfile.TemporaryDirectory() as value:
        root = Path(value)
        first = available_export_path(root, "会话.md")
        first.write_text("one", encoding="utf-8")
        second = available_export_path(root, "会话.md")
        assert second.name == "会话-2.md", second
        assert second.parent == root.resolve()
    print("session branching and export stay portable and trace-free")


if __name__ == "__main__":
    main()
