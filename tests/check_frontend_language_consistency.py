from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

FRONTEND_PATHS = [
    ROOT / "frontend" / "react" / "src",
    ROOT / "frontend" / "styles.css",
]

MOJIBAKE_TOKENS = ["鏂", "浼", "鍒", "鎼", "鐭", "妯", "瀵", "绠", "澶", "涓", "鍚", "杩", "榛", "瑙", "璇", "�"]
MIXED_VISIBLE_COPY = [
    '"Workspace"',
    "'Workspace'",
    'content: "Info"',
    "Model正在思考",
    "本地备用Model",
    "对话Model",
    "GPT Model",
    "Model与",
    "Model网关",
    "系列Model",
    "Model服务",
    "CustomModel",
    "Knowledge已",
    "Knowledge失败",
    "创建Knowledge",
    "删除Knowledge",
]

REQUIRED_CHINESE_COPY = [
    "模型",
    "新建模型配置",
    "知识库",
    "新对话",
    "有什么可以帮你？",
    "登录 KnowFlow",
]


def iter_files():
    for base in FRONTEND_PATHS:
        if base.is_file():
            yield base
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix in {".js", ".jsx", ".css"}:
                yield path


def main() -> None:
    all_text = ""
    offenders = []
    for path in iter_files():
        text = path.read_text(encoding="utf-8")
        all_text += "\n" + text
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(token in line for token in MOJIBAKE_TOKENS):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
    mixed_copy = [copy for copy in MIXED_VISIBLE_COPY if copy in all_text]
    missing = [copy for copy in REQUIRED_CHINESE_COPY if copy not in all_text]
    if offenders:
        raise AssertionError("Frontend source contains mojibake text:\n" + "\n".join(offenders[:80]))
    if mixed_copy:
        raise AssertionError("Frontend source contains mixed Chinese/English visible copy: " + ", ".join(mixed_copy))
    if missing:
        raise AssertionError("Frontend Chinese UI copy is missing required text: " + ", ".join(missing))
    print("frontend UI copy is Chinese-first and mojibake-free")


if __name__ == "__main__":
    main()
