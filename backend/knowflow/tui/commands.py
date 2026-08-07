from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Mapping, Sequence


SOURCE_LABELS = {
    "builtin": "内置",
    "tool": "工具",
    "skill": "Skill",
    "mcp": "MCP",
    "workflow": "工作流",
    "plugin": "插件",
    "dynamic": "扩展",
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _command_token(value: str) -> str:
    return _normalize(value).split(" ", 1)[0]


def _parts(value: str) -> tuple[str, ...]:
    return tuple(
        part
        for part in re.split(r"[:_-]+", value.removeprefix("/"))
        if part
    )


@dataclass(frozen=True)
class SlashCommand:
    value: str
    description: str
    aliases: tuple[str, ...] = ()
    hidden: bool = False
    source: str = "builtin"
    argument_hint: str = ""
    immediate: bool = False

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def requires_arguments(self) -> bool:
        return bool(self.argument_hint) or self.source != "builtin"


COMMANDS = (
    SlashCommand("/help", "浏览默认命令和Agent扩展", ("/?",), immediate=True),
    SlashCommand("/new", "开始新会话", immediate=True),
    SlashCommand("/clear", "清空当前显示", immediate=True),
    SlashCommand("/model", "查看或切换模型", argument_hint="[list | config | use <ID>]"),
    SlashCommand("/status", "查看会话与运行状态", immediate=True),
    SlashCommand(
        "/permissions",
        "管理工具的Allow、Ask和Deny规则",
        ("/allowed-tools",),
        immediate=True,
    ),
    SlashCommand("/tasks", "查看或管理等待任务", argument_hint="[list | remove <序号> | clear]"),
    SlashCommand("/continue", "继续执行暂停的任务队列", immediate=True),
    SlashCommand("/retry", "重新执行上一项任务", immediate=True),
    SlashCommand("/tools", "查看可用工具", immediate=True),
    SlashCommand("/skills", "查看当前会话可用Skill", immediate=True),
    SlashCommand("/mcp", "查看MCP服务器", immediate=True),
    SlashCommand("/memory", "查看最近长期记忆", immediate=True),
    SlashCommand("/history", "搜索或清空输入历史", argument_hint="[search <关键词> | clear]"),
    SlashCommand("/update", "更新KnowFlow CLI到最新版", immediate=True),
    SlashCommand("/about", "查看执行环境与会话上下文", immediate=True),
    SlashCommand("/version", "显示CLI与协议版本", immediate=True),
    SlashCommand("/exit", "退出KnowFlow", ("/quit",), immediate=True),
)


def parse_command(value: str) -> tuple[str, list[str]]:
    normalized = value.strip()
    if not normalized:
        return "", []
    parts = normalized.split()
    return (parts[0].lower(), parts[1:]) if parts else ("", [])


def find_command(
    value: str,
    commands: Sequence[SlashCommand] = COMMANDS,
) -> SlashCommand | None:
    token = _command_token(value)
    for command in commands:
        if token == command.value or token in command.aliases:
            return command
    return None


def canonical_command(
    value: str,
    commands: Sequence[SlashCommand] = COMMANDS,
) -> str:
    command = find_command(value, commands)
    return command.value if command is not None else value.strip()


def _match_score(command: SlashCommand, query: str, usage: int) -> tuple:
    name = command.value.removeprefix("/").lower()
    aliases = tuple(alias.removeprefix("/").lower() for alias in command.aliases)
    description = command.description.lower()
    parts = _parts(command.value)

    if query == name:
        rank, distance = 0, 0
    elif query in aliases:
        rank, distance = 1, 0
    elif name.startswith(query):
        rank, distance = 2, len(name) - len(query)
    elif any(alias.startswith(query) for alias in aliases):
        rank, distance = 3, min(len(alias) - len(query) for alias in aliases if alias.startswith(query))
    elif any(part.startswith(query) for part in parts):
        rank, distance = 4, min(len(part) - len(query) for part in parts if part.startswith(query))
    else:
        cursor = 0
        gaps = 0
        for character in query:
            position = name.find(character, cursor)
            if position < 0:
                break
            gaps += position - cursor
            cursor = position + 1
        else:
            return (5, gaps, -usage, len(name), name)
        candidates = (name, *aliases, *parts, description)
        similarity = max(SequenceMatcher(None, query, candidate).ratio() for candidate in candidates)
        contains = query in name or any(query in candidate for candidate in candidates)
        if not contains and similarity < 0.58:
            return (99, 0, 0, name)
        rank, distance = 6, -similarity
    return (rank, distance, -usage, len(name), name)


def match_commands(
    query: str,
    commands: Sequence[SlashCommand] = COMMANDS,
    usage: Mapping[str, int] | None = None,
) -> list[SlashCommand]:
    """Return Claude Code-style flat command suggestions.

    Suggestions stop once actual arguments begin. A trailing space is kept for
    argument hints but does not reopen a second command layer.
    """

    normalized = query.lstrip()
    if not normalized.startswith("/"):
        return []
    body = normalized[1:]
    if body.endswith(" "):
        return []
    if " " in body.rstrip():
        return []
    needle = body.strip().lower()
    usage = usage or {}
    visible = [command for command in commands if not command.hidden]
    if not needle:
        return sorted(
            visible,
            key=lambda command: (
                command.source != "builtin",
                -int(usage.get(command.value, 0)),
                command.value,
            ),
        )
    ranked = [
        (_match_score(command, needle, int(usage.get(command.value, 0))), command)
        for command in visible
    ]
    return [command for score, command in sorted(ranked, key=lambda item: item[0]) if score[0] < 99]


def merge_commands(
    builtins: Sequence[SlashCommand],
    dynamic: Sequence[SlashCommand],
) -> tuple[SlashCommand, ...]:
    merged: list[SlashCommand] = []
    seen: set[str] = set()
    for command in (*dynamic, *builtins):
        if not command.value.startswith("/") or command.value in seen:
            continue
        seen.add(command.value)
        merged.append(command)
    return tuple(merged)
