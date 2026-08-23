from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def unique_branch_title(
    source_title: str,
    existing_titles: Iterable[str],
    requested_title: str = "",
    *,
    max_length: int = 255,
) -> str:
    """Return a stable, human-readable branch title without collisions."""

    requested = " ".join(str(requested_title or "").split())
    source = " ".join(str(source_title or "新会话").split()) or "新会话"
    base = requested or f"{source}（分支）"
    base = base[:max_length].rstrip() or "新会话（分支）"
    occupied = {str(value or "").strip() for value in existing_titles}
    if base not in occupied:
        return base
    stem = base.removesuffix("（分支）") if not requested else base
    index = 2
    while True:
        suffix = f"（分支 {index}）"
        candidate = f"{stem[: max_length - len(suffix)].rstrip()}{suffix}"
        if candidate not in occupied:
            return candidate
        index += 1


def render_session_markdown(
    title: str,
    messages: Iterable[dict[str, Any]],
) -> str:
    """Render only user-visible conversation content, never runtime traces."""

    sections: list[str] = [f"# {str(title or 'AgentLens会话').strip() or 'AgentLens会话'}"]
    labels = {"user": "用户", "assistant": "Agent"}
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "").strip()
        if role not in labels or not content:
            continue
        sections.extend((f"## {labels[role]}", content))
    return "\n\n".join(sections).rstrip() + "\n"


def safe_export_filename(value: str, *, fallback: str = "agentlens-session") -> str:
    """Create a portable Markdown filename and strip all path semantics."""

    raw = str(value or "").strip()
    raw = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if raw.lower().endswith(".md"):
        raw = raw[:-3]
    normalized = _UNSAFE_FILENAME.sub("-", raw)
    normalized = re.sub(r"\s+", "-", normalized).strip(" .-_")
    normalized = normalized.replace("..", ".")[:80].rstrip(" .-_")
    if not normalized:
        normalized = fallback
    return f"{normalized}.md"


def available_export_path(directory: Path, filename: str) -> Path:
    """Avoid overwriting an existing export while staying inside directory."""

    root = Path(directory).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = safe_export_filename(filename)
    candidate = (root / safe_name).resolve()
    if candidate.parent != root:
        raise ValueError("导出文件必须位于当前工作区。")
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        next_candidate = root / f"{candidate.stem}-{index}{candidate.suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1
