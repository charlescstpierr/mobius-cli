"""Unit tests for the run CLI command handler module."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode


@pytest.fixture
def run_command(reloaded_command) -> ModuleType:
    return reloaded_command("mobius.cli.commands.run")


def _ctx(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


def _spec(tmp_path: Path) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Run handler unit test goal.
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )
    return spec


def test_run_handler_validation_error_exits_3(tmp_path: Path, run_command: ModuleType) -> None:
    """Spec missing required keys raises SeedSpecValidationError → ExitCode.VALIDATION."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("project_type: greenfield\n", encoding="utf-8")

    with pytest.raises(typer.Exit) as exc:
        run_command.run(_ctx(tmp_path), spec_path=bad, detach=True, foreground=False)
    assert exc.value.exit_code == int(ExitCode.VALIDATION)


def test_run_handler_oserror_during_prepare_exits_3(
    tmp_path: Path, run_command: ModuleType
) -> None:
    """If reading the spec raises OSError, we exit with VALIDATION."""
    spec = _spec(tmp_path)

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated EIO")

    with (
        mock.patch.object(run_command, "prepare_run", side_effect=_explode),
        pytest.raises(typer.Exit) as exc,
    ):
        run_command.run(_ctx(tmp_path), spec_path=spec, detach=True, foreground=False)
    assert exc.value.exit_code == int(ExitCode.VALIDATION)


def test_run_handler_neither_detach_nor_foreground_exits_2(
    tmp_path: Path, run_command: ModuleType
) -> None:
    spec = _spec(tmp_path)
    with pytest.raises(typer.Exit) as exc:
        run_command.run(_ctx(tmp_path), spec_path=spec, detach=False, foreground=False)
    assert exc.value.exit_code == int(ExitCode.USAGE)


def test_run_handler_foreground_overrides_detach(tmp_path: Path, run_command: ModuleType) -> None:
    spec = _spec(tmp_path)

    fake_prepared = mock.MagicMock()
    fake_prepared.run_id = "run_abc"

    with (
        mock.patch.object(run_command, "prepare_run", return_value=fake_prepared),
        mock.patch.object(run_command, "run_foreground", return_value=int(ExitCode.OK)) as run_fg,
    ):
        run_command.run(_ctx(tmp_path), spec_path=spec, detach=True, foreground=True)
    run_fg.assert_called_once()


def test_run_handler_foreground_nonzero_exit(tmp_path: Path, run_command: ModuleType) -> None:
    spec = _spec(tmp_path)
    fake_prepared = mock.MagicMock()
    fake_prepared.run_id = "run_x"

    with (
        mock.patch.object(run_command, "prepare_run", return_value=fake_prepared),
        mock.patch.object(run_command, "run_foreground", return_value=1),
        pytest.raises(typer.Exit) as exc,
    ):
        run_command.run(_ctx(tmp_path), spec_path=spec, foreground=True, detach=False)
    assert exc.value.exit_code == 1


def test_run_handler_detached_json_output_emits_run_payload(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run_command: ModuleType
) -> None:
    spec = _spec(tmp_path)

    fake_paths = mock.MagicMock()
    fake_paths.log_file = tmp_path / "log"
    fake_prepared = mock.MagicMock()
    fake_prepared.run_id = "run_jjj"
    fake_prepared.paths = fake_paths

    with (
        mock.patch.object(run_command, "prepare_run", return_value=fake_prepared),
        mock.patch.object(run_command, "start_detached_worker", return_value=4242),
    ):
        run_command.run(
            _ctx(tmp_path, json_output=True),
            spec_path=spec,
            detach=True,
            foreground=False,
        )

    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["run_id"] == "run_jjj"
    assert payload["mode"] == "detach"
    assert payload["pid"] == 4242


def test_run_handler_detached_plain_output_emits_run_id_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run_command: ModuleType
) -> None:
    spec = _spec(tmp_path)
    fake_paths = mock.MagicMock()
    fake_paths.log_file = tmp_path / "log"
    fake_prepared = mock.MagicMock()
    fake_prepared.run_id = "run_kkk"
    fake_prepared.paths = fake_paths

    with (
        mock.patch.object(run_command, "prepare_run", return_value=fake_prepared),
        mock.patch.object(run_command, "start_detached_worker", return_value=10),
    ):
        run_command.run(_ctx(tmp_path), spec_path=spec, detach=True, foreground=False)

    out = capsys.readouterr().out.strip()
    assert out == "run_kkk"


def test_worker_run_passes_through_exit_code(tmp_path: Path, run_command: ModuleType) -> None:
    with mock.patch.object(run_command, "execute_run", return_value=int(ExitCode.OK)):
        run_command.worker_run(_ctx(tmp_path), run_id="run_y")
    with mock.patch.object(run_command, "execute_run", return_value=1):
        with pytest.raises(typer.Exit) as exc:
            run_command.worker_run(_ctx(tmp_path), run_id="run_y")
        assert exc.value.exit_code == 1
