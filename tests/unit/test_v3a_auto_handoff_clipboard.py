from __future__ import annotations

from pathlib import Path

from mobius.v3a.phase_router.handoff import (
    detect_clipboard_tool,
    render_auto_handoff_display,
)


def fake_which(*available: str):
    def _which(name: str) -> str | None:
        if name in available:
            return f"/usr/bin/{name}"
        return None

    return _which


def test_clipboard_detection_prefers_pbcopy_on_macos() -> None:
    tool = detect_clipboard_tool(
        platform="darwin",
        env={},
        which=fake_which("pbcopy", "wl-copy", "xclip"),
    )

    assert tool is not None
    assert tool.name == "pbcopy"
    assert tool.command == ("/usr/bin/pbcopy",)


def test_clipboard_detection_prefers_wl_copy_on_wayland() -> None:
    tool = detect_clipboard_tool(
        platform="linux",
        env={"WAYLAND_DISPLAY": "wayland-1", "DISPLAY": ":0"},
        which=fake_which("wl-copy", "xclip"),
    )

    assert tool is not None
    assert tool.name == "wl-copy"
    assert tool.command == ("/usr/bin/wl-copy",)


def test_clipboard_detection_prefers_xclip_on_x11() -> None:
    tool = detect_clipboard_tool(
        platform="linux",
        env={"DISPLAY": ":0"},
        which=fake_which("xclip"),
    )

    assert tool is not None
    assert tool.name == "xclip"
    assert tool.command == ("/usr/bin/xclip", "-selection", "clipboard")


def test_clipboard_detection_falls_through_gracefully() -> None:
    assert detect_clipboard_tool(platform="linux", env={}, which=fake_which()) is None


def test_auto_handoff_display_shows_prompt_path_without_clipboard() -> None:
    prompt_path = Path("/tmp/mobius/handoff-prompt.md")

    rendered = render_auto_handoff_display(
        prompt_path=prompt_path,
        copied_to_clipboard=False,
        clipboard_tool=None,
    )

    assert "Mobius's job is done" in rendered
    assert f"handoff prompt path: {prompt_path}" in rendered
    assert "open in claude" in rendered
    assert "open in codex" in rendered
    assert "open in hermes" in rendered
    assert "quit" in rendered
