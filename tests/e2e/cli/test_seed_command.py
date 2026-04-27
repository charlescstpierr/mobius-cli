import json
import os
import sqlite3
import subprocess
from pathlib import Path

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
session_id: interview_source
project_type: greenfield
ambiguity_score: 0.0
ambiguity_gate: 0.2
ambiguity_components:
  goal: 0.0
  constraints: 0.0
  success: 0.0
goal: Build a fast CLI workflow.
constraints:
  - Never use MCP
  - Persist all workflow state
success_criteria:
  - Seed command emits a session id
  - Seed events are queryable in SQLite
""".strip(),
        encoding="utf-8",
    )


def test_seed_help_documents_json_and_spec_argument(tmp_path: Path) -> None:
    result = run_mobius("seed", "--help", mobius_home=tmp_path / "home")

    assert result.returncode == 0
    assert "spec_or_session_id" in result.stdout
    assert "--json" in result.stdout
    assert result.stderr == ""


def test_seed_spec_emits_session_id_json_and_persists_events(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)

    result = run_mobius("seed", str(spec), "--json", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].startswith("seed_")
    assert payload["source"] == str(spec)
    assert payload["event_count"] >= 3
    assert result.stderr == ""

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        rows = connection.execute(
            """
            SELECT type, json_extract(payload, '$.goal')
            FROM events
            WHERE aggregate_id = ?
            ORDER BY sequence
            """,
            (payload["session_id"],),
        ).fetchall()
        session_row = connection.execute(
            "SELECT runtime, status FROM sessions WHERE session_id = ?",
            (payload["session_id"],),
        ).fetchone()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [
        "seed.started",
        "seed.validated",
        "seed.completed",
    ]
    assert rows[2][1] == "Build a fast CLI workflow."
    assert session_row == ("seed", "completed")


def test_seed_rejects_invalid_spec_with_clear_stderr(tmp_path: Path) -> None:
    spec = tmp_path / "invalid.yaml"
    spec.write_text(
        "project_type: invalid\ngoal:\nconstraints:\nsuccess_criteria:\n",
        encoding="utf-8",
    )

    result = run_mobius("seed", str(spec), mobius_home=tmp_path / "home")

    assert result.returncode == 3
    assert "seed spec validation failed" in result.stderr
    assert "project_type must be either 'greenfield' or 'brownfield'" in result.stderr
    assert "goal is required" in result.stderr
    assert result.stdout == ""


def test_seed_can_use_interview_session_id_as_source(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    fixture = tmp_path / "fixture.yaml"
    spec = tmp_path / "spec.yaml"
    fixture.write_text(
        """
project_type: greenfield
goal: Produce a reusable seed from interview output.
constraints:
  - Keep the seed deterministic
success:
  - Seed session is created from interview id
""".strip(),
        encoding="utf-8",
    )
    interview = run_mobius(
        "--json",
        "interview",
        "--non-interactive",
        "--input",
        str(fixture),
        "--output",
        str(spec),
        mobius_home=mobius_home,
    )
    assert interview.returncode == 0
    interview_id = json.loads(interview.stdout)["session_id"]

    result = run_mobius("--json", "seed", interview_id, mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].startswith("seed_")
    assert payload["source"] == interview_id
