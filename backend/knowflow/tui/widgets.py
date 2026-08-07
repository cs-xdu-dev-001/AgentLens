from __future__ import annotations

from rich.markdown import Markdown as RichMarkdown
from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static, TextArea


class TranscriptView(VerticalScroll):
    """Conversation transcript with one mutable streaming response."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._assistant: Static | None = None
        self._assistant_text = ""

    async def add_user(self, content: str) -> None:
        await self.mount(Static(content, classes="message user-message"))
        self._assistant = None
        self._assistant_text = ""
        self.scroll_end(animate=False)

    async def append_assistant(self, content: str) -> None:
        if not content:
            return
        if self._assistant is None:
            self._assistant = Static(classes="message assistant-message")
            await self.mount(self._assistant)
        self._assistant_text += content
        self._assistant.update(RichMarkdown(self._assistant_text))
        self.scroll_end(animate=False)

    async def add_tool(
        self,
        name: str,
        status: str,
        latency_ms: int | None,
    ) -> None:
        ok = status in {"success", "succeeded", "completed"}
        marker = "●" if ok else "×"
        suffix = f"  {latency_ms}ms" if latency_ms is not None else ""
        value = Text()
        value.append(f"{marker} ", style="green" if ok else "red")
        value.append(name or "工具调用", style="bold")
        value.append(f"  {status or '完成'}{suffix}", style="dim")
        await self.mount(Static(value, classes="tool-card"))
        self.scroll_end(animate=False)

    async def add_notice(self, content: str, *, error: bool = False) -> None:
        await self.mount(
            Static(
                content,
                classes="notice error-notice" if error else "notice",
            )
        )
        self.scroll_end(animate=False)

    async def clear_transcript(self) -> None:
        await self.remove_children()
        self._assistant = None
        self._assistant_text = ""


class Composer(TextArea):
    class Submitted(Message):
        pass

    def __init__(self) -> None:
        super().__init__(
            "",
            id="composer",
            soft_wrap=True,
            show_line_numbers=False,
            highlight_cursor_line=False,
            placeholder="输入任务，/help查看命令",
        )

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted())
            return
        await super()._on_key(event)
