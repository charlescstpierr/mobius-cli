from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mobius.v3a.interview.scribe import backup_spec_yaml, run_seed_handoff


def test_backup_spec_yaml_moves_existing_spec_to_timestamped_bak_without_touching_baks(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("goal: old\n", encoding="utf-8")
    existing_backup = tmp_path / "spec.yaml.pre-build.2026-04-28T14-32-09Z.bak"
    existing_backup.write_text("goal: older\n", encoding="utf-8")

    backup = backup_spec_yaml(
        tmp_path,
        now=lambda: datetime(2026, 4, 29, 12, 34, 56, tzinfo=UTC),
    )

    assert backup == tmp_path / "spec.yaml.pre-build.2026-04-29T12-34-56Z.bak"
    assert backup.read_text(encoding="utf-8") == "goal: old\n"
    assert not spec.exists()
    assert existing_backup.read_text(encoding="utf-8") == "goal: older\n"


def test_backup_spec_yaml_never_clobbers_successive_backups(tmp_path: Path) -> None:
    first = tmp_path / "spec.yaml.pre-build.2026-04-29T12-34-56Z.bak"
    first.write_text("goal: first\n", encoding="utf-8")
    spec = tmp_path / "spec.yaml"
    spec.write_text("goal: second\n", encoding="utf-8")

    backup = backup_spec_yaml(
        tmp_path,
        now=lambda: datetime(2026, 4, 29, 12, 34, 56, tzinfo=UTC),
    )

    assert backup == tmp_path / "spec.yaml.pre-build.2026-04-29T12-34-57Z.bak"
    assert first.read_text(encoding="utf-8") == "goal: first\n"
    assert backup.read_text(encoding="utf-8") == "goal: second\n"


def test_backup_spec_yaml_returns_none_when_no_spec_exists(tmp_path: Path) -> None:
    assert backup_spec_yaml(tmp_path) is None


def test_backup_spec_yaml_accepts_naive_datetime_and_default_clock(tmp_path: Path) -> None:
    spec = tmp_path / "spec.yaml"
    spec.write_text("goal: naive\n", encoding="utf-8")

    backup = backup_spec_yaml(
        tmp_path,
        now=lambda: datetime(2026, 4, 29, 12, 34, 56),
    )

    assert backup == tmp_path / "spec.yaml.pre-build.2026-04-29T12-34-56Z.bak"
    assert backup.read_text(encoding="utf-8") == "goal: naive\n"

    spec.write_text("goal: default clock\n", encoding="utf-8")
    second_backup = backup_spec_yaml(tmp_path)

    assert second_backup is not None
    assert second_backup.name.startswith("spec.yaml.pre-build.")
    assert second_backup.name.endswith("Z.bak")
    assert second_backup.read_text(encoding="utf-8") == "goal: default clock\n"


def test_run_seed_handoff_invokes_v2_interview_cli_lazily(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    fixture = tmp_path / ".mobius" / "build" / "run-1" / "fixture.yaml"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("goal: Build a deterministic CLI\n", encoding="utf-8")
    calls: list[dict[str, Any]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        (tmp_path / "spec.yaml").write_text("goal: new\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_seed_handoff(fixture_path=fixture, workspace=tmp_path)

    assert calls == [
        {
            "command": [
                "mobius",
                "interview",
                "--non-interactive",
                "--input",
                str(fixture),
            ],
            "cwd": tmp_path,
            "check": True,
            "capture_output": True,
            "text": True,
        }
    ]
    assert result.spec_path == tmp_path / "spec.yaml"
    assert result.backup_path is None
    assert result.stdout == "ok\n"
