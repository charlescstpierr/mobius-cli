"""Auto-handoff helpers for the end of ``mobius build`` Phase 4."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClipboardTool:
    """A detected clipboard command and the arguments needed to write to it."""

    name: str
    command: tuple[str, ...]


@dataclass(frozen=True)
class AutoHandoffResult:
    """Rendered Phase 4 handoff prompt and user-facing completion message."""

    agent: str
    prompt: str
    prompt_path: Path
    copied_to_clipboard: bool
    clipboard_tool: str | None
    display: str
    command: tuple[str, ...]


WhichFn = Callable[[str], str | None]


def known_handoff_agents() -> tuple[str, ...]:
    """Return the v2 handoff agents, reusing the canonical v2 symbol."""
    from mobius.agents import KNOWN_AGENTS

    return KNOWN_AGENTS


def auto_handoff_agent() -> str:
    """Return the default handoff agent used to render the prompt."""
    return known_handoff_agents()[0]


def detect_clipboard_tool(
    *,
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    which: WhichFn | None = None,
) -> ClipboardTool | None:
    """Detect the preferred clipboard command for the current runtime."""
    if which is None:
        import shutil

        which = shutil.which
    resolved_platform = sys.platform if platform is None else platform
    resolved_env = os.environ if env is None else env

    if resolved_platform == "darwin":
        pbcopy = which("pbcopy")
        if pbcopy is not None:
            return ClipboardTool("pbcopy", (pbcopy,))

    if resolved_env.get("WAYLAND_DISPLAY"):
        wl_copy = which("wl-copy")
        if wl_copy is not None:
            return ClipboardTool("wl-copy", (wl_copy,))

    if resolved_env.get("DISPLAY"):
        xclip = which("xclip")
        if xclip is not None:
            return ClipboardTool("xclip", (xclip, "-selection", "clipboard"))

    for name, command in (
        ("pbcopy", ("pbcopy",)),
        ("wl-copy", ("wl-copy",)),
        ("xclip", ("xclip", "-selection", "clipboard")),
    ):
        resolved = which(name)
        if resolved is not None:
            return ClipboardTool(name, (resolved, *command[1:]))
    return None


def run_auto_handoff(
    *,
    spec_path: Path,
    output_dir: Path,
    agent: str | None = None,
) -> AutoHandoffResult:
    """Render the v2 handoff prompt, copy it if possible, and build the menu."""
    selected_agent = auto_handoff_agent() if agent is None else agent
    prompt, command = _render_handoff_prompt(spec_path=spec_path, agent=selected_agent)
    prompt_path = output_dir / "handoff-prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    clipboard_tool = detect_clipboard_tool()
    copied = False
    if clipboard_tool is not None:
        copied = _copy_to_clipboard(prompt, clipboard_tool)

    return AutoHandoffResult(
        agent=selected_agent,
        prompt=prompt,
        prompt_path=prompt_path,
        copied_to_clipboard=copied,
        clipboard_tool=clipboard_tool.name if clipboard_tool is not None else None,
        display=render_auto_handoff_display(
            prompt_path=prompt_path,
            copied_to_clipboard=copied,
            clipboard_tool=clipboard_tool.name if clipboard_tool is not None else None,
        ),
        command=command,
    )


def render_auto_handoff_display(
    *,
    prompt_path: Path,
    copied_to_clipboard: bool,
    clipboard_tool: str | None,
) -> str:
    """Render the Phase 4 completion message and four-option menu."""
    if copied_to_clipboard and clipboard_tool is not None:
        clipboard_line = f"✓ Handoff prompt copied to clipboard via {clipboard_tool}."
    else:
        clipboard_line = f"Clipboard unavailable; handoff prompt path: {prompt_path}"
    return "\n".join(
        [
            "Mobius's job is done.",
            clipboard_line,
            "Choose your next agent:",
            "1. open in claude",
            "2. open in codex",
            "3. open in hermes",
            "4. quit",
        ]
    )


def _render_handoff_prompt(*, spec_path: Path, agent: str) -> tuple[str, tuple[str, ...]]:
    import subprocess

    command = ("mobius", "handoff", "--agent", agent, "--spec", str(spec_path))
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        msg = completed.stderr.strip() or completed.stdout.strip() or "mobius handoff failed"
        raise AutoHandoffError(msg)
    return completed.stdout, command


def _copy_to_clipboard(prompt: str, tool: ClipboardTool) -> bool:
    import subprocess

    completed = subprocess.run(
        tool.command,
        input=prompt,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


class AutoHandoffError(RuntimeError):
    """Raised when v2 handoff prompt rendering fails."""
