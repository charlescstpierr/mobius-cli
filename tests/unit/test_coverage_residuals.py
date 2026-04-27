"""Supplementary tests targeting the residual coverage gaps after the M6 batch.

These tests deliberately exercise small error/edge branches in cli/__init__,
cli/commands/setup, cli/commands/seed, cli/commands/lineage, cli/main,
config, logging, persistence/event_store, and the workflow modules
(cancel, evolve, interview, lineage, qa, run, seed) that the broader test
suite leaves implicit. They are intentionally short, branch-focused, and
do not depend on subprocess fixtures.
"""

from __future__ import annotations

import json
import logging as stdlib_logging
import os
import sqlite3
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest

from mobius import cli as cli_module
from mobius.cli.commands import seed as seed_command_module
from mobius.cli.commands import setup as setup_command_module
from mobius.cli.main import CliContext
from mobius.config import (
    get_paths,
    load_config,
    save_config,
)
from mobius.logging import JsonLogFormatter, configure_logging, get_logger
from mobius.persistence.event_store import EventStore, _canonical_json, iso8601_utc_now
from mobius.workflow import cancel as cancel_module
from mobius.workflow import evolve as evolve_module
from mobius.workflow import interview as interview_module
from mobius.workflow import lineage as lineage_module
from mobius.workflow import qa as qa_module
from mobius.workflow import run as run_module
from mobius.workflow import seed as seed_module

# ---------------------------------------------------------------------------
# cli/__init__.py residuals
# ---------------------------------------------------------------------------


def test_fast_store_status_handles_corrupt_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A garbage DB should make the fast path fall back rather than crash."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    db_path.write_bytes(b"not a sqlite database header")
    monkeypatch.setenv("MOBIUS_HOME", str(home))
    # The fast path returns False on any sqlite error → caller falls through.
    assert cli_module._try_fast_store_status(["status"]) is False


def test_fast_status_handles_corrupt_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A garbage DB on the run-id fast path must surface an error and exit 1."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    db_path.write_bytes(b"not a sqlite database header")
    monkeypatch.setenv("MOBIUS_HOME", str(home))
    with pytest.raises(SystemExit) as exc:
        cli_module._try_fast_status(["status", "run_x"])
    assert exc.value.code == 1
    assert "status failed" in capsys.readouterr().err


def test_fast_bootstrap_store_failure_is_swallowed_and_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If bootstrap fails (e.g. mkdir denied), fast-path returns False."""
    home = tmp_path / "no_perms"
    monkeypatch.setenv("MOBIUS_HOME", str(home))
    with mock.patch.object(
        cli_module,
        "_fast_bootstrap_store",
        side_effect=OSError("simulated"),
    ):
        assert cli_module._try_fast_store_status(["status"]) is False


def test_fast_bootstrap_store_rolls_back_on_inner_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A BaseException inside the immediate transaction must trigger ROLLBACK."""
    home = tmp_path / "rollback_home"
    home.mkdir()
    db_path = home / "events.db"

    # Wrap sqlite3.connect so that the connection used inside _fast_bootstrap_store
    # raises mid-transaction. We use a delegating wrapper instead of mutating the
    # immutable sqlite3.Connection type itself.
    real_connect = sqlite3.connect

    class FailingConnection:
        def __init__(self, real: sqlite3.Connection) -> None:
            self._real = real
            self._saw_begin = False

        def execute(self, sql: str, *args: object) -> object:
            if "INSERT INTO aggregates" in sql and self._saw_begin:
                raise RuntimeError("boom inside transaction")
            if "BEGIN IMMEDIATE" in sql:
                self._saw_begin = True
            return self._real.execute(sql, *args)

        def executescript(self, sql: str) -> object:
            return self._real.executescript(sql)

        def close(self) -> None:
            self._real.close()

    def fake_connect(*args: object, **kwargs: object) -> object:
        return FailingConnection(real_connect(*args, **kwargs))

    monkeypatch.setattr(cli_module.sqlite3, "connect", fake_connect)
    with pytest.raises(RuntimeError):
        cli_module._fast_bootstrap_store(home, db_path)
    monkeypatch.undo()
    # Reopen via EventStore to confirm WAL replay still clean.
    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"


def test_pid_is_live_returns_true_on_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When os.kill raises PermissionError, the process is still considered alive."""
    monkeypatch.setattr(cli_module.os, "kill", mock.Mock(side_effect=PermissionError()))
    assert cli_module._pid_is_live(123_456) is True


def test_mark_stale_creates_session_when_missing_and_appends_crashed(
    tmp_path: Path,
) -> None:
    """The fast helper must INSERT a fresh session row when one is missing."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    # Initialize the schema.
    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"
    # Drop a stale evolution PID file so the fast helper hits the
    # "session is None / append crashed" branch.
    pid_file = home / "evolutions" / "evo_missing" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("2999999\n", encoding="utf-8")

    cli_module._mark_stale_session_if_needed(home, db_path, "evo_missing")

    with EventStore(db_path) as store:
        events = store.read_events("evo_missing")
        row = store.connection.execute(
            "SELECT runtime, status FROM sessions WHERE session_id = ?",
            ("evo_missing",),
        ).fetchone()
    assert row is not None
    assert row["runtime"] == "evolution"
    assert row["status"] == "crashed"
    # An evolution.crashed event was appended.
    assert any(event.type == "evolution.crashed" for event in events)


def test_mark_stale_skips_when_pid_alive(tmp_path: Path) -> None:
    """A live pid must short-circuit; the session must remain running."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.create_session("run_alive", runtime="run", metadata={}, status="running")
    pid_file = home / "runs" / "run_alive" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")

    cli_module._mark_stale_session_if_needed(home, db_path, "run_alive")
    with EventStore(db_path) as store:
        row = store.connection.execute(
            "SELECT status FROM sessions WHERE session_id = ?",
            ("run_alive",),
        ).fetchone()
    assert row["status"] == "running"


def test_mark_stale_terminal_session_just_cleans_pid_file(tmp_path: Path) -> None:
    """If the session is already terminal, the pid file is removed without writes."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.create_session("run_done", runtime="run", metadata={}, status="completed")
        store.end_session("run_done", status="completed")
    pid_file = home / "runs" / "run_done" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("99999999\n", encoding="utf-8")

    cli_module._mark_stale_session_if_needed(home, db_path, "run_done")
    assert not pid_file.exists()


# ---------------------------------------------------------------------------
# cli/commands/setup.py residuals
# ---------------------------------------------------------------------------


def test_setup_unknown_runtime_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown runtime must emit a usage error and exit 2."""
    import typer

    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    with pytest.raises(typer.Exit) as exc:
        setup_command_module.run(ctx, runtime="vim", scope="user")
    assert exc.value.exit_code == 2
    assert "unknown runtime" in capsys.readouterr().err


def test_setup_unknown_scope_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Unknown scope must emit a usage error and exit 2."""
    import typer

    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    with pytest.raises(typer.Exit) as exc:
        setup_command_module.run(ctx, runtime="claude", scope="cluster")
    assert exc.value.exit_code == 2
    assert "unknown scope" in capsys.readouterr().err


def test_setup_uninstall_with_no_inventory_emits_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Uninstall on a host with no inventory file must short-circuit cleanly."""
    monkeypatch.setenv("MOBIUS_TEST_HOME", str(tmp_path / "fakehome"))
    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    setup_command_module.run(ctx, runtime="claude", scope="user", uninstall=True, dry_run=False)
    out = capsys.readouterr().out
    assert "no Mobius inventory found" in out


def test_setup_uninstall_dry_run_emits_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run uninstall on a host with no inventory must say 'would remove'."""
    monkeypatch.setenv("MOBIUS_TEST_HOME", str(tmp_path / "fakehome2"))
    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    setup_command_module.run(ctx, runtime="claude", scope="user", uninstall=True, dry_run=True)
    out = capsys.readouterr().out
    assert "would remove" in out


def test_setup_uninstall_skips_modified_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An asset whose hash no longer matches the inventory must be skipped."""
    fake_home = tmp_path / "fhome"
    fake_home.mkdir()
    monkeypatch.setenv("MOBIUS_TEST_HOME", str(fake_home))

    # Synthesize an inventory referencing a tampered file.
    asset_path = fake_home / ".claude" / "skills" / "ghost" / "SKILL.md"
    asset_path.parent.mkdir(parents=True)
    asset_path.write_text("tampered\n", encoding="utf-8")

    inventory_dir = fake_home / ".mobius" / "installs"
    inventory_dir.mkdir(parents=True)
    inventory_path = inventory_dir / "claude-user.json"
    inventory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": "claude",
                "scope": "user",
                "assets": [
                    {"path": str(asset_path), "sha256": "0" * 64},
                    # An entry with non-string types must be ignored.
                    {"path": 12345, "sha256": "x"},
                    "not-a-dict",
                ],
            }
        ),
        encoding="utf-8",
    )

    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    setup_command_module.run(ctx, runtime="claude", scope="user", uninstall=True, dry_run=False)
    out = capsys.readouterr().out
    assert "skip modified" in out
    assert asset_path.exists()  # not removed because hash mismatched.


def test_setup_uninstall_skips_missing_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Inventory entry pointing at a missing file must produce 'skip missing'."""
    fake_home = tmp_path / "fhome3"
    fake_home.mkdir()
    monkeypatch.setenv("MOBIUS_TEST_HOME", str(fake_home))
    inventory_dir = fake_home / ".mobius" / "installs"
    inventory_dir.mkdir(parents=True)
    inventory_path = inventory_dir / "claude-user.json"
    inventory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": "claude",
                "scope": "user",
                "assets": [{"path": str(fake_home / "missing"), "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )
    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    setup_command_module.run(ctx, runtime="claude", scope="user", uninstall=True, dry_run=False)
    assert "skip missing" in capsys.readouterr().out


def test_setup_dry_run_emits_no_filesystem_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run install must report 'would install/update/skip' without copying."""
    fake_home = tmp_path / "fhome4"
    fake_home.mkdir()
    monkeypatch.setenv("MOBIUS_TEST_HOME", str(fake_home))
    ctx = CliContext(json_output=False, mobius_home=tmp_path)
    setup_command_module.run(ctx, runtime="claude", scope="user", dry_run=True, uninstall=False)
    out = capsys.readouterr().out
    assert "dry-run" in out
    # The home target dir must not have been populated.
    assert not (fake_home / ".claude" / "skills").exists()


# ---------------------------------------------------------------------------
# cli/commands/seed.py residuals
# ---------------------------------------------------------------------------


def test_seed_resolve_session_without_interview_event_raises(
    tmp_path: Path,
) -> None:
    """A session id that exists but has no interview.completed event must raise."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event("session-x", "run.started", {"goal": "x"})
    with pytest.raises(seed_module.SeedSpecValidationError):
        seed_command_module._resolve_spec_path(db_path, "session-x")


def test_seed_resolve_session_pointing_at_missing_file_raises(
    tmp_path: Path,
) -> None:
    """An interview output path that no longer exists must raise FileNotFoundError."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as store:
        store.append_event(
            "session-y",
            "interview.completed",
            {"output": str(tmp_path / "vanished.yaml")},
        )
    with pytest.raises(FileNotFoundError):
        seed_command_module._resolve_spec_path(db_path, "session-y")


def test_seed_resolve_session_unknown_id_raises(tmp_path: Path) -> None:
    """Unknown session id with no events must raise FileNotFoundError."""
    home = tmp_path / "home"
    home.mkdir()
    db_path = home / "events.db"
    with EventStore(db_path) as _store:
        pass
    with pytest.raises(FileNotFoundError):
        seed_command_module._resolve_spec_path(db_path, "nope")


# ---------------------------------------------------------------------------
# cli/main.py residuals — _handle_sigint and _version_callback
# ---------------------------------------------------------------------------


def test_handle_sigint_exits_130(capsys: pytest.CaptureFixture[str]) -> None:
    """The SIGINT handler must write 'interrupted' to stderr and exit 130."""
    import typer

    from mobius.cli.main import _handle_sigint

    with pytest.raises(typer.Exit) as exc:
        _handle_sigint(2, None)
    assert exc.value.exit_code == 130
    assert "interrupted" in capsys.readouterr().err


def test_version_callback_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    """--version prints the version and exits 0."""
    import typer

    from mobius import __version__
    from mobius.cli.main import _version_callback

    with pytest.raises(typer.Exit) as exc:
        _version_callback(True)
    assert exc.value.exit_code == 0
    assert __version__ in capsys.readouterr().out


def test_version_callback_noop_when_false() -> None:
    """When the flag is False the callback does nothing."""
    from mobius.cli.main import _version_callback

    _version_callback(False)


# ---------------------------------------------------------------------------
# config.py residuals — invalid value rejection paths
# ---------------------------------------------------------------------------


def test_load_config_rejects_non_object_json(tmp_path: Path) -> None:
    """A config file containing a JSON array (not an object) must raise."""
    paths = get_paths(tmp_path)
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    # Create the event store so _ensure_state succeeds.
    with EventStore(paths.event_store) as _store:
        pass
    paths.config_file.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_config(tmp_path)


def test_default_home_uses_env_when_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Setting MOBIUS_HOME must override the default location."""
    from mobius.config import default_home

    monkeypatch.setenv("MOBIUS_HOME", str(tmp_path))
    assert default_home() == tmp_path


def test_default_home_falls_back_to_dot_mobius(monkeypatch: pytest.MonkeyPatch) -> None:
    """When MOBIUS_HOME is unset, default_home() returns ~/.mobius."""
    from mobius.config import default_home

    monkeypatch.delenv("MOBIUS_HOME", raising=False)
    assert default_home() == Path.home() / ".mobius"


def test_save_config_idempotent_for_unchanged_value(tmp_path: Path) -> None:
    """Saving the same value twice must not rewrite the file."""
    save_config(tmp_path, "profile", "prod")
    paths = get_paths(tmp_path)
    first_mtime = paths.config_file.stat().st_mtime_ns
    save_config(tmp_path, "profile", "prod")
    assert paths.config_file.stat().st_mtime_ns == first_mtime


# ---------------------------------------------------------------------------
# logging.py residuals
# ---------------------------------------------------------------------------


def test_configure_logging_routes_to_stderr() -> None:
    """A configured root logger must dispatch records via stderr handlers."""
    configure_logging(json_output=False)
    handlers = stdlib_logging.getLogger().handlers
    assert handlers
    assert all(getattr(handler, "stream", None) is sys.stderr for handler in handlers)


def test_get_logger_configures_logging_when_unconfigured() -> None:
    """get_logger must auto-configure when no handlers exist."""
    root_logger = stdlib_logging.getLogger()
    saved = root_logger.handlers
    try:
        root_logger.handlers = []
        logger = get_logger("mobius.test.unconfigured")
        assert logger is not None
        assert root_logger.handlers
    finally:
        root_logger.handlers = saved


def test_json_log_formatter_includes_exception_payload() -> None:
    """The JSON formatter must include 'exception' when exc_info is present."""
    formatter = JsonLogFormatter()
    try:
        raise RuntimeError("boom-formatter")
    except RuntimeError:
        record = stdlib_logging.LogRecord(
            name="mobius",
            level=stdlib_logging.ERROR,
            pathname="x",
            lineno=1,
            msg="payload",
            args=(),
            exc_info=sys.exc_info(),
        )
    rendered = formatter.format(record)
    payload = json.loads(rendered)
    assert "exception" in payload
    assert payload["message"] == "payload"


# ---------------------------------------------------------------------------
# persistence/event_store.py residuals
# ---------------------------------------------------------------------------


def test_event_store_read_only_blocks_writes(tmp_path: Path) -> None:
    """Open in read-only mode and reject writes."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as store:
        store.append_event("agg-1", "ev", {"v": 1})
    with EventStore(db_path, read_only=True) as ro:
        with pytest.raises(PermissionError):
            ro.append_event("agg-1", "ev2", {"v": 2})
        with pytest.raises(PermissionError):
            ro.create_session("s", runtime="run", metadata={}, status="running")
        with pytest.raises(PermissionError):
            ro.end_session("s", status="completed")


def test_event_store_lock_retry_succeeds(tmp_path: Path) -> None:
    """The journal_mode retry path must eventually succeed under transient lock."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as _store:
        pass
    # Force a contended path: two simultaneous opens.
    threads = [threading.Thread(target=lambda: EventStore(db_path).close()) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    with EventStore(db_path) as store:
        assert store.integrity_check() == "ok"


def test_event_store_replay_hash_empty_aggregate(tmp_path: Path) -> None:
    """An aggregate with no events still hashes to a stable digest."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as store:
        digest_one = store.replay_hash("never-existed")
        digest_two = store.replay_hash("never-existed")
    assert digest_one == digest_two
    assert len(digest_one) == 64


def test_event_store_canonical_json_is_stable() -> None:
    """The canonical JSON serializer is sorted, separator-tight, and stable."""
    payload = {"b": 1, "a": [3, 2, 1]}
    rendered = _canonical_json(payload)
    assert rendered == '{"a":[3,2,1],"b":1}'


def test_event_store_iso8601_format_is_microsecond_z() -> None:
    """The ISO8601 helper must always end with 'Z' and contain microseconds."""
    stamp = iso8601_utc_now()
    assert stamp.endswith("Z")
    assert "." in stamp


# ---------------------------------------------------------------------------
# workflow/cancel.py residuals
# ---------------------------------------------------------------------------


def test_cancel_run_returns_not_found_when_session_absent(tmp_path: Path) -> None:
    """Cancelling an unknown run must return NOT_FOUND."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as _store:
        pass
    result = cancel_module.cancel_run(paths, "nope")
    assert result == cancel_module.CancelResult.NOT_FOUND


def test_cancel_run_returns_not_found_when_event_store_missing(tmp_path: Path) -> None:
    """Without an event store on disk, cancel returns NOT_FOUND."""
    paths = get_paths(tmp_path / "nonexistent")
    result = cancel_module.cancel_run(paths, "nope")
    assert result == cancel_module.CancelResult.NOT_FOUND


def test_cancel_run_returns_already_finished_for_completed_session(tmp_path: Path) -> None:
    """A session in a terminal state must short-circuit to ALREADY_FINISHED."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run-done", runtime="run", metadata={}, status="completed")
        store.end_session("run-done", status="completed")
    result = cancel_module.cancel_run(paths, "run-done")
    assert result == cancel_module.CancelResult.ALREADY_FINISHED


def test_cancel_run_handles_missing_pid_file(tmp_path: Path) -> None:
    """Running session without a pid file must record a clean cancellation."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run-nopid", runtime="run", metadata={}, status="running")
    result = cancel_module.cancel_run(paths, "run-nopid")
    assert result == cancel_module.CancelResult.CANCELLED
    with EventStore(paths.event_store) as store:
        events = [event.type for event in store.read_events("run-nopid")]
    assert "run.cancelled" in events


def test_cancel_run_handles_invalid_pid_file(tmp_path: Path) -> None:
    """A pid file containing garbage must trigger the invalid-pid branch."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run-bad-pid", runtime="run", metadata={}, status="running")

    # Fabricate the pid file in the place cancel expects it.
    pid_file = paths.state_dir / "runs" / "run-bad-pid" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("xxx\n", encoding="utf-8")

    result = cancel_module.cancel_run(paths, "run-bad-pid")
    assert result == cancel_module.CancelResult.CANCELLED
    assert not pid_file.exists()


def test_cancel_run_handles_stale_pid_file(tmp_path: Path) -> None:
    """A pid file pointing at a dead process must trigger the stale branch."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as store:
        store.create_session("run-stale-pid", runtime="run", metadata={}, status="running")
    pid_file = paths.state_dir / "runs" / "run-stale-pid" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("2999999\n", encoding="utf-8")
    result = cancel_module.cancel_run(paths, "run-stale-pid")
    assert result == cancel_module.CancelResult.CANCELLED
    assert not pid_file.exists()


def test_cancel_pid_helpers_accept_garbage_and_missing(tmp_path: Path) -> None:
    """The internal pid helpers must tolerate garbage and missing files."""
    bad = tmp_path / "bad"
    bad.write_text("nope\n", encoding="utf-8")
    assert cancel_module._read_pid(bad) is None
    assert cancel_module._read_pid(tmp_path / "missing") is None
    cancel_module._cleanup_pid_file(tmp_path / "missing")  # idempotent
    # _pid_is_live PermissionError branch
    with mock.patch.object(cancel_module.os, "kill", side_effect=PermissionError()):
        assert cancel_module._pid_is_live(123) is True


# ---------------------------------------------------------------------------
# workflow/evolve.py residuals
# ---------------------------------------------------------------------------


def test_evolve_calculate_similarity_matches_identical_payloads() -> None:
    """Identical candidates must produce similarity 1.0."""
    candidate = {"name": "x", "type": "ac", "payload": {"v": 1}}
    assert evolve_module.calculate_similarity(candidate, candidate) == 1.0


def test_evolve_detect_period_two_oscillation_detects_alternation() -> None:
    """A B A B alternation must detect period-two oscillation."""
    history = [
        {"name": "a", "type": "ac", "payload": {}},
        {"name": "b", "type": "ac", "payload": {}},
        {"name": "a", "type": "ac", "payload": {}},
        {"name": "b", "type": "ac", "payload": {}},
    ]
    assert evolve_module.detect_period_two_oscillation(history) is True


def test_evolve_detect_period_two_oscillation_short_history() -> None:
    """Histories shorter than 4 cannot oscillate."""
    history = [{"name": str(i), "type": "ac", "payload": {}} for i in range(3)]
    assert evolve_module.detect_period_two_oscillation(history) is False


def test_evolve_detect_repetitive_feedback_threshold() -> None:
    """Question overlap above the threshold must trip the repetitive flag."""
    prev = ["What should change?", "Which AC failed?"]
    curr = ["What should change?", "Which AC failed?"]
    assert evolve_module.detect_repetitive_feedback(prev, curr) is True


def test_evolve_detect_repetitive_feedback_disjoint_questions() -> None:
    """Wholly disjoint question sets do not trip the repetitive flag."""
    prev = ["a?"]
    curr = ["b?"]
    assert evolve_module.detect_repetitive_feedback(prev, curr) is False


def test_evolve_detect_repetitive_feedback_empty_returns_false() -> None:
    """Empty inputs must return False rather than dividing by zero."""
    assert evolve_module.detect_repetitive_feedback([], ["x?"]) is False
    assert evolve_module.detect_repetitive_feedback(["x?"], []) is False


# ---------------------------------------------------------------------------
# workflow/interview.py residuals
# ---------------------------------------------------------------------------


def test_interview_strip_quotes_handles_both_quote_types() -> None:
    """Interview's _strip_quotes accepts ' and \" wrappers and leaves bare values."""
    assert interview_module._strip_quotes("'hello'") == "hello"
    assert interview_module._strip_quotes('"hello"') == "hello"
    assert interview_module._strip_quotes("hello") == "hello"
    assert interview_module._strip_quotes('"') == '"'  # too short → unchanged


def test_interview_yaml_scalar_quotes_special_characters() -> None:
    """Special characters and embedded newlines force quoted output."""
    assert interview_module._yaml_scalar("plain") == "plain"
    assert interview_module._yaml_scalar("") == '""'
    assert interview_module._yaml_scalar("with: colon").startswith('"')


def test_interview_yaml_list_handles_empty_and_multi() -> None:
    """Empty list → '  []'; non-empty list → one '  - ...' entry per item."""
    assert interview_module._yaml_list([]) == ["  []"]
    rendered = interview_module._yaml_list(["a", "b"])
    assert rendered == ["  - a", "  - b"]


def test_interview_parse_simple_yaml_rejects_orphan_list_item() -> None:
    """A '- value' line without a preceding key must raise ValueError."""
    with pytest.raises(ValueError, match="list item"):
        interview_module._parse_simple_yaml("- orphan\n")


def test_interview_parse_simple_yaml_rejects_unsupported_line() -> None:
    """A line with no ':' must raise ValueError."""
    with pytest.raises(ValueError, match="unsupported"):
        interview_module._parse_simple_yaml("not_a_pair\n")


def test_interview_parse_simple_yaml_rejects_mixed_scalar_list() -> None:
    """A key cannot be both scalar and list — that must raise ValueError."""
    with pytest.raises(ValueError):
        interview_module._parse_simple_yaml("key: scalar\n- 1\n")


def test_interview_parse_mapping_rejects_top_level_array() -> None:
    """fixture JSON must be an object, never a top-level array."""
    with pytest.raises(ValueError):
        interview_module._parse_mapping("[1, 2]")


def test_interview_ambiguity_helpers() -> None:
    """The internal ambiguity heuristics return 0 or 1 for known/unknown markers."""
    assert interview_module._ambiguity_for_scalar("tbd") == 1.0
    assert interview_module._ambiguity_for_scalar("done") == 0.0
    assert interview_module._ambiguity_for_list([]) == 1.0
    assert interview_module._ambiguity_for_list(["tbd", "done"]) == 0.5
    assert interview_module._ambiguity_for_list(["done"]) == 0.0


# ---------------------------------------------------------------------------
# workflow/lineage.py residuals
# ---------------------------------------------------------------------------


def test_lineage_decode_metadata_handles_invalid_json() -> None:
    """Malformed metadata must decode to an empty dict."""
    assert lineage_module._decode_metadata("not-json") == {}


def test_lineage_decode_metadata_handles_non_object() -> None:
    """Top-level JSON arrays must decode to an empty dict."""
    assert lineage_module._decode_metadata("[1,2]") == {}


def test_lineage_phase_for_session_uses_explicit_phase_metadata() -> None:
    """Explicit phase metadata wins over the runtime → phase fallback."""
    assert lineage_module._phase_for_session("run", {"phase": "custom"}) == "custom"
    assert lineage_module._phase_for_session("evolution", {"double_diamond_phase": "x"}) == "x"
    # Fallback table is exercised by the existing tests; here we cover an unknown runtime.
    assert lineage_module._phase_for_session("unknown", {}) == "unknown"


def test_lineage_parent_id_returns_none_for_invalid_metadata() -> None:
    """Non-dict metadata must return None for parent_id."""
    assert lineage_module._parent_id({"metadata": "wrong-type"}) is None
    assert lineage_module._parent_id({"metadata": {}}) is None


def test_lineage_replay_hash_for_aggregate_returns_none_for_unknown(tmp_path: Path) -> None:
    """Asking for a missing aggregate must return None, not crash."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as _store:
        pass
    assert lineage_module.replay_hash_for_aggregate(db_path, "ghost") is None


def test_lineage_replay_hash_for_aggregate_returns_hash_for_existing(tmp_path: Path) -> None:
    """A real aggregate with events must surface a SHA-256 hash."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as store:
        store.append_event("agg", "ev", {"v": 1})
    digest = lineage_module.replay_hash_for_aggregate(db_path, "agg")
    assert digest is not None
    assert len(digest) == 64


# ---------------------------------------------------------------------------
# workflow/qa.py residuals
# ---------------------------------------------------------------------------


def test_qa_evaluate_run_returns_none_for_missing_session(tmp_path: Path) -> None:
    """Asking for an unknown session must return None."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as _store:
        pass
    assert qa_module.evaluate_run_qa(db_path, "ghost") is None


def test_qa_evaluate_run_marks_failures_for_failed_run(tmp_path: Path) -> None:
    """A failed run must show the no_failure_events check failing."""
    db_path = tmp_path / "events.db"
    with EventStore(db_path) as store:
        store.create_session("run-1", runtime="run", metadata={}, status="failed")
        store.append_event("run-1", "run.started", {})
        store.append_event("run-1", "run.failed", {"why": "x"})
        store.end_session("run-1", status="failed")
    report = qa_module.evaluate_run_qa(db_path, "run-1")
    assert report is not None
    assert report.summary.failed > 0
    no_failure = next(r for r in report.results if r.id == "no_failure_events")
    assert no_failure.passed is False


def test_qa_decode_json_object_handles_invalid_json() -> None:
    """Malformed JSON must decode to {}."""
    assert qa_module._decode_json_object("not json") == {}


def test_qa_decode_json_object_rejects_non_objects() -> None:
    """A JSON array at top level must decode to {}."""
    assert qa_module._decode_json_object("[1, 2]") == {}


# ---------------------------------------------------------------------------
# workflow/run.py residuals
# ---------------------------------------------------------------------------


def test_run_pid_is_live_permission_error_is_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """run._pid_is_live must treat PermissionError as 'still alive'."""
    monkeypatch.setattr(run_module.os, "kill", mock.Mock(side_effect=PermissionError()))
    assert run_module._pid_is_live(987_654) is True


def test_run_mark_stale_run_skips_when_pid_file_missing(tmp_path: Path) -> None:
    """No pid file → no DB write."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as _store:
        pass
    run_module.mark_stale_run_if_needed(paths, "absent")  # no exception


def test_run_mark_stale_run_handles_invalid_pid(tmp_path: Path) -> None:
    """Garbage pid file must mark the run crashed."""
    paths = get_paths(tmp_path)
    paths.event_store.parent.mkdir(parents=True, exist_ok=True)
    with EventStore(paths.event_store) as _store:
        pass
    pid_file = paths.state_dir / "runs" / "rcrash" / "pid"
    pid_file.parent.mkdir(parents=True)
    pid_file.write_text("xxx\n", encoding="utf-8")
    run_module.mark_stale_run_if_needed(paths, "rcrash")
    with EventStore(paths.event_store) as store:
        events = store.read_events("rcrash")
    assert any(event.type == "run.crashed" for event in events)


# ---------------------------------------------------------------------------
# workflow/seed.py residuals
# ---------------------------------------------------------------------------


def test_seed_load_seed_spec_missing_file_raises(tmp_path: Path) -> None:
    """Missing files must raise SeedSpecValidationError, not OSError."""
    with pytest.raises(seed_module.SeedSpecValidationError):
        seed_module.load_seed_spec(tmp_path / "missing.yaml")


def test_seed_parse_mapping_rejects_empty_input() -> None:
    """Empty inputs must raise ValueError ('spec file is empty')."""
    with pytest.raises(ValueError, match="empty"):
        seed_module._parse_mapping("")


def test_seed_parse_mapping_rejects_non_object_json() -> None:
    """A top-level JSON array must raise ValueError."""
    with pytest.raises(ValueError):
        seed_module._parse_mapping("[1, 2]")


def test_seed_parse_simple_yaml_rejects_orphan_list_item() -> None:
    """A '- value' line without a preceding key must raise ValueError."""
    with pytest.raises(ValueError):
        seed_module._parse_simple_yaml("- orphan\n")


def test_seed_parse_simple_yaml_rejects_unsupported_line() -> None:
    """A line lacking ':' must raise ValueError."""
    with pytest.raises(ValueError):
        seed_module._parse_simple_yaml("not_a_pair\n")


def test_seed_parse_simple_yaml_rejects_mixed_scalar_list() -> None:
    """A key cannot be both scalar and list."""
    with pytest.raises(ValueError):
        seed_module._parse_simple_yaml("key: x\n- 1\n")


def test_seed_validate_seed_spec_collects_all_errors() -> None:
    """Validation must aggregate all errors into one message."""
    with pytest.raises(seed_module.SeedSpecValidationError) as exc:
        seed_module.validate_seed_spec({})
    msg = str(exc.value)
    assert "goal is required" in msg
    assert "constraints" in msg
    assert "success_criteria" in msg


def test_seed_validate_seed_spec_brownfield_requires_context() -> None:
    """A brownfield spec missing context must raise."""
    with pytest.raises(seed_module.SeedSpecValidationError, match="context"):
        seed_module.validate_seed_spec(
            {
                "project_type": "brownfield",
                "goal": "x",
                "constraints": ["c"],
                "success_criteria": ["s"],
            }
        )


def test_seed_validate_seed_spec_rejects_unknown_project_type() -> None:
    """An unsupported project_type must surface in the error message."""
    with pytest.raises(seed_module.SeedSpecValidationError, match="project_type"):
        seed_module.validate_seed_spec(
            {
                "project_type": "frankenstein",
                "goal": "x",
                "constraints": ["c"],
                "success_criteria": ["s"],
            }
        )


def test_seed_strip_quotes_short_input_unchanged() -> None:
    """Strings shorter than 2 chars are returned unchanged."""
    assert seed_module._strip_quotes("'") == "'"
    assert seed_module._strip_quotes("") == ""
