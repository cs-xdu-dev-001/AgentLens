from __future__ import annotations

from dataclasses import dataclass

import re


def _normalize_prefix(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


@dataclass(frozen=True)
class SlashCommand:
    value: str
    description: str
    aliases: tuple[str, ...] = ()
    is_group: bool = False
    hidden: bool = False

    def score(self, query: str, parent: tuple[str, ...], prefix: str) -> int | None:
        if not query.startswith("/"):
            return None
        segments = _segments(query)
        if tuple(segments[:-1]) != parent:
            return None
        candidate = segments[-1]
        if prefix:
            if candidate.startswith(prefix):
                return len(candidate) - len(prefix)
            cursor = 0
            gaps = 0
            for ch in prefix:
                position = candidate.find(ch, cursor)
                if position < 0:
                    break
                gaps += position - cursor
                cursor = position + 1
            else:
                return 100 + gaps
            return None
        return 0


def _segments(value: str) -> list[str]:
    return [segment for segment in value[1:].lower().split() if segment]


def _normalize_query(query: str) -> tuple[tuple[str, ...], str, bool]:
    if not query.startswith("/"):
        return tuple(), "", False
    body = query[1:]
    if not body.strip():
        return tuple(), "", body.endswith(" ")
    has_tail_space = body.endswith(" ")
    parts = [part for part in body.split() if part]
    if has_tail_space:
        return tuple(parts), "", True
    if len(parts) == 1:
        return tuple(), parts[0].lower(), False
    return tuple(part.lower() for part in parts[:-1]), parts[-1].lower(), False


COMMANDS = (
    SlashCommand("/help", "查看命令与快捷键", ("/?",), is_group=True),
    SlashCommand("/help commands", "查看完整命令清单"),
    SlashCommand("/help shortcuts", "查看交互快捷键"),
    SlashCommand("/help tui", "查看TUI功能说明"),
    SlashCommand("/new", "开始新会话"),
    SlashCommand("/clear", "清空当前显示"),
    SlashCommand("/model", "查看当前模型", is_group=True),
    SlashCommand("/model list", "查看模型配置"),
    SlashCommand("/model config", "打开模型配置说明"),
    SlashCommand("/model use", "切换会话模型（远程模式）"),
    SlashCommand("/status", "查看会话与运行状态"),
    SlashCommand("/permissions", "查看本次会话权限"),
    SlashCommand("/tasks", "查看等待执行的任务"),
    SlashCommand("/continue", "继续执行等待队列"),
    SlashCommand("/exit", "退出KnowFlow", ("/quit",)),
    SlashCommand("/about", "显示版本、执行环境与会话上下文"),
    SlashCommand("/version", "显示当前CLI与协议版本"),
    SlashCommand("/update", "更新KnowFlow CLI到最新版"),
    SlashCommand("/tools", "查看工具清单", is_group=True),
    SlashCommand("/tools list", "列出可用工具"),
    SlashCommand("/skills", "查看Skill清单", is_group=True),
    SlashCommand("/skills list", "列出当前会话可用技能"),
    SlashCommand("/mcp", "查看MCP接入", is_group=True),
    SlashCommand("/mcp list", "列出MCP服务器"),
    SlashCommand("/memory", "查看长期记忆", is_group=True),
    SlashCommand("/memory list", "查看最近记忆摘要"),
)


def parse_command(value: str) -> tuple[str, list[str]]:
    value = value.strip()
    if not value:
        return "", []
    parts = [part for part in value.split() if part]
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


def find_command(value: str) -> SlashCommand | None:
    normalized = canonical_command(value)
    normalized = normalized.strip().lower()
    for command in COMMANDS:
        if command.value == normalized:
            return command
    return None


def match_commands(query: str) -> list[SlashCommand]:
    if not query.startswith("/"):
        return []
    query = query.lower()
    parent, prefix, has_tail_space = _normalize_query(query)
    ranked: list[tuple[int, int, SlashCommand]] = []
    for index, command in enumerate(COMMANDS):
        if command.score(command.value, parent, prefix) is not None:
            ranked.append((command.score(command.value, parent, prefix) or 0, index, command))
            continue
        if parent or prefix or has_tail_space:
            for alias in command.aliases:
                score = command.score(alias, parent, prefix)
                if score is not None:
                    ranked.append((score + 1000, index, command))
                    break
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]


def canonical_command(value: str) -> str:
    normalized = _normalize_prefix(value)
    for command in COMMANDS:
        if normalized == command.value or normalized in command.aliases:
            return command.value
    return value.strip()


def command_children(prefix: str) -> list[str]:
    if not prefix.startswith("/"):
        return []
    normalized_prefix = prefix.strip().lower()
    parent = normalized_prefix
    children: list[str] = []
    for command in COMMANDS:
        value = command.value.lower()
        if not value.startswith(parent + " "):
            continue
        child = value[len(parent) + 1 :]
        if " " in child:
            continue
        children.append(command.value)
    return sorted(children)
