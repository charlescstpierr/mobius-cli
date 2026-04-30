"""Output-format seam: one interface, JSON and Markdown adapters."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from enum import IntEnum
from typing import Any, Protocol, runtime_checkable

import typer


@runtime_checkable
class _ModelPayload(Protocol):
    def model_dump_json(self) -> str:
        """Return a compact JSON representation."""


class _CliContext(Protocol):
    @property
    def json_output(self) -> bool:
        """Whether the global CLI JSON flag is set."""


class Formatter:
    """CLI output formatter that centralises the json-vs-text dispatch.

    Every command handler builds a *payload* (serialisable dict/list) and an
    optional *text* representation.  ``Formatter.emit`` routes to the right
    adapter so that individual commands never repeat the ``if json_output: …
    else: …`` pattern.
    """

    def __init__(self, *, json_output: bool = False) -> None:
        self.json_output = json_output

    def emit(self, payload: Any, *, text: str | list[str] | Callable[[], None]) -> None:
        """Write *payload* as JSON or *text* to stdout."""
        output = _output_adapter()
        if self.json_output:
            output.write_json(self.to_json(payload))
        else:
            if callable(text):
                text()
            elif isinstance(text, list):
                for line in text:
                    output.write_line(line)
            else:
                output.write_line(text)

    def to_json(self, payload: Any) -> str:
        """Return the byte-compatible JSON rendering for *payload*."""
        if isinstance(payload, str):
            return payload
        if isinstance(payload, _ModelPayload):
            return payload.model_dump_json()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def write_line(self, line: str) -> None:
        """Unconditional line to stdout (use sparingly; prefer :meth:`emit`)."""
        _output_adapter().write_line(line)

    def write_error(self, message: str) -> None:
        """Diagnostic line to stderr."""
        _output_adapter().write_error_line(message)

    def exit_with(self, code: int | IntEnum) -> None:
        """Raise ``typer.Exit`` with the given code."""
        raise typer.Exit(code=int(code))

    def exit_ok(self) -> None:
        """Exit 0."""
        self.exit_with(0)

    def exit_error(self) -> None:
        """Exit 1."""
        self.exit_with(1)


class JsonFormatter(Formatter):
    """Adapter that always writes JSON output."""

    def __init__(self) -> None:
        super().__init__(json_output=True)


class MarkdownFormatter(Formatter):
    """Adapter that always writes Markdown/text output."""

    def __init__(self) -> None:
        super().__init__(json_output=False)


def get_formatter(context: _CliContext, *, json_output: bool | None = None) -> Formatter:
    """Build a :class:`Formatter` respecting the CLI context.

    A command-local ``json_output`` flag is OR'd with the global one so that
    both ``mobius --json doctor`` and ``mobius doctor --json`` work.
    """
    use_json = context.json_output if json_output is None else context.json_output or json_output
    return Formatter(json_output=use_json)


def _output_adapter() -> Any:
    """Return the compatibility output module for monkeypatch-friendly writes."""
    from mobius.cli import output

    return output


def _no_color() -> bool:
    return os.environ.get("NO_COLOR") is not None


def _console() -> type[Any]:
    from rich.console import Console

    return Console


def write_line(message: str) -> None:
    """Write one data line to stdout without terminal-width wrapping."""
    _console()(file=sys.stdout, no_color=_no_color(), soft_wrap=True).print(message)


def write_json(message: str) -> None:
    """Write one compact JSON payload to stdout."""
    sys.stdout.write(f"{message}\n")


def write_rich(renderable: Any, *, width: int | None = None) -> None:
    """Write a Rich renderable to stdout."""
    _console()(file=sys.stdout, no_color=_no_color(), soft_wrap=True, width=width).print(renderable)


def write_error_line(message: str) -> None:
    """Write one diagnostic line to stderr."""
    sys.stderr.write(f"{message}\n")
