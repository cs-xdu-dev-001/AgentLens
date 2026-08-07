from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlashCommand:
    value: str
    description: str
    aliases: tuple[str, ...] = ()

    def score(self, query: str) -> int | None:
        needle = query.strip().lower()
        if not needle.startswith("/") or " " in needle:
            return None
        best: int | None = None
        for candidate in (self.value, *self.aliases):
            target = candidate.lower()
            if target.startswith(needle):
                score = len(target) - len(needle)
            else:
                cursor = 0
                gaps = 0
                for character in needle:
                    position = target.find(character, cursor)
                    if position < 0:
                        break
                    gaps += position - cursor
                    cursor = position + 1
                else:
                    score = 100 + gaps
                    best = score if best is None else min(best, score)
                    continue
                continue
            best = score if best is None else min(best, score)
        return best


COMMANDS = (
    SlashCommand("/help", "查看命令与快捷键", ("/?",)),
    SlashCommand("/new", "开始新会话"),
    SlashCommand("/clear", "清空当前显示"),
    SlashCommand("/model", "查看当前模型"),
    SlashCommand("/status", "查看会话与运行状态"),
    SlashCommand("/permissions", "查看本次会话权限"),
    SlashCommand("/tasks", "查看等待执行的任务"),
    SlashCommand("/continue", "继续执行等待队列"),
    SlashCommand("/exit", "退出KnowFlow", ("/quit",)),
)


def match_commands(query: str) -> list[SlashCommand]:
    ranked: list[tuple[int, int, SlashCommand]] = []
    for index, command in enumerate(COMMANDS):
        score = command.score(query)
        if score is not None:
            ranked.append((score, index, command))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in ranked]


def canonical_command(value: str) -> str:
    normalized = value.strip().lower()
    for command in COMMANDS:
        if normalized == command.value or normalized in command.aliases:
            return command.value
    return normalized
