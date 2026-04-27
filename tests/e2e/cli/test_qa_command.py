import json
import os
import subprocess
from pathlib import Path

from mobius.persistence.event_store import EventStore

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_mobius(*args: str, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def write_valid_spec(path: Path) -> None:
    path.write_text(
        """
project_type: greenfield
goal: Produce a QA-verifiable run.
constraints:
  - Stay deterministic
success_criteria:
  - QA exits zero for completed runs
""".strip(),
        encoding="utf-8",
    )


def create_failed_run(mobius_home: Path, run_id: str, spec_path: Path) -> None:
    with EventStore(mobius_home / "events.db") as store:
        store.create_session(
            run_id,
            runtime="run",
            metadata={"spec_path": str(spec_path), "project_type": "greenfield"},
            status="running",
        )
        store.append_event(run_id, "run.started", {"goal": "Produce a QA-verifiable run."})
        store.append_event(run_id, "run.failed", {"reason": "known bad fixture"})
        store.end_session(run_id, status="failed")


def test_qa_offline_json_passes_completed_run(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0
    run_id = next((mobius_home / "runs").glob("run_*/metadata.json")).parent.name

    qa_result = run_mobius("qa", run_id, "--offline", "--json", mobius_home=mobius_home)

    assert qa_result.returncode == 0
    assert qa_result.stderr == ""
    payload = json.loads(qa_result.stdout)
    assert payload["run_id"] == run_id
    assert payload["mode"] == "offline"
    assert payload["summary"]["total"] == len(payload["results"])
    assert payload["summary"]["failed"] == 0
    assert payload["results"]


def test_qa_offline_uses_event_store_when_spec_file_deleted(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0
    run_id = next((mobius_home / "runs").glob("run_*/metadata.json")).parent.name
    spec.unlink()

    qa_result = run_mobius("qa", run_id, "--offline", "--json", mobius_home=mobius_home)

    assert qa_result.returncode == 0
    assert qa_result.stderr == ""
    payload = json.loads(qa_result.stdout)
    assert payload["summary"]["failed"] == 0
    spec_result = next(
        result for result in payload["results"] if result["id"] == "spec_has_success_criteria"
    )
    assert spec_result["passed"] is True
    assert spec_result["detail"] == "success_criteria=1"


def test_qa_json_fails_known_bad_run(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    create_failed_run(mobius_home, "run_bad", spec)

    qa_result = run_mobius("qa", "run_bad", "--json", mobius_home=mobius_home)

    assert qa_result.returncode == 1
    assert qa_result.stderr == ""
    payload = json.loads(qa_result.stdout)
    assert payload["summary"]["total"] == len(payload["results"])
    assert payload["summary"]["failed"] > 0
    assert any(result["id"] == "no_failure_events" for result in payload["results"])


def test_qa_unknown_run_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("qa", "run_missing", "--offline", mobius_home=tmp_path / "home")

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()
