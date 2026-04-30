from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict
from pytest import CaptureFixture

from mobius.cli.formatter import Formatter, JsonFormatter, MarkdownFormatter, get_formatter


@dataclass(frozen=True)
class _Context:
    json_output: bool


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    beta: int
    alpha: str


def test_formatter_emits_sorted_compact_json_for_plain_payload(
    capsys: CaptureFixture[str],
) -> None:
    formatter = Formatter(json_output=True)

    formatter.emit({"beta": 2, "alpha": 1}, text="ignored")

    captured = capsys.readouterr()
    assert captured.out == '{"alpha":1,"beta":2}\n'
    assert captured.err == ""


def test_formatter_preserves_pydantic_model_json_order(
    capsys: CaptureFixture[str],
) -> None:
    formatter = JsonFormatter()

    formatter.emit(_Payload(beta=2, alpha="one"), text="ignored")

    assert capsys.readouterr().out == '{"beta":2,"alpha":"one"}\n'


def test_markdown_formatter_emits_each_text_line(capsys: CaptureFixture[str]) -> None:
    formatter = MarkdownFormatter()

    formatter.emit({"ignored": True}, text=["# Title", "- item"])

    assert capsys.readouterr().out == "# Title\n- item\n"


def test_get_formatter_honors_command_local_json_override(
    capsys: CaptureFixture[str],
) -> None:
    formatter = get_formatter(_Context(json_output=False), json_output=True)
    global_formatter = get_formatter(_Context(json_output=True), json_output=False)

    formatter.emit(json.loads('{"ok":true}'), text="not used")

    assert formatter.json_output is True
    assert global_formatter.json_output is True
    assert capsys.readouterr().out == '{"ok":true}\n'
