"""Environment diagnostics for the Mobius CLI."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mobius.config import get_paths
from mobius.persistence.event_store import EventStore
from mobius.workflow.ids import readable_session_id

CheckStatus = Literal["ok", "warn", "fail"]

_EXPECTED_HOME_MODE = 0o700
_EXPECTED_DB_MODE = 0o600
_SKIPPED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


@dataclass(frozen=True)
class DoctorCheck:
    """A single doctor diagnostic result."""

    check_name: str
    status: CheckStatus
    details: str

    def to_payload(self) -> dict[str, str]:
        """Return the JSON/event payload form of this check."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "details": self.details,
        }


def run_doctor(*, cwd: Path, mobius_home: Path) -> list[DoctorCheck]:
    """Run all doctor checks and emit one event for each result."""
    paths = get_paths(mobius_home)
    checks = [
        _check_python_env(),
        _check_shebangs(cwd),
        _check_mobius_home(paths.home),
        _check_sqlite_health(paths.event_store),
        _check_spec(cwd),
        _check_permissions(paths.event_store),
    ]
    _emit_check_events(paths.event_store, checks)
    return checks


def _check_python_env() -> DoctorCheck:
    executable = Path(sys.executable)
    if not executable.exists():
        return DoctorCheck("python_env", "fail", f"sys.executable does not exist: {executable}")
    if not os.access(executable, os.X_OK):
        return DoctorCheck("python_env", "fail", f"sys.executable is not executable: {executable}")

    import subprocess

    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DoctorCheck("python_env", "fail", f"uv is not runnable: {exc}")
    if result.returncode != 0:
        return DoctorCheck(
            "python_env",
            "fail",
            f"uv --version exited {result.returncode}: {result.stderr.strip()}",
        )
    return DoctorCheck("python_env", "ok", f"python={executable}; {result.stdout.strip()}")


def _check_shebangs(cwd: Path) -> DoctorCheck:
    stale = _find_stale_shebangs(cwd)
    if stale:
        sample = ", ".join(f"{path}: {target}" for path, target in stale[:5])
        extra = "" if len(stale) <= 5 else f" (+{len(stale) - 5} more)"
        return DoctorCheck("shebang_check", "fail", f"stale shebangs: {sample}{extra}")
    return DoctorCheck("shebang_check", "ok", f"no stale shebangs under {cwd}")


def _find_stale_shebangs(root: Path) -> list[tuple[str, str]]:
    stale: list[tuple[str, str]] = []
    for path in _iter_candidate_files(root):
        try:
            with path.open("rb") as file:
                first_line = file.readline(512)
        except OSError:
            continue
        if not first_line.startswith(b"#!"):
            continue
        shebang = first_line[2:].decode("utf-8", errors="replace").strip()
        target = shebang.split(maxsplit=1)[0]
        if not target.startswith("/"):
            continue
        target_path = Path(target)
        if (
            _is_project_venv_script(path)
            and target_path.resolve() != Path(sys.executable).resolve()
        ):
            try:
                display_path = str(path.relative_to(root))
            except ValueError:
                display_path = str(path)
            stale.append((display_path, target))
            continue
        if target_path.exists():
            continue
        try:
            display_path = str(path.relative_to(root))
        except ValueError:
            display_path = str(path)
        stale.append((display_path, target))
    return stale


def _iter_candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name in _SKIPPED_DIRS:
                    continue
                if (
                    ".venv" in entry.parts
                    and entry.name != "bin"
                    and entry.name != ".venv"
                ):
                    continue
                stack.append(entry)
            elif entry.is_file():
                if ".venv" in entry.parts and "bin" not in entry.parts:
                    continue
                candidates.append(entry)
    return candidates


def _is_project_venv_script(path: Path) -> bool:
    return ".venv" in path.parts and "bin" in path.parts


def _check_mobius_home(home: Path) -> DoctorCheck:
    if not home.exists():
        return DoctorCheck("mobius_home", "fail", f"MOBIUS_HOME does not exist: {home}")
    if not home.is_dir():
        return DoctorCheck("mobius_home", "fail", f"MOBIUS_HOME is not a directory: {home}")
    mode = _mode(home)
    if mode != _EXPECTED_HOME_MODE:
        return DoctorCheck(
            "mobius_home",
            "warn",
            f"MOBIUS_HOME mode is {_format_mode(mode)}, expected 0700: {home}",
        )
    return DoctorCheck("mobius_home", "ok", f"MOBIUS_HOME exists with mode 0700: {home}")


def _check_sqlite_health(event_store: Path) -> DoctorCheck:
    if not event_store.exists():
        return DoctorCheck("sqlite_health", "warn", f"event store does not exist: {event_store}")

    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{event_store}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return DoctorCheck("sqlite_health", "fail", f"cannot open event store: {exc}")
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        integrity_text = str(integrity[0]) if integrity is not None else ""
        if integrity_text != "ok":
            return DoctorCheck("sqlite_health", "fail", f"integrity_check={integrity_text}")
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    except sqlite3.Error as exc:
        return DoctorCheck("sqlite_health", "fail", f"sqlite health check failed: {exc}")
    finally:
        connection.close()

    required = {"events", "sessions", "aggregates", "schema_migrations"}
    missing = sorted(required - tables)
    if missing:
        return DoctorCheck("sqlite_health", "fail", f"missing tables: {', '.join(missing)}")
    return DoctorCheck("sqlite_health", "ok", "integrity_check=ok; schema present")


def _check_spec(cwd: Path) -> DoctorCheck:
    spec_path = cwd / "spec.yaml"
    if not spec_path.exists():
        return DoctorCheck("spec_valid", "ok", f"no spec.yaml in {cwd}")
    try:
        from mobius.workflow.seed import load_seed_spec

        load_seed_spec(spec_path)
    except Exception as exc:
        return DoctorCheck("spec_valid", "fail", f"spec.yaml is invalid: {exc}")
    return DoctorCheck("spec_valid", "ok", f"spec.yaml is valid: {spec_path}")


def _check_permissions(event_store: Path) -> DoctorCheck:
    if not event_store.exists():
        return DoctorCheck("permissions", "warn", f"event store does not exist: {event_store}")
    mode = _mode(event_store)
    if mode != _EXPECTED_DB_MODE:
        return DoctorCheck(
            "permissions",
            "warn",
            f"events.db mode is {_format_mode(mode)}, expected 0600: {event_store}",
        )
    return DoctorCheck("permissions", "ok", f"events.db exists with mode 0600: {event_store}")


def _emit_check_events(event_store: Path, checks: list[DoctorCheck]) -> None:
    aggregate_id = readable_session_id("doctor", "environment diagnostics")
    try:
        with EventStore(event_store) as store:
            for check in checks:
                store.append_event(
                    aggregate_id,
                    "doctor.check_completed",
                    check.to_payload(),
                )
    except Exception:
        return


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _format_mode(mode: int) -> str:
    return f"{mode:04o}"
