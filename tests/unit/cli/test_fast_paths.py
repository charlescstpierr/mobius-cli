"""Branch-coverage tests for the cli/__init__ fast-path entry points."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest import mock

import pytest

from mobius import cli as cli_module
from mobius.persistence.event_store import EventStore

# Capture the fast-path main() at import time before any mobius.cli.main
# submodule import can shadow the attribute on the package.
_FAST_MAIN = cli_module.main if callable(getattr(cli_module, "main", None)) else None


def _invoke_fast_main() -> None:
    """Call the fast-path main(), avoiding submodule shadowing."""
    if _FAST_MAIN is None:  # pragma: no cover — defensive
        # In some test orderings the submodule already shadows the function;
        # re-import directly from the package source to recover it.
        import importlib

        importlib.reload(cli_module)
        cli_module.main()
        return
    _FAST_MAIN()


def _set_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("MOBIUS_HOME", str(home))


# ---------------- _try_fast_status (run id status) ----------------


def test_fast_status_help_flag_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_home(monkeypatch, tmp_path / "h")
    assert cli_module._try_fast_status(["status", "run_x", "--help"]) is False


def test_fast_status_read_only_flag_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_home(monkeypatch, tmp_path / "h")
    assert cli_module._try_fast_status(["status", "run_x", "--read-only"]) is False


def test_fast_status_follow_flag_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_home(monkeypatch, tmp_path / "h")
    assert cli_module._try_fast_status(["status", "run_x", "--follow"]) is False


def test_fast_status_too_many_args_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_home(monkeypatch, tmp_path / "h")
    assert cli_module._try_fast_status(["status", "a", "b"]) is False


def test_fast_status_db_missing_exits_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "missing"
    _set_home(monkeypatch, home)
    with pytest.raises(SystemExit) as exc:
        cli_module._try_fast_status(["status", "run_x"])
    assert exc.value.code == 4


def test_fast_status_unknown_run_exits_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db"):
        pass
    _set_home(monkeypatch, home)
    with pytest.raises(SystemExit) as exc:
        cli_module._try_fast_status(["status", "run_missing"])
    assert exc.value.code == 4


def test_fast_status_returns_payload_for_known_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db") as store:
        store.create_session("run_a", runtime="run", metadata={}, status="completed")
    _set_home(monkeypatch, home)

    handled = cli_module._try_fast_status(["status", "run_a", "--json"])
    assert handled is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run_a"
    assert payload["state"] == "completed"


def test_fast_status_latest_returns_most_recent_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db") as store:
        store.create_session("run_first", runtime="run", metadata={}, status="completed")
        store.append_event("run_first", "run.started", {"goal": "First"})
        store.create_session("run_second", runtime="run", metadata={}, status="completed")
        store.append_event("run_second", "run.started", {"goal": "Second"})
    _set_home(monkeypatch, home)

    handled = cli_module._try_fast_status(["status", "latest", "--json"])

    assert handled is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run_second"


def test_fast_status_latest_without_runs_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db"):
        pass
    _set_home(monkeypatch, home)

    with pytest.raises(SystemExit) as exc:
        cli_module._try_fast_status(["status", "latest"])

    assert exc.value.code == 4


def test_fast_status_markdown_path_returns_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db") as store:
        store.create_session("run_md", runtime="run", metadata={}, status="completed")
    _set_home(monkeypatch, home)
    handled = cli_module._try_fast_status(["status", "run_md"])
    assert handled is True
    out = capsys.readouterr().out
    assert "# Run run_md" in out
    assert "completed" in out


# ---------------- _try_fast_store_status (no run id) ----------------


def test_fast_store_status_returns_after_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "auto"
    _set_home(monkeypatch, home)
    handled = cli_module._try_fast_store_status(["status"])
    assert handled is True
    out = capsys.readouterr().out
    assert "event_store=" in out
    assert "migrations_applied=true" in out


def test_fast_store_status_json_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "auto"
    _set_home(monkeypatch, home)
    handled = cli_module._try_fast_store_status(["--json", "status"])
    assert handled is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["migrations_applied"] is True
    assert payload["integrity_check"] == "ok"


def test_fast_store_status_falls_back_when_extra_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_home(monkeypatch, tmp_path / "h")
    assert cli_module._try_fast_store_status(["status", "extra"]) is False


def test_fast_store_status_falls_back_when_schema_table_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    # Create a DB without the schema_migrations table.
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE scratch (id INTEGER PRIMARY KEY)")
    finally:
        connection.close()
    _set_home(monkeypatch, home)
    assert cli_module._try_fast_store_status(["status"]) is False


def test_fast_store_status_falls_back_when_migrations_row_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.connection.execute("DELETE FROM schema_migrations")
    _set_home(monkeypatch, home)
    assert cli_module._try_fast_store_status(["status"]) is False


# ---------------- main() and dispatch ----------------


def test_main_help_uses_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mobius", "--help"])
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    _invoke_fast_main()
    assert "Usage: mobius" in buffer.getvalue()


def test_main_version_uses_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from mobius import __version__

    monkeypatch.setattr(sys, "argv", ["mobius", "--version"])
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    _invoke_fast_main()
    assert __version__ in buffer.getvalue()


def test_main_falls_back_to_typer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown args go through the slow path."""
    import importlib

    monkeypatch.setattr(sys, "argv", ["mobius", "config", "show"])
    called = mock.MagicMock()
    # The fast path imports `mobius.cli.main` and calls its top-level `main`.
    # Use importlib because the package attribute `main` is the fast-path
    # function, which shadows the submodule of the same name.
    slow_module = importlib.import_module("mobius.cli.main")
    monkeypatch.setattr(slow_module, "main", called)
    _invoke_fast_main()
    called.assert_called_once()


def test_pid_helpers_round_trip(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    pid_file.write_text("99999999\n", encoding="utf-8")
    pid = cli_module._read_pid(pid_file)
    assert pid == 99999999
    cli_module._cleanup_pid_file(pid_file)
    assert not pid_file.exists()
    # cleanup is idempotent
    cli_module._cleanup_pid_file(pid_file)


def test_read_pid_returns_none_for_garbage(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"
    pid_file.write_text("not-a-number\n", encoding="utf-8")
    assert cli_module._read_pid(pid_file) is None


def test_read_pid_returns_none_when_missing(tmp_path: Path) -> None:
    assert cli_module._read_pid(tmp_path / "missing") is None


def test_pid_is_live_handles_dead_process() -> None:
    # PID 1 should be alive on every POSIX system; an unlikely pid likely is dead.
    assert cli_module._pid_is_live(os.getpid()) is True
    assert cli_module._pid_is_live(2_999_999) is False


def test_mark_stale_no_pid_file_is_noop(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    with EventStore(home / "events.db") as store:
        store.create_session("run_z", runtime="run", metadata={}, status="running")
    cli_module._mark_stale_session_if_needed(home, home / "events.db", "run_z")
    # No exception means success
