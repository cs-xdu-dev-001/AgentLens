from __future__ import annotations

import re
from math import ceil
from time import monotonic
from typing import Any

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import events, on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Collapsible, Input, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from ..services.agent_event_protocol import agent_event_name
from .commands import COMMANDS, SlashCommand, match_commands


ACCENT = "#d97757"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
    "cookie",
    "api_key",
    "apikey",
)
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|token|secret|password|authorization|cookie|"
    r"private[_-]?key|key)[\"']?\s*[:=]\s*[\"']?)([^\"',;\s}]+)"
)
OPENAI_KEY_PATTERN = re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_-]{8,}\b")
ACCOUNT_IDENTIFIER_PATTERN = re.compile(
    r"\b((?:org|proj)-)[A-Za-z0-9_-]{8,}\b"
)
BEARER_PATTERN = re.compile(
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"
)
CLI_SECRET_PATTERN = re.compile(
    r"(?i)(--(?:api[-_]?key|token|secret|password|authorization|cookie)"
    r"(?:=|\s+)[\"']?)([^\"'\s,;]+)"
)


def redact_public_detail(value: Any, *, limit: int = 180) -> str:
    if value is None:
        return ""

    def render(item: Any, depth: int = 0) -> str:
        if depth > 4:
            return "…"
        if isinstance(item, dict):
            values = []
            for key, child in item.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized == "key" or any(
                    part in normalized for part in SENSITIVE_KEY_PARTS
                ):
                    values.append(f"{key}=[已隐藏]")
                else:
                    values.append(f"{key}={render(child, depth + 1)}")
            return ", ".join(values)
        if isinstance(item, (list, tuple)):
            return ", ".join(render(child, depth + 1) for child in item[:8])
        text = str(item)
        text = OPENAI_KEY_PATTERN.sub("[已隐藏]", text)
        text = ACCOUNT_IDENTIFIER_PATTERN.sub(r"\1[已隐藏]", text)
        text = BEARER_PATTERN.sub("Bearer [已隐藏]", text)
        text = JWT_PATTERN.sub("[已隐藏]", text)
        text = CLI_SECRET_PATTERN.sub(r"\1[已隐藏]", text)
        return SENSITIVE_VALUE_PATTERN.sub(r"\1[已隐藏]", text)

    text = " ".join(render(value).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


TOOL_VERBS = {
    "list_workspace": "浏览",
    "list_workspace_files": "浏览",
    "read_workspace_file": "读取",
    "write_workspace_file": "写入",
    "sandbox_command": "运行",
    "run_sandbox_command": "运行",
    "read_tool_result": "读取工具结果",
}


def tool_activity_title(event: dict[str, Any]) -> str:
    """Return a concise, public description for a tool invocation."""
    name = str(
        event.get("toolName")
        or event.get("tool_name")
        or event.get("name")
        or "工具调用"
    )
    normalized = name.lower().replace("-", "_")
    arguments = event.get("arguments") or event.get("input")
    arguments = arguments if isinstance(arguments, dict) else {}
    target = ""
    for key in ("path", "file_path", "directory", "command", "result_id"):
        if arguments.get(key):
            target = redact_public_detail(arguments[key], limit=72)
            break
    verb = TOOL_VERBS.get(normalized)
    if verb is None:
        return name
    return f"{verb} {target}".strip()


def error_recovery_message(value: Any) -> tuple[str, str]:
    """Classify a public error into a useful label and recovery action."""
    text = redact_public_detail(value, limit=300)
    normalized = text.lower()
    if any(part in normalized for part in ("401", "unauthorized", "api key")):
        return "认证失败", "检查API Key与模型权限后输入/retry。"
    if "403" in normalized or "forbidden" in normalized:
        return "请求被拒绝", "检查账号权限或调整权限规则后输入/retry。"
    if "429" in normalized or "rate limit" in normalized:
        return "请求过于频繁", "稍后输入/retry，或切换可用模型。"
    if any(part in normalized for part in ("timeout", "timed out")):
        return "请求超时", "检查网络与上游状态后输入/retry。"
    if any(
        part in normalized
        for part in ("connection", "connecterror", "network", "dns")
    ):
        return "连接失败", "检查网络、Base URL与代理后输入/retry。"
    if any(part in normalized for part in ("permission", "denied", "sandbox")):
        return "权限不足", "调整权限或换一种做法；确认安全后可输入/retry。"
    return "执行失败", "修改要求后重新发送，或输入/retry重试上一任务。"


def tool_error_presentation(code: Any, message: Any) -> tuple[str, str]:
    normalized = str(code or "").strip().lower()
    known = {
        "permission_denied": ("未获批准", "调整权限或让Agent换一种做法。"),
        "approval_timeout": ("批准已超时", "重新执行后及时确认。"),
        "unknown_tool": ("工具不可用", "检查工具配置或改用其他工具。"),
        "invalid_arguments": ("参数不正确", "让Agent修正参数后再试。"),
        "input_validation_failed": ("参数不正确", "让Agent修正参数后再试。"),
        "tool_execution_indeterminate": (
            "执行状态不确定",
            "为避免重复写入，先检查目标状态再决定是否重试。",
        ),
        "tool_cancelled": ("已由用户中断", "检查已有输出后再决定是否重试。"),
        "tool_timeout": ("命令执行超时", "缩小任务或提高命令超时时间后重试。"),
        "sandbox_runtime_unavailable": (
            "SRT不可用",
            "运行agentlens doctor --cli检查SRT及Linux沙箱依赖。",
        ),
    }
    if normalized in known:
        return known[normalized]
    return error_recovery_message(message or code)


def _format_bytes(value: Any) -> str:
    try:
        size = max(0, int(value or 0))
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def _safe_shell_output(value: Any, *, lines: int = 5, limit: int = 2_000) -> str:
    raw_lines = str(value or "").splitlines()[-max(1, int(lines)) :]
    rendered = "\n".join(
        redact_public_detail(line, limit=max(80, limit // max(1, lines)))
        for line in raw_lines
    )
    return rendered if len(rendered) <= limit else rendered[-limit:]


class CommandMenu(Vertical):
    """Keyboard-driven slash command suggestions kept near the composer."""

    def __init__(self) -> None:
        super().__init__(id="command-menu")
        self.matches: list[SlashCommand] = []
        self.selected = 0
        self.commands: tuple[SlashCommand, ...] = COMMANDS
        self.query = ""
        self.usage: dict[str, int] = {}
        self.window_size = 6
        self._visible_start = 0

    def compose(self):
        yield Static("命令", classes="command-menu-title")
        yield OptionList(id="command-options", compact=True)

    def _render_option(self, command: SlashCommand) -> Text:
        row = Text()
        row.append(command.value, style="bold")
        needle = self.query.removeprefix("/").strip().lower()
        matched_alias = next(
            (
                alias
                for alias in command.aliases
                if needle
                and alias.removeprefix("/").lower().startswith(needle)
                and not command.value.removeprefix("/").lower().startswith(needle)
            ),
            "",
        )
        if matched_alias:
            row.append(f"  ({matched_alias})", style="dim")
        if command.argument_hint:
            row.append(f" {command.argument_hint}", style="dim")
        row.append(f"  {command.description}", style="dim")
        if command.source != "builtin":
            row.append(f"  [{command.source_label}]", style=ACCENT)
        return row

    def set_commands(self, commands: tuple[SlashCommand, ...]) -> None:
        self.commands = commands

    async def update_query(self, value: str) -> None:
        query = value.lstrip().lower()
        self.query = query
        self.matches = [
            item
            for item in match_commands(query, self.commands, self.usage)
            if not item.hidden
        ]
        self.selected = min(self.selected, max(0, len(self.matches) - 1))
        await self._render_matches()

    def record_usage(self, command: SlashCommand) -> None:
        self.usage[command.value] = self.usage.get(command.value, 0) + 1

    def _window(self) -> tuple[int, list[SlashCommand]]:
        if len(self.matches) <= self.window_size:
            return 0, self.matches
        half = self.window_size // 2
        start = max(0, min(self.selected - half, len(self.matches) - self.window_size))
        return start, self.matches[start : start + self.window_size]

    async def _render_matches(self) -> None:
        self.set_class(bool(self.matches), "visible")
        options = self.query_one("#command-options", OptionList)
        options.clear_options()
        if self.matches:
            self._visible_start, visible = self._window()
            options.add_options(
                [
                    Option(self._render_option(command), id=command.value)
                    for command in visible
                ]
            )
            options.highlighted = self.selected - self._visible_start
        self._update_title()

    def _update_title(self) -> None:
        title = self.query_one(".command-menu-title", Static)
        selected = self.matches[self.selected] if self.matches else None
        description = selected.description if selected else ""
        source = (
            f" · {selected.source_label}"
            if selected is not None and selected.source != "builtin"
            else ""
        )
        position = (
            f" · {self.selected + 1}/{len(self.matches)}"
            if len(self.matches) > self.window_size
            else ""
        )
        if self.size.width and self.size.width < 70:
            title.update(f"{description}{source}{position}")
        else:
            title.update(
                f"{description}{source}{position}  ↑↓选择  Tab/→补全  Enter确认  Esc关闭"
            )

    async def move(self, delta: int) -> None:
        if not self.matches:
            return
        self.selected = (self.selected + delta) % len(self.matches)
        await self._render_matches()

    @on(OptionList.OptionHighlighted)
    def handle_option_highlighted(
        self,
        event: OptionList.OptionHighlighted,
    ) -> None:
        self.selected = self._visible_start + event.option_index
        self._update_title()

    @on(OptionList.OptionSelected)
    def handle_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        self.selected = self._visible_start + event.option_index
        self.post_message(Composer.CommandAccepted())

    async def hide(self) -> None:
        self.matches = []
        self.selected = 0
        self._visible_start = 0
        await self._render_matches()

    @property
    def selected_value(self) -> str | None:
        if not self.matches:
            return None
        return self.matches[self.selected].value

    @property
    def selected_command(self) -> SlashCommand | None:
        if not self.matches:
            return None
        return self.matches[self.selected]


class RunActivity(Vertical):
    """Public, sanitized Agent progress for one turn."""

    STATUS_LABELS = {
        "running": "运行中",
        "waiting": "等待确认",
        "retrying": "等待重试",
        "pending": "等待中",
        "success": "已完成",
        "succeeded": "已完成",
        "completed": "已完成",
        "failed": "失败",
        "error": "失败",
        "cancelled": "已取消",
    }

    def __init__(self) -> None:
        super().__init__(classes="run-activity")
        self.started_at = monotonic()
        self.finished = False
        self._rows: dict[str, Collapsible] = {}
        self._statuses: dict[str, str] = {}
        self._titles: dict[str, str] = {}
        self._details: dict[str, str] = {}
        self.expanded = False
        self._tool_sequence = 0
        self._hidden_steps = 0
        self._tool_keys: set[str] = set()
        self._failed_tool_keys: set[str] = set()
        self._active_tool_keys: set[str] = set()
        self._tool_started_at: dict[str, float] = {}
        self._retry_deadline: float | None = None
        self._retry_attempt = 0
        self._retry_max = 0
        self._retry_status = 0

    def compose(self):
        yield Static("✻ 正在处理… (0.0s)", classes="activity-header")
        yield Vertical(classes="activity-steps")

    async def begin(self) -> None:
        await self.upsert("model", "分析任务", "running")

    @classmethod
    def _row_title(
        cls,
        title: str,
        status: str,
        *,
        elapsed: float | None = None,
        frame: str | None = None,
    ) -> Text:
        label = cls.STATUS_LABELS.get(status, status)
        marker = "×" if status in {"failed", "error"} else (
            frame if frame is not None and status == "running" else (
                "●" if status == "running" else (
                    "?" if status in {"waiting", "retrying"} else (
                        "■" if status == "cancelled" else "✓"
                    )
                )
            )
        )
        value = Text()
        value.append(
            f"  {marker} ",
            style="red" if marker == "×" else ACCENT,
        )
        value.append(title or "Agent步骤")
        value.append(f"  {label}", style="dim")
        if elapsed is not None:
            value.append(f" · {elapsed:.1f}s", style="dim")
        return value

    async def upsert(
        self,
        key: str,
        title: str,
        status: str,
        detail: str = "",
    ) -> None:
        normalized = status.lower() or "running"
        elapsed = None
        if key.startswith("tool:"):
            if normalized in {"running", "waiting", "retrying"}:
                self._tool_started_at.setdefault(key, monotonic())
            elif key in self._tool_started_at:
                elapsed = monotonic() - self._tool_started_at.pop(key)
        value = self._row_title(
            title,
            normalized,
            elapsed=elapsed,
        )
        if detail:
            self._details[key] = detail
        row = self._rows.get(key)
        if row is None:
            if len(self._rows) >= 100:
                oldest_key = next(iter(self._rows))
                row = self._rows.pop(oldest_key)
                self._statuses.pop(oldest_key, None)
                self._titles.pop(oldest_key, None)
                self._details.pop(oldest_key, None)
                row.title = value
                row.query_one(".activity-detail", Static).update(
                    detail or "暂无公开详情"
                )
                row.collapsed = not self.expanded or not bool(detail)
                self.query_one(".activity-steps", Vertical).move_child(
                    row,
                    after=-1,
                )
                self._hidden_steps += 1
            else:
                row = Collapsible(
                    Static(detail or "暂无公开详情", classes="activity-detail"),
                    title=value,
                    collapsed=not self.expanded or not bool(detail),
                    classes="activity-step",
                )
                await self.query_one(".activity-steps", Vertical).mount(row)
            self._rows[key] = row
        else:
            row.title = value
            row.query_one(".activity-detail", Static).update(
                detail or self._details.get(key) or "暂无公开详情"
            )
        self._statuses[key] = normalized
        self._titles[key] = title
        row.set_class(normalized in {"failed", "error"}, "failed")
        row.set_class(
            normalized in {"running", "waiting", "retrying"},
            "active",
        )
        if normalized in {"failed", "error"} and detail:
            row.collapsed = False
        if key == "model" and normalized == "retrying" and detail:
            row.collapsed = False

    @staticmethod
    def _safe_detail(value: Any, *, limit: int = 180) -> str:
        return redact_public_detail(value, limit=limit)

    async def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        for key, row in self._rows.items():
            row.collapsed = not expanded or not bool(self._details.get(key))

    async def update_event(self, event: dict) -> None:
        event_name = agent_event_name(event)
        if event_name == "model.retrying":
            delay_ms = event.get("retryInMs")
            delay = (
                max(0.0, float(delay_ms) / 1000)
                if isinstance(delay_ms, (int, float))
                else 0.0
            )
            self._retry_deadline = monotonic() + delay
            self._retry_attempt = int(event.get("retryAttempt") or 1)
            self._retry_max = int(event.get("maxRetries") or 1)
            self._retry_status = int(event.get("statusCode") or 0)
            error_type = str(event.get("errorType") or "").lower()
            detail = (
                f"{ceil(delay)}秒后重试 · "
                f"第{self._retry_attempt}/{self._retry_max}次"
            )
            title = (
                "模型连接超时"
                if "timeout" in error_type
                else (
                    "模型连接失败"
                    if "connect" in error_type
                    else "模型请求失败"
                )
            )
            if self._retry_status:
                title += f"（HTTP {self._retry_status}）"
            await self.upsert("model", title, "retrying", detail)
            return
        if event_name in {"message.delta", "message.completed", "model.event"}:
            had_retry = self._retry_deadline is not None
            self._retry_deadline = None
            if had_retry:
                self._details.pop("model", None)
            await self.upsert("model", "模型生成回答", "running")
            if had_retry and "model" in self._rows:
                self._rows["model"].collapsed = True
            return
        if event_name.startswith("step."):
            step = event.get("step") if isinstance(event.get("step"), dict) else event
            kind = str(step.get("kind") or "")
            name = str(step.get("name") or "")
            key = (
                "model"
                if kind == "model"
                else str(
                    step.get("stepId")
                    or step.get("id")
                    or f"{kind}:{name}"
                )
            )
            title = name or str(step.get("title") or "Agent步骤")
            duration = step.get("durationMs")
            detail = (
                f"{int(duration)}ms"
                if isinstance(duration, (int, float))
                else ""
            )
            await self.upsert(
                key,
                title,
                str(step.get("status") or "running"),
                detail,
            )
            return
        if event_name.startswith("tool."):
            call_id = str(
                event.get("toolCallId")
                or event.get("callId")
                or event.get("id")
                or ""
            )
            if not call_id:
                self._tool_sequence += 1
                call_id = str(self._tool_sequence)
            key = f"tool:{call_id}"
            title = self._titles.get(key) or tool_activity_title(event)
            if event_name == "tool.progress":
                output = _safe_shell_output(event.get("output"), lines=5)
                elapsed = event.get("elapsedSeconds")
                summary = []
                if isinstance(elapsed, (int, float)):
                    summary.append(f"{float(elapsed):.1f}s")
                lines = event.get("totalLines")
                if isinstance(lines, (int, float)) and int(lines) > 0:
                    summary.append(f"{int(lines)}行")
                size = _format_bytes(event.get("totalBytes"))
                if size:
                    summary.append(size)
                detail = output or "运行中…"
                if summary:
                    detail += "\n" + " · ".join(summary)
                self._tool_keys.add(key)
                self._active_tool_keys.add(key)
                await self.upsert(key, title, "running", detail)
                if key in self._rows:
                    self._rows[key].collapsed = False
                return
            latency = event.get("latencyMs")
            fragments = []
            if isinstance(latency, (int, float)):
                fragments.append(f"{int(latency)}ms")
            arguments = (
                event.get("arguments")
                or event.get("input")
            )
            safe_arguments = self._safe_detail(arguments, limit=240)
            if safe_arguments:
                fragments.append(f"输入 {safe_arguments}")
            output = event.get("output") or event.get("result")
            output_dict = output if isinstance(output, dict) else {}
            is_shell = str(event.get("toolName") or "") in {
                "run_sandbox_command",
                "sandbox_command",
            }
            shell_parts = []
            if is_shell:
                stdout = _safe_shell_output(output_dict.get("stdout"), lines=8)
                stderr = _safe_shell_output(output_dict.get("stderr"), lines=8)
                if stdout:
                    shell_parts.append(stdout)
                if stderr:
                    shell_parts.append(f"stderr\n{stderr}")
                exit_code = output_dict.get("exit_code")
                if isinstance(exit_code, (int, float)):
                    shell_parts.append(f"退出码 {int(exit_code)}")
            safe_output = (
                "\n".join(shell_parts)
                if shell_parts
                else self._safe_detail(output, limit=600)
            )
            if safe_output:
                fragments.append(f"结果 {safe_output}")
            error_message = self._safe_detail(
                event.get("errorMessage") or event.get("error"),
                limit=600,
            )
            if error_message:
                error_label, recovery = tool_error_presentation(
                    event.get("errorCode") or event.get("error_code"),
                    error_message,
                )
                fragments.append(f"{error_label}：{error_message}")
                fragments.append(f"建议：{recovery}")
            elif event.get("errorCode") or event.get("error_code"):
                error_label, recovery = tool_error_presentation(
                    event.get("errorCode") or event.get("error_code"),
                    "",
                )
                fragments.append(error_label)
                fragments.append(f"建议：{recovery}")
            detail = (
                "\n".join(fragments)
                if error_message
                else " · ".join(fragments)
            )
            status = str(
                event.get("normalizedStatus")
                or event.get("status")
                or ("failed" if event_name == "tool.failed" else "completed")
            )
            self._tool_keys.add(key)
            if status.lower() in {"failed", "error"}:
                self._failed_tool_keys.add(key)
            if status.lower() in {"running", "waiting"}:
                self._active_tool_keys.add(key)
            else:
                self._active_tool_keys.discard(key)
            await self.upsert(
                key,
                title,
                status,
                detail,
            )
            if is_shell and detail and key in self._rows:
                self._rows[key].collapsed = False
            return
        if event_name in {"run.updated", "run.plan_created"}:
            run = event.get("run")
            if not isinstance(run, dict):
                return
            steps = run.get("steps")
            if isinstance(steps, list):
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        continue
                    await self.upsert(
                        str(step.get("id") or step.get("stepId") or f"plan:{index}"),
                        str(step.get("title") or step.get("name") or f"步骤{index + 1}"),
                        str(step.get("status") or "pending"),
                    )
            return
        if event_name == "approval.required":
            call_id = str(
                event.get("toolCallId")
                or event.get("approvalId")
                or event.get("id")
                or "approval"
            )
            activity_event = {
                **event,
                "arguments": event.get("inputSummary"),
            }
            key = f"tool:{call_id}"
            self._tool_keys.add(key)
            self._active_tool_keys.add(key)
            await self.upsert(
                key,
                tool_activity_title(activity_event),
                "waiting",
                "等待权限确认",
            )

    def tick(self, elapsed: float | None = None) -> None:
        if self.finished:
            return
        value = monotonic() - self.started_at if elapsed is None else elapsed
        frames = ("✻", "✽", "✶", "✢")
        frame = frames[int(value * 4) % len(frames)]
        if self._retry_deadline is not None and "model" in self._rows:
            remaining = max(0, ceil(self._retry_deadline - monotonic()))
            detail = (
                f"{remaining}秒后重试 · "
                f"第{self._retry_attempt}/{self._retry_max}次"
            )
            self._details["model"] = detail
            self._rows["model"].query_one(
                ".activity-detail",
                Static,
            ).update(detail)
        activity_frame = ("·", "●", "•", "●")[int(value * 4) % 4]
        for key in tuple(self._active_tool_keys):
            row = self._rows.get(key)
            started = self._tool_started_at.get(key)
            if row is None or started is None:
                continue
            row.title = self._row_title(
                self._titles.get(key, "工具调用"),
                self._statuses.get(key, "running"),
                elapsed=monotonic() - started,
                frame=activity_frame,
            )
        self.query_one(".activity-header", Static).update(
            (
                f"{frame} 模型请求将在"
                f"{max(0, ceil(self._retry_deadline - monotonic()))}秒后重试"
                if self._retry_deadline is not None
                else f"{frame} 正在处理… ({value:.1f}s)"
            )
            + (
                f" · {len(self._active_tool_keys)}个工具运行中"
                if self._active_tool_keys
                else ""
            )
            + (f" · +{self._hidden_steps}早期步骤" if self._hidden_steps else "")
            + (" · Ctrl+O详情" if self._tool_keys else "")
        )

    async def finish(
        self,
        *,
        failed: bool = False,
        cancelled: bool = False,
    ) -> None:
        self.finished = True
        for key, status in tuple(self._statuses.items()):
            if status in {"running", "waiting", "retrying"}:
                await self.upsert(
                    key,
                    self._titles[key],
                    (
                        "cancelled"
                        if cancelled
                        else ("failed" if failed else "completed")
                    ),
                )
        self._active_tool_keys.clear()
        elapsed = monotonic() - self.started_at
        state_label = (
            "■ 已中断"
            if cancelled
            else ("× 执行失败" if failed else "✓ 执行完成")
        )
        tool_summary = (
            f" · {len(self._tool_keys)}次工具调用"
            if self._tool_keys
            else ""
        )
        failure_summary = (
            f" · {len(self._failed_tool_keys)}次失败"
            if self._failed_tool_keys
            else ""
        )
        self.query_one(".activity-header", Static).update(
            f"{state_label} ({elapsed:.1f}s){tool_summary}{failure_summary}"
            + (f" · +{self._hidden_steps}早期步骤" if self._hidden_steps else "")
            + (" · Ctrl+O详情" if self._tool_keys else "")
        )
        self.set_class(failed, "failed")
        self.set_class(cancelled, "cancelled")


class TranscriptView(VerticalScroll):
    """Conversation transcript with one mutable streaming response."""

    MAX_VISIBLE_BLOCKS = 200
    TRIM_TO_BLOCKS = 160

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: Static | None = None
        self._assistant_text = ""
        self._activity: RunActivity | None = None
        self._assistant_render_scheduled = False
        self._message_widgets: list[Static] = []
        self._records: dict[int, tuple[str, str, bool]] = {}
        self._archived_records: list[tuple[str, str, bool]] = []
        self._archive_widgets: list[Static] = []
        self._archive_summary: Static | None = None
        self.archive_expanded = False

    async def _register_block(
        self,
        widget: Static,
        kind: str,
        content: str,
        error: bool = False,
    ) -> None:
        self._message_widgets.append(widget)
        self._records[id(widget)] = (kind, content, error)
        await self._enforce_render_cap()

    async def _enforce_render_cap(self) -> None:
        if len(self._message_widgets) <= self.MAX_VISIBLE_BLOCKS:
            return
        count = len(self._message_widgets) - self.TRIM_TO_BLOCKS
        outgoing = self._message_widgets[:count]
        self._message_widgets = self._message_widgets[count:]
        for widget in outgoing:
            record = self._records.pop(id(widget), None)
            if record is not None:
                self._archived_records.append(record)
            await widget.remove()
        await self._render_archive_summary()

    async def _render_archive_summary(self) -> None:
        if not self._archived_records:
            return
        label = (
            f"已展开{len(self._archived_records)}条历史 · Ctrl+O收起"
            if self.archive_expanded
            else f"已折叠{len(self._archived_records)}条历史 · Ctrl+O展开"
        )
        if self._archive_summary is None:
            self._archive_summary = Static(label, classes="archive-summary")
            await self.mount(self._archive_summary, before=0)
        else:
            self._archive_summary.update(label)

    @staticmethod
    def _record_widget(record: tuple[str, str, bool]) -> Static:
        kind, content, error = record
        if kind == "user":
            value = Text()
            value.append("❯ ", style=f"bold {ACCENT}")
            value.append(content, style="bold")
            return Static(value, classes="message user-message archived-message")
        if kind == "assistant":
            return Static(
                RichMarkdown(content),
                classes="message assistant-message archived-message",
            )
        return Static(
            content,
            classes=(
                "notice error-notice archived-message"
                if error
                else "notice archived-message"
            ),
        )

    async def set_archive_expanded(self, expanded: bool) -> None:
        self.archive_expanded = expanded
        for widget in self._archive_widgets:
            await widget.remove()
        self._archive_widgets = []
        if expanded and self._archived_records and self._archive_summary is not None:
            for record in self._archived_records:
                widget = self._record_widget(record)
                self._archive_widgets.append(widget)
                await self.mount(widget, before=self._archive_summary)
        await self._render_archive_summary()

    async def show_welcome(
        self,
        *,
        version: str,
        model: str,
        workspace: str,
    ) -> None:
        panel = Vertical(classes="welcome-panel")
        panel.border_title = f" AgentLens v{version} "
        await self.mount(panel)

        brand = Text(justify="center")
        brand.append("●──────●  ", style=ACCENT)
        brand.append("AGENT", style=f"bold {ACCENT}")
        brand.append("LENS\n", style="bold")
        brand.append("│╲    ╱   ", style=ACCENT)
        brand.append("Agent CLI\n", style="dim")
        brand.append("│ ╲  ╱\n", style=ACCENT)
        brand.append("│  ╲╱\n", style=ACCENT)
        brand.append("●   ●", style=ACCENT)
        await panel.mount(Static(brand, classes="welcome-brand"))

        context = Text(justify="center")
        model_label = model if len(model) <= 22 else f"{model[:19]}…"
        workspace_label = (
            workspace
            if len(workspace) <= 38
            else f"{workspace[:10]}…{workspace[-27:]}"
        )
        context.append(model_label, style=ACCENT)
        context.append("  ·  ", style="dim")
        context.append(workspace_label, style="dim")
        await panel.mount(Static(context, classes="welcome-context"))

        hint = Text(justify="center")
        hint.append("输入 ", style="dim")
        hint.append("/", style=f"bold {ACCENT}")
        hint.append(" 查看命令", style="dim")
        await panel.mount(Static(hint, classes="welcome-tip"))

    async def add_user(self, content: str) -> None:
        value = Text()
        value.append("❯ ", style=f"bold {ACCENT}")
        value.append(content, style="bold")
        widget = Static(value, classes="message user-message")
        await self.mount(widget)
        await self._register_block(widget, "user", content)
        self._assistant = None
        self._assistant_text = ""
        self.scroll_end(animate=False)

    async def begin_run(self) -> None:
        self._activity = RunActivity()
        await self.mount(self._activity)
        await self._activity.begin()
        self.scroll_end(animate=False)

    async def update_activity(self, event: dict) -> None:
        if self._activity is not None:
            await self._activity.update_event(event)
            self.scroll_end(animate=False)

    async def finish_run(
        self,
        *,
        failed: bool = False,
        cancelled: bool = False,
    ) -> None:
        if self._activity is not None:
            await self._activity.finish(
                failed=failed,
                cancelled=cancelled,
            )
            self.scroll_end(animate=False)

    def tick_run(self, elapsed: float) -> None:
        if self._activity is not None:
            self._activity.tick(elapsed)

    async def append_assistant(self, content: str) -> None:
        if not content:
            return
        if self._assistant is None:
            self._assistant = Static(classes="message assistant-message")
            await self.mount(self._assistant)
            await self._register_block(self._assistant, "assistant", "")
        self._assistant_text += content
        if not self._assistant_render_scheduled:
            self._assistant_render_scheduled = True
            self.set_timer(0.04, self._flush_streaming_assistant)

    def _flush_streaming_assistant(self) -> None:
        if not self._assistant_render_scheduled:
            return
        self._assistant_render_scheduled = False
        if self._assistant is not None:
            self._assistant.update(self._assistant_text)
            self.scroll_end(animate=False)

    def finalize_assistant(self) -> None:
        self._assistant_render_scheduled = False
        if self._assistant is not None and self._assistant_text:
            self._assistant.update(RichMarkdown(self._assistant_text))
            self._records[id(self._assistant)] = (
                "assistant",
                self._assistant_text,
                False,
            )
            self.scroll_end(animate=False)

    async def add_notice(self, content: str, *, error: bool = False) -> None:
        widget = Static(
            content,
            classes="notice error-notice" if error else "notice",
        )
        await self.mount(widget)
        await self._register_block(widget, "notice", content, error)
        self.scroll_end(animate=False)

    async def add_recovery(
        self,
        title: str,
        detail: str,
        action: str,
        *,
        error: bool = False,
    ) -> None:
        value = Text()
        value.append(f"{'×' if error else '■'} {title}", style="bold red" if error else "bold")
        if detail:
            value.append(f"\n  {redact_public_detail(detail, limit=300)}", style="dim")
        value.append(f"\n  {action}", style=ACCENT)
        widget = Static(
            value,
            classes=(
                "recovery-notice error-recovery"
                if error
                else "recovery-notice"
            ),
        )
        await self.mount(widget)
        await self._register_block(
            widget,
            "notice",
            f"{title}\n{detail}\n{action}",
            error,
        )
        self.scroll_end(animate=False)

    async def clear_transcript(self) -> None:
        await self.remove_children()
        self._assistant = None
        self._assistant_text = ""
        self._activity = None
        self._assistant_render_scheduled = False
        self._message_widgets = []
        self._records = {}
        self._archived_records = []
        self._archive_widgets = []
        self._archive_summary = None
        self.archive_expanded = False

    async def set_activity_expanded(self, expanded: bool) -> None:
        if self._activity is not None:
            await self._activity.set_expanded(expanded)
        await self.set_archive_expanded(expanded)


class QueuePreview(Static):
    """Compact, Claude-style preview of input waiting behind the active turn."""

    def __init__(self) -> None:
        super().__init__(id="queue-preview")

    def update_queue(self, items: list[str], *, paused: bool) -> None:
        if not items:
            self.remove_class("visible")
            self.update("")
            return
        value = Text()
        label = "队列已暂停" if paused else "接下来"
        value.append(f"{label}  ", style="bold yellow" if paused else "dim")
        for index, item in enumerate(items[:3]):
            if index:
                value.append("  ·  ", style="dim")
            value.append(redact_public_detail(item, limit=64))
        if len(items) > 3:
            value.append(f"  ·  +{len(items) - 3}项", style="dim")
        value.append(
            "  /continue继续" if paused else "  Ctrl+T管理",
            style=ACCENT,
        )
        self.update(value)
        self.add_class("visible")


class HistorySearchBar(Horizontal):
    class Preview(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class Accepted(Message):
        pass

    class Cancelled(Message):
        pass

    def __init__(self) -> None:
        super().__init__(id="history-search")
        self.history: list[str] = []
        self.original = ""
        self.match = ""

    def compose(self):
        yield Static("搜索历史：", id="history-search-label")
        yield Input(placeholder="输入关键词", id="history-search-input")

    def open(self, history: list[str], original: str) -> None:
        self.history = list(history)
        self.original = original
        self.match = original
        self.add_class("visible")
        search = self.query_one("#history-search-input", Input)
        search.value = ""
        search.focus()

    def close(self) -> None:
        self.remove_class("visible")

    @on(Input.Changed)
    def handle_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        self.match = next(
            (
                item
                for item in reversed(self.history)
                if not query or query in item.lower()
            ),
            "",
        )
        label = self.query_one("#history-search-label", Static)
        label.update("搜索历史：" if self.match else "没有匹配：")
        self.post_message(self.Preview(self.match or self.original))

    @on(Input.Submitted)
    def handle_submitted(self) -> None:
        self.post_message(self.Accepted())

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.post_message(self.Cancelled())
            return
        await super()._on_key(event)


PASTE_THRESHOLD = 10_000
PASTE_PREVIEW = 500
PASTE_REFERENCE_PATTERN = re.compile(
    r"\n?\[粘贴内容 #(\d+)：已折叠 \d+ 字符\]\n?"
)


class Composer(TextArea):
    class Submitted(Message):
        pass

    class CommandQuery(Message):
        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    class CommandMove(Message):
        def __init__(self, delta: int) -> None:
            self.delta = delta
            super().__init__()

    class CommandAccepted(Message):
        pass

    class CommandDismissed(Message):
        pass

    class HistoryRequested(Message):
        pass

    def __init__(self) -> None:
        super().__init__(
            "",
            id="composer",
            soft_wrap=True,
            show_line_numbers=False,
            highlight_cursor_line=False,
            placeholder="输入任务，/查看命令",
        )
        self.command_menu_open = False
        self.prompt_history: list[str] = []
        self.history_index: int | None = None
        self.history_draft = ""
        self.pasted_contents: dict[int, str] = {}
        self._paste_sequence = 0

    def set_history(self, values: list[str]) -> None:
        self.prompt_history = list(values[-500:])
        self.history_index = None
        self.history_draft = ""

    def clear_history(self) -> None:
        self.set_history([])

    def expanded_text(self) -> str:
        def replace(match: re.Match[str]) -> str:
            return self.pasted_contents.get(int(match.group(1)), match.group(0))

        return PASTE_REFERENCE_PATTERN.sub(replace, self.text)

    def _paste_preview(self, value: str) -> str:
        if len(value) <= PASTE_THRESHOLD:
            return value
        self._paste_sequence += 1
        reference = self._paste_sequence
        hidden_content = value[PASTE_PREVIEW:-PASTE_PREVIEW]
        self.pasted_contents[reference] = hidden_content
        hidden = len(hidden_content)
        return (
            value[:PASTE_PREVIEW]
            + f"\n[粘贴内容 #{reference}：已折叠 {hidden} 字符]\n"
            + value[-PASTE_PREVIEW:]
        )

    def on_paste(self, event: events.Paste) -> None:
        event.prevent_default()
        event.stop()
        self.insert(self._paste_preview(event.text))

    def remember(self, value: str) -> None:
        text = value.strip()
        if text and (
            not self.prompt_history or self.prompt_history[-1] != text
        ):
            self.prompt_history.append(text)
            self.prompt_history = self.prompt_history[-100:]
        self.history_index = None
        self.history_draft = ""

    def _move_history(self, delta: int) -> bool:
        if not self.prompt_history:
            return False
        if self.history_index is None:
            if delta > 0:
                return False
            self.history_draft = self.text
            self.history_index = len(self.prompt_history)
        self.history_index = max(
            0,
            min(len(self.prompt_history), self.history_index + delta),
        )
        value = (
            self.history_draft
            if self.history_index == len(self.prompt_history)
            else self.prompt_history[self.history_index]
        )
        self.load_text(value)
        return True

    def on_text_area_changed(self) -> None:
        self.post_message(self.CommandQuery(self.text))

    async def _on_key(self, event: events.Key) -> None:
        if self.command_menu_open:
            if event.key in {"up", "down"}:
                event.prevent_default()
                event.stop()
                self.post_message(
                    self.CommandMove(-1 if event.key == "up" else 1)
                )
                return
            if event.key in {"tab", "right", "enter"}:
                event.prevent_default()
                event.stop()
                self.post_message(self.CommandAccepted())
                return
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self.post_message(self.CommandDismissed())
                return
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted())
            return
        if event.key in {"up", "down"} and "\n" not in self.text:
            if self._move_history(-1 if event.key == "up" else 1):
                event.prevent_default()
                event.stop()
                return
        if event.key == "ctrl+r" and self.prompt_history:
            event.prevent_default()
            event.stop()
            self.post_message(self.HistoryRequested())
            return
        await super()._on_key(event)


class StatusBar(Static):
    def update_status(
        self,
        *,
        model: str,
        workspace: str,
        phase: str,
        queue_size: int,
        tool_calls: int,
        permissions: int,
        permission_mode: str,
    ) -> None:
        short_workspace = workspace.rstrip("/\\").split("/")[-1].split("\\")[-1]
        parts = [model, short_workspace or workspace, permission_mode]
        if tool_calls:
            parts.append(f"工具 {tool_calls}")
        if queue_size:
            parts.append(f"队列 {queue_size}")
        if permissions:
            parts.append(f"单项授权 {permissions}")
        self.update("  ·  ".join(parts))
