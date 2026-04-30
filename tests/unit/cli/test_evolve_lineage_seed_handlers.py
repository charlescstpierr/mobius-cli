"""Direct unit tests for evolve, lineage, seed CLI command handlers."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from unittest import mock

import pytest
import typer

from mobius.cli.main import CliContext, ExitCode


@pytest.fixture
def evolve_command(reloaded_command) -> ModuleType:
    return reloaded_command("mobius.cli.commands.evolve")


@pytest.fixture
def lineage_command(reloaded_command) -> ModuleType:
    return reloaded_command("mobius.cli.commands.lineage")


@pytest.fixture
def seed_command(reloaded_command) -> ModuleType:
    return reloaded_command("mobius.cli.commands.seed")


def _ctx(tmp_path: Path, *, json_output: bool = False) -> CliContext:
    return CliContext(json_output=json_output, mobius_home=tmp_path / "home")


# -------------------------------- evolve --------------------------------


def test_evolve_handler_source_missing_exits_4(tmp_path: Path, evolve_command: ModuleType) -> None:
    from mobius.workflow.evolve import EvolutionSourceNotFoundError

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise EvolutionSourceNotFoundError("source not found: run_x")

    with (
        mock.patch.object(evolve_command, "prepare_evolution", side_effect=_explode),
        pytest.raises(typer.Exit) as exc,
    ):
        evolve_command.run(_ctx(tmp_path), source_run_id="run_x", generations=1)
    assert exc.value.exit_code == int(ExitCode.NOT_FOUND)


def test_evolve_handler_neither_detach_nor_fg(tmp_path: Path, evolve_command: ModuleType) -> None:
    fake_prepared = mock.MagicMock()
    fake_prepared.evolution_id = "evo_z"
    with (
        mock.patch.object(evolve_command, "prepare_evolution", return_value=fake_prepared),
        pytest.raises(typer.Exit) as exc,
    ):
        evolve_command.run(
            _ctx(tmp_path),
            source_run_id="run_x",
            generations=1,
            detach=False,
            foreground=False,
        )
    assert exc.value.exit_code == int(ExitCode.USAGE)


def test_evolve_handler_foreground_invokes_run_foreground(
    tmp_path: Path, evolve_command: ModuleType
) -> None:
    fake_prepared = mock.MagicMock()
    fake_prepared.evolution_id = "evo_a"
    with (
        mock.patch.object(evolve_command, "prepare_evolution", return_value=fake_prepared),
        mock.patch.object(
            evolve_command, "run_foreground", return_value=int(ExitCode.OK)
        ) as run_fg,
    ):
        evolve_command.run(
            _ctx(tmp_path),
            source_run_id="run_x",
            generations=1,
            detach=True,
            foreground=True,
        )
    run_fg.assert_called_once()


def test_evolve_handler_foreground_nonzero_exits(
    tmp_path: Path, evolve_command: ModuleType
) -> None:
    fake_prepared = mock.MagicMock()
    fake_prepared.evolution_id = "evo_a"
    with (
        mock.patch.object(evolve_command, "prepare_evolution", return_value=fake_prepared),
        mock.patch.object(evolve_command, "run_foreground", return_value=2),
        pytest.raises(typer.Exit) as exc,
    ):
        evolve_command.run(
            _ctx(tmp_path),
            source_run_id="run_x",
            generations=1,
            foreground=True,
            detach=False,
        )
    assert exc.value.exit_code == 2


def test_evolve_handler_detached_json_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], evolve_command: ModuleType
) -> None:
    fake_paths = mock.MagicMock()
    fake_paths.log_file = tmp_path / "log"
    fake_prepared = mock.MagicMock()
    fake_prepared.evolution_id = "evo_q"
    fake_prepared.source_run_id = "run_q"
    fake_prepared.generations = 3
    fake_prepared.paths = fake_paths

    with (
        mock.patch.object(evolve_command, "prepare_evolution", return_value=fake_prepared),
        mock.patch.object(evolve_command, "start_detached_worker", return_value=99),
    ):
        evolve_command.run(
            _ctx(tmp_path, json_output=True),
            source_run_id="run_q",
            generations=3,
        )
    payload = json.loads(capsys.readouterr().out)
    assert payload["evolution_id"] == "evo_q"
    assert payload["mode"] == "detach"
    assert payload["pid"] == 99


def test_evolve_handler_detached_plain_emits_evolution_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], evolve_command: ModuleType
) -> None:
    fake_paths = mock.MagicMock()
    fake_paths.log_file = tmp_path / "log"
    fake_prepared = mock.MagicMock()
    fake_prepared.evolution_id = "evo_p"
    fake_prepared.source_run_id = "run_q"
    fake_prepared.generations = 1
    fake_prepared.paths = fake_paths
    with (
        mock.patch.object(evolve_command, "prepare_evolution", return_value=fake_prepared),
        mock.patch.object(evolve_command, "start_detached_worker", return_value=99),
    ):
        evolve_command.run(_ctx(tmp_path), source_run_id="r", generations=1)
    assert capsys.readouterr().out.strip() == "evo_p"


def test_evolve_worker_passes_through_exit(tmp_path: Path, evolve_command: ModuleType) -> None:
    with mock.patch.object(evolve_command, "execute_evolution", return_value=int(ExitCode.OK)):
        evolve_command.worker_evolve(_ctx(tmp_path), evolution_id="evo_w")
    with mock.patch.object(evolve_command, "execute_evolution", return_value=1):
        with pytest.raises(typer.Exit) as exc:
            evolve_command.worker_evolve(_ctx(tmp_path), evolution_id="evo_w")
        assert exc.value.exit_code == 1


# -------------------------------- lineage --------------------------------


def test_lineage_handler_no_id_exits_2(tmp_path: Path, lineage_command: ModuleType) -> None:
    with pytest.raises(SystemExit) as exc:
        lineage_command.run(_ctx(tmp_path), None)
    assert exc.value.code == int(ExitCode.USAGE)


def test_lineage_handler_hash_unknown_exits_4(tmp_path: Path, lineage_command: ModuleType) -> None:
    with (
        mock.patch.object(lineage_command, "replay_hash_for_aggregate", return_value=None),
        pytest.raises(SystemExit) as exc,
    ):
        lineage_command.run(_ctx(tmp_path), aggregate_id="run_x", hash_output=True)
    assert exc.value.code == int(ExitCode.NOT_FOUND)


def test_lineage_handler_hash_prints_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], lineage_command: ModuleType
) -> None:
    with mock.patch.object(lineage_command, "replay_hash_for_aggregate", return_value="deadbeef"):
        lineage_command.run(_ctx(tmp_path), aggregate_id="run_y", hash_output=True)
    assert capsys.readouterr().out.strip() == "deadbeef"


def test_lineage_handler_unknown_aggregate_exits_4(
    tmp_path: Path, lineage_command: ModuleType
) -> None:
    with (
        mock.patch.object(lineage_command, "build_lineage", return_value=None),
        pytest.raises(SystemExit) as exc,
    ):
        lineage_command.run(_ctx(tmp_path), aggregate_id="run_x")
    assert exc.value.code == int(ExitCode.NOT_FOUND)


# -------------------------------- seed --------------------------------


def test_seed_handler_validation_error(tmp_path: Path, seed_command: ModuleType) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("project_type: greenfield\n", encoding="utf-8")
    with pytest.raises(typer.Exit) as exc:
        seed_command.run(_ctx(tmp_path), str(bad))
    assert exc.value.exit_code == int(ExitCode.VALIDATION)


def test_seed_handler_unknown_session_id_exits_4(tmp_path: Path, seed_command: ModuleType) -> None:
    from mobius.persistence.event_store import EventStore

    home = tmp_path / "home"
    with EventStore(home / "events.db"):
        pass
    with pytest.raises(typer.Exit) as exc:
        seed_command.run(_ctx(tmp_path), "session_does_not_exist")
    assert exc.value.exit_code == int(ExitCode.NOT_FOUND)


def test_seed_handler_emits_session_id_then_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seed_command: ModuleType
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Seed handler unit test goal.
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )

    seed_command.run(_ctx(tmp_path), str(spec), json_output=True)
    captured = capsys.readouterr().out.strip()
    payload = json.loads(captured)
    assert payload["session_id"].startswith("seed_seed-handler-unit-test-goal_")
    assert payload["event_count"] == 3
    assert payload["grade"] is None


def test_seed_handler_emits_plain_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seed_command: ModuleType
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Seed handler plain id.
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )
    seed_command.run(_ctx(tmp_path), str(spec))
    out = capsys.readouterr().out.strip()
    assert out.startswith("seed_seed-handler-plain-id_")


def test_seed_handler_validate_emits_bronze_grade_event(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], seed_command: ModuleType
) -> None:
    from mobius.persistence.event_store import EventStore

    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Seed handler bronze grade.
constraints:
  - C1
success_criteria:
  - S1
""".strip(),
        encoding="utf-8",
    )

    seed_command.run(_ctx(tmp_path), str(spec), json_output=True, validate=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["event_count"] == 4
    assert payload["grade"] == "bronze"
    assert payload["criteria_met"] == 4
    assert payload["criteria_total"] == 4

    with EventStore(tmp_path / "home" / "events.db", read_only=True) as store:
        grade_events = [
            event
            for event in store.read_events(payload["session_id"])
            if event.type == "spec.grade_assigned"
        ]
    assert len(grade_events) == 1
    grade_payload = grade_events[0].payload_data
    assert grade_payload["grade"] == "bronze"
    assert grade_payload["criteria_met"] == 4
    assert grade_payload["criteria_total"] == 4
