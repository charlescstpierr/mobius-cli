"""Regression tests pinning the v0.1.4 fixes from the multi-project UAT.

The v0.1.3 multi-project UAT report flagged:

* **Bug**: a single ``mobius cancel`` produced two ``run.cancelled`` events.
* **Bug**: the seed-spec validator rejected ``stages``, ``steps`` and
  ``matrix`` with the misleading message
  ``key 'X' cannot contain both scalar and …``.
* **Gap**: there was no ``mobius runs ls`` to list runs.
* **Gap**: ``mobius init`` had no project-type templates.
* **Gap**: ``mobius interview`` only worked in non-interactive fixture mode.

Each test below pins the fixed behaviour so we cannot regress.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

from mobius.cli.main import CliContext, ExitCode
from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.cancel import CancelResult, cancel_run
from mobius.workflow.run import get_run_paths
from mobius.workflow.seed import SeedSpecValidationError, load_seed_spec
from mobius.workflow.templates import detect_template, get_template, render_spec

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- Cancel
def _start_sigterm_aware_worker(run_id: str, db_path: Path) -> subprocess.Popen[str]:
    """Launch a child that mimics the v0.1.4 worker SIGTERM contract.

    The worker is authoritative: on SIGTERM it idempotently writes
    ``run.cancelled`` and updates the session row, then exits.
    """
    code = f"""
import signal, sqlite3, sys, time, uuid
DB = {str(db_path)!r}
RID = {run_id!r}
NOW = '2026-04-27T00:00:00.000000Z'
conn = sqlite3.connect(DB, timeout=10, isolation_level=None)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=30000')
conn.execute('PRAGMA foreign_keys=ON')
conn.execute('BEGIN IMMEDIATE')
conn.execute(
    'INSERT INTO events(event_id, aggregate_id, sequence, type, payload, created_at)'
    ' VALUES (?,?,?,?,?,?)',
    (str(uuid.uuid4()), RID, 1, 'run.started', '{{}}', NOW),
)
conn.execute('COMMIT')
conn.close()

def handler(signum, frame):
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=30000')
    c.execute('BEGIN IMMEDIATE')
    has = c.execute(
        "SELECT 1 FROM events WHERE aggregate_id=? AND type='run.cancelled' LIMIT 1",
        (RID,),
    ).fetchone()
    if has is None:
        seq = c.execute(
            'SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE aggregate_id = ?', (RID,)
        ).fetchone()[0]
        c.execute(
            'INSERT INTO events(event_id, aggregate_id, sequence, type, payload, created_at)'
            ' VALUES (?,?,?,?,?,?)',
            (str(uuid.uuid4()), RID, seq, 'run.cancelled', '{{"signal":"cancelled"}}', NOW),
        )
        c.execute(
            'UPDATE sessions SET ended_at=?, status=? WHERE session_id=?',
            (NOW, 'cancelled', RID),
        )
    c.execute('COMMIT')
    c.close()
    sys.exit(0)

signal.signal(signal.SIGTERM, handler)
print('ready', flush=True)
time.sleep(60)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line.strip() == "ready", f"worker did not become ready: {line!r}"
    return process


def _pid_is_live(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_cancel_emits_exactly_one_run_cancelled_event(tmp_path: Path) -> None:
    """v0.1.4 fix: one ``run.cancelled`` event per cancel call, never two."""
    paths = get_paths(tmp_path / "home")
    run_id = "run_cancel_one"
    with EventStore(paths.event_store) as store:
        store.create_session(run_id, runtime="run", status="running")

    process = _start_sigterm_aware_worker(run_id, paths.event_store)
    run_paths = get_run_paths(paths, run_id)
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    run_paths.pid_file.write_text(f"{process.pid}\n", encoding="utf-8")

    try:
        result = cancel_run(paths, run_id, grace_period=2.0)
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    assert result is CancelResult.CANCELLED
    with EventStore(paths.event_store, read_only=True) as store:
        types = [e.type for e in store.read_events(run_id)]
    assert types.count("run.cancelled") == 1, types


def test_cancel_emits_one_event_when_worker_already_dead(tmp_path: Path) -> None:
    """If the worker is gone, cancel still emits exactly one ``run.cancelled``."""
    paths = get_paths(tmp_path / "home")
    run_id = "run_cancel_stale"
    with EventStore(paths.event_store) as store:
        store.create_session(run_id, runtime="run", status="running")
    run_paths = get_run_paths(paths, run_id)
    run_paths.directory.mkdir(parents=True, exist_ok=True)
    # PID 0 (or 99999) is unlikely to be live.
    run_paths.pid_file.write_text("99999\n", encoding="utf-8")

    result = cancel_run(paths, run_id, grace_period=0.05)
    assert result is CancelResult.CANCELLED
    with EventStore(paths.event_store, read_only=True) as store:
        types = [e.type for e in store.read_events(run_id)]
    assert types.count("run.cancelled") == 1, types


# --------------------------------------------------------------------------- Seed errors
def test_unknown_spec_key_error_is_clear(tmp_path: Path) -> None:
    """v0.1.4 fix: unknown keys produce ``unknown spec key 'X'`` not the cryptic"
    " 'cannot contain both scalar and …' message."""
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        "project_type: greenfield\n"
        "goal: g\n"
        "constraints:\n  - c\n"
        "success_criteria:\n  - s\n"
        "stages:\n  - stage1\n",
        encoding="utf-8",
    )
    with pytest.raises(SeedSpecValidationError) as exc:
        load_seed_spec(spec)
    msg = str(exc.value)
    assert "unknown spec key" in msg
    assert "'stages'" in msg
    assert "Allowed top-level keys" in msg
    assert "cannot contain both scalar" not in msg


def test_seed_spec_accepts_steps_with_command_and_depends_on(tmp_path: Path) -> None:
    """``steps:`` is a first-class key recording named work items + ordering."""
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Express ordered work natively.
constraints:
  - c
success_criteria:
  - s
steps:
  - name: extract
    command: ./extract.sh
  - name: transform
    command: ./transform.sh
""".strip(),
        encoding="utf-8",
    )
    parsed = load_seed_spec(spec)
    assert [step.name for step in parsed.steps] == ["extract", "transform"]
    assert parsed.steps[0].command == "./extract.sh"


def test_seed_spec_accepts_matrix_with_axes(tmp_path: Path) -> None:
    """``matrix:`` declares axes for multi-platform projects."""
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: Ship on iOS and Android.
constraints:
  - c
success_criteria:
  - s
matrix:
  platform:
    - ios
    - android
""".strip(),
        encoding="utf-8",
    )
    parsed = load_seed_spec(spec)
    assert parsed.matrix == {"platform": ["ios", "android"]}


def test_seed_spec_rejects_steps_referring_to_missing_dependency(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
project_type: greenfield
goal: g
constraints:
  - c
success_criteria:
  - s
steps:
  - name: build
    depends_on:
      - bogus
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(SeedSpecValidationError, match="depends_on 'bogus'"):
        load_seed_spec(spec)


# --------------------------------------------------------------------------- Templates
def test_get_template_returns_blank_for_unknown_name() -> None:
    assert get_template("not-a-real-template").name == "blank"


def test_detect_template_picks_lib_for_pyproject(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    assert detect_template(tmp_path) == "lib"


def test_detect_template_picks_cli_for_cargo(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\n", encoding="utf-8")
    assert detect_template(tmp_path) == "cli"


def test_detect_template_picks_web_for_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    assert detect_template(tmp_path) == "web"


def test_detect_template_picks_mobile_for_pubspec(tmp_path: Path) -> None:
    (tmp_path / "pubspec.yaml").write_text("name: app\n", encoding="utf-8")
    assert detect_template(tmp_path) == "mobile"


def test_detect_template_picks_mobile_for_ios_android_pair(tmp_path: Path) -> None:
    (tmp_path / "ios").mkdir()
    (tmp_path / "android").mkdir()
    assert detect_template(tmp_path) == "mobile"


def test_detect_template_picks_docs_for_mkdocs(tmp_path: Path) -> None:
    (tmp_path / "mkdocs.yml").write_text("site_name: x\n", encoding="utf-8")
    assert detect_template(tmp_path) == "docs"


def test_detect_template_falls_back_to_blank(tmp_path: Path) -> None:
    assert detect_template(tmp_path) == "blank"


def test_render_spec_for_each_template_loads_as_valid_seed(tmp_path: Path) -> None:
    for name in ["web", "cli", "lib", "etl", "mobile", "docs", "blank"]:
        spec_path = tmp_path / f"{name}.yaml"
        spec_path.write_text(render_spec(get_template(name)), encoding="utf-8")
        spec = load_seed_spec(spec_path)
        assert spec.goal
        assert spec.constraints
        assert spec.success_criteria
        assert spec.template == name


# --------------------------------------------------------------------------- Init template flag
def test_init_command_applies_template(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOBIUS_HOME", raising=False)
    init_command = importlib.import_module("mobius.cli.commands.init")
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)

    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    init_command.run(ctx, workspace, template="etl")
    out = buffer.getvalue()

    assert "template=etl" in out
    spec_text = (workspace / "spec.yaml").read_text(encoding="utf-8")
    assert "template: etl" in spec_text
    assert "extract" in spec_text


def test_init_command_rejects_unknown_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import typer

    init_command = importlib.import_module("mobius.cli.commands.init")
    workspace = tmp_path / "ws"
    ctx = CliContext(json_output=False, mobius_home=tmp_path / "home")

    with pytest.raises(typer.Exit) as exc_info:
        init_command.run(ctx, workspace, template="bogus")
    assert int(exc_info.value.exit_code) == int(ExitCode.USAGE)


# --------------------------------------------------------------------------- Interview interactive
def test_interview_interactive_drives_with_scripted_stdin(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In interactive mode the handler reads answers from stdin and writes spec.yaml."""
    interview_command = importlib.import_module("mobius.cli.commands.interview")
    answers = "\n".join(
        [
            "greenfield",  # project_type
            "Build a deterministic interview test fixture",  # goal
            "first constraint",  # constraints
            "",  # finish
            "first criterion",  # success
            "",  # finish
        ]
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(answers + "\n"))
    monkeypatch.chdir(tmp_path)
    interview_command.run(
        CliContext(json_output=False, mobius_home=tmp_path / "home"),
        non_interactive=False,
        input_path=None,
        output_path=None,  # default ./spec.yaml
        template="blank",
    )
    spec = (tmp_path / "spec.yaml").read_text(encoding="utf-8")
    assert "Build a deterministic interview test fixture" in spec
    assert "session_id:" in spec


# --------------------------------------------------------------------------- Runs ls
def test_runs_ls_returns_empty_table_on_fresh_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_module = importlib.import_module("mobius.cli.commands.runs")
    ctx = CliContext(json_output=False, mobius_home=tmp_path / "home")
    runs_module.ls(ctx)
    captured = capsys.readouterr()
    assert "(no runs found)" in captured.out


def test_runs_ls_lists_runs_and_evolutions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_module = importlib.import_module("mobius.cli.commands.runs")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_a", runtime="run", status="running")
        store.append_event("run_a", "run.started", {})
        store.create_session("run_b", runtime="run", status="completed")
        store.create_session("seed_x", runtime="seed", status="completed")
    runs_module.ls(ctx)
    out = capsys.readouterr().out
    assert "run_a" in out
    assert "run_b" in out
    # By default seed sessions are not shown.
    assert "seed_x" not in out


def test_runs_ls_json_envelope_is_parseable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_module = importlib.import_module("mobius.cli.commands.runs")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("run_a", runtime="run", status="running")
    runs_module.ls(ctx, json_output=True)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["runs"], list)
    assert payload["runs"][0]["run_id"] == "run_a"


def test_runs_ls_show_all_includes_other_runtimes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runs_module = importlib.import_module("mobius.cli.commands.runs")
    home = tmp_path / "home"
    ctx = CliContext(json_output=False, mobius_home=home)
    paths = get_paths(home)
    with EventStore(paths.event_store) as store:
        store.create_session("seed_z", runtime="seed", status="completed")
    runs_module.ls(ctx, show_all=True)
    assert "seed_z" in capsys.readouterr().out


# --------------------------------------------------------------------------- Stop unused warnings
def _silence_unused() -> None:
    _ = (CliContext, ExitCode, signal, time, ModuleType)


_silence_unused()
