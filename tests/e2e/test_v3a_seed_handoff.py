from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from mobius.workflow.seed import assign_bronze_grade, load_seed_spec

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MOBIUS_BIN = PROJECT_ROOT / ".venv" / "bin" / "mobius"


def run_mobius(*args: str, cwd: Path, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(MOBIUS_BIN), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "MOBIUS_HOME": str(mobius_home),
            "NO_COLOR": "1",
            "PATH": f"{MOBIUS_BIN.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        },
    )


def test_build_phase_two_seeds_spec_yaml_that_passes_bronze(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = run_mobius(
        "build",
        "tiny TODO CLI",
        "--agent",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 0, result.stderr
    payload = _payload_for_phase(result.stdout, "seed")
    assert payload["phase_done"] == "seed"
    assert payload["next_phase"] == "maturity"

    spec_path = workspace / "spec.yaml"
    assert Path(payload["spec_yaml"]) == spec_path
    assert spec_path.exists()
    grade = assign_bronze_grade(load_seed_spec(spec_path))
    assert grade.grade == "bronze"
    assert grade.criteria_met == grade.criteria_total


def test_build_phase_two_is_idempotent_for_same_input_except_generated_ids(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = run_mobius(
        "build",
        "tiny TODO CLI",
        "--agent",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )
    assert first.returncode == 0, first.stderr
    first_spec = (workspace / "spec.yaml").read_text(encoding="utf-8")

    second = run_mobius(
        "build",
        "tiny TODO CLI",
        "--agent",
        "--auto-top-up",
        cwd=workspace,
        mobius_home=tmp_path / "home",
    )
    assert second.returncode == 0, second.stderr
    second_spec = (workspace / "spec.yaml").read_text(encoding="utf-8")

    backups = sorted(workspace.glob("spec.yaml.pre-build.*.bak"))
    assert len(backups) == 1
    assert _normalize_generated_id(backups[0].read_text(encoding="utf-8")) == (
        _normalize_generated_id(first_spec)
    )
    assert _normalize_generated_id(first_spec) == _normalize_generated_id(second_spec)


def _normalize_generated_id(spec_text: str) -> str:
    return "\n".join(
        "session_id: <generated>" if line.startswith("session_id:") else line
        for line in spec_text.splitlines()
    )


def _payload_for_phase(stdout: str, phase: str) -> dict[str, object]:
    for line in stdout.splitlines():
        payload = json.loads(line)
        if payload.get("phase_done") == phase:
            return payload
    raise AssertionError(f"missing phase payload for {phase!r}: {stdout}")
