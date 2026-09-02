"""Terminal UI entry point for the AgentLens CLI."""

from __future__ import annotations

import os
from typing import Any


def run_tui(
    backend: Any,
    *,
    assume_yes: bool = False,
    startup_action: str = "",
) -> None:
    """Prefer the Ink UI on Linux and keep Textual as a safe fallback."""

    selected = os.getenv("KNOWFLOW_TUI", "auto").strip().lower()
    if selected not in {"auto", "ink", "textual"}:
        raise RuntimeError("KNOWFLOW_TUI只能是auto、ink或textual。")
    if selected != "textual":
        from .ink_launcher import InkTuiUnavailable, run_ink_tui

        try:
            if run_ink_tui(
                backend,
                assume_yes=assume_yes,
                startup_action=startup_action,
            ):
                return
        except InkTuiUnavailable:
            if selected == "ink":
                raise
    from .app import run_tui as run_textual_tui

    run_textual_tui(
        backend,
        assume_yes=assume_yes,
        startup_action=startup_action,
    )


__all__ = ["run_tui"]
