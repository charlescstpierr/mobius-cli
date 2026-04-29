"""Phase 2 scribe handoff from v3a fixtures to the v2 CLI writer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class SeedHandoffResult:
    """Result of invoking the v2 interview CLI as the Phase 2 writer."""

    spec_path: Path
    backup_path: Path | None
    command: tuple[str, ...]
    stdout: str
    stderr: str


def backup_spec_yaml(
    workspace: Path,
    *,
    now: Callable[[], datetime] | None = None,
) -> Path | None:
    """Move an existing ``spec.yaml`` aside with a unique UTC timestamp suffix."""
    spec_path = workspace / "spec.yaml"
    if not spec_path.exists():
        return None

    current = (now or _utc_now)()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC).replace(microsecond=0)
    while True:
        backup_path = workspace / f"spec.yaml.pre-build.{_format_utc_timestamp(current)}.bak"
        if not backup_path.exists():
            spec_path.replace(backup_path)
            return backup_path
        current += timedelta(seconds=1)


def run_seed_handoff(*, fixture_path: Path, workspace: Path) -> SeedHandoffResult:
    """Run v2's non-interactive interview command against a v3a fixture."""
    import subprocess

    resolved_workspace = workspace.expanduser().resolve()
    resolved_fixture = fixture_path.expanduser().resolve()
    backup_path = backup_spec_yaml(resolved_workspace)
    command = (
        "mobius",
        "interview",
        "--non-interactive",
        "--input",
        str(resolved_fixture),
    )
    completed = subprocess.run(
        list(command),
        cwd=resolved_workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    return SeedHandoffResult(
        spec_path=resolved_workspace / "spec.yaml",
        backup_path=backup_path,
        command=command,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _format_utc_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H-%M-%SZ")
