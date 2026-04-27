"""Direct unit tests for the interview command handler."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode


@pytest.fixture
def interview_command() -> ModuleType:
    sys.modules.pop("mobius.cli.commands.interview", None)
    return importlib.import_module("mobius.cli.commands.interview")


def _ctx(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


def _fixture(tmp_path: Path) -> Path:
    f = tmp_path / "f.yaml"
    f.write_text(
        """
project_type: greenfield
goal: Build a deterministic interview fixture handler.
constraints:
  - Constraint one with detail
success:
  - Outcome one with detail
""".strip(),
        encoding="utf-8",
    )
    return f


def test_interview_handler_rejects_interactive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    with pytest.raises(typer.Exit) as exc:
        interview_command.run(_ctx(tmp_path), non_interactive=False)
    assert exc.value.exit_code == int(ExitCode.VALIDATION)
    assert "interactive" in capsys.readouterr().err


def test_interview_handler_requires_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    with pytest.raises(typer.Exit) as exc:
        interview_command.run(_ctx(tmp_path), non_interactive=True, input_path=None)
    assert exc.value.exit_code == int(ExitCode.USAGE)
    assert "--input" in capsys.readouterr().err


def test_interview_handler_requires_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(typer.Exit) as exc:
        interview_command.run(
            _ctx(tmp_path),
            non_interactive=True,
            input_path=fixture,
            output_path=None,
        )
    assert exc.value.exit_code == int(ExitCode.USAGE)
    assert "--output" in capsys.readouterr().err


def test_interview_handler_validation_error_exits_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("project_type: marsfield\n", encoding="utf-8")
    with pytest.raises(typer.Exit) as exc:
        interview_command.run(
            _ctx(tmp_path),
            non_interactive=True,
            input_path=bad,
            output_path=tmp_path / "out.yaml",
        )
    assert exc.value.exit_code == int(ExitCode.VALIDATION)


def test_interview_handler_writes_spec_and_emits_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    fixture = _fixture(tmp_path)
    out = tmp_path / "out.yaml"
    interview_command.run(
        _ctx(tmp_path),
        non_interactive=True,
        input_path=fixture,
        output_path=out,
    )
    captured = capsys.readouterr().out
    assert "session_id=interview_" in captured
    assert "ambiguity_score=" in captured
    assert out.exists()
    assert "ambiguity_score" in out.read_text(encoding="utf-8")


def test_interview_handler_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], interview_command: ModuleType
) -> None:
    fixture = _fixture(tmp_path)
    out = tmp_path / "out.yaml"
    interview_command.run(
        _ctx(tmp_path, json_output=True),
        non_interactive=True,
        input_path=fixture,
        output_path=out,
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["session_id"].startswith("interview_")
    assert payload["passed_gate"] is True
