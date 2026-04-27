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


def test_interview_help_documents_non_interactive_input_and_output(tmp_path: Path) -> None:
    result = run_mobius("interview", "--help", mobius_home=tmp_path / "home")

    assert result.returncode == 0
    assert "--non-interactive" in result.stdout
    assert "--input" in result.stdout
    assert "--output" in result.stdout
    assert result.stderr == ""


def test_interview_non_interactive_fixture_writes_spec_and_events(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    fixture = tmp_path / "fixture.yaml"
    spec = tmp_path / "spec.yaml"
    fixture.write_text(
        """
project_type: brownfield
goal: Replace MCP orchestration with a one-shot CLI.
constraints:
  - Do not add MCP dependencies
  - Persist interview answers in SQLite
success:
  - Spec file exists
  - Ambiguity score is at or below the gate
context: Existing Mobius code already has Typer and an event store.
""".strip(),
        encoding="utf-8",
    )

    result = run_mobius(
        "--json",
        "interview",
        "--non-interactive",
        "--input",
        str(fixture),
        "--output",
        str(spec),
        mobius_home=mobius_home,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["session_id"].startswith("interview_")
    assert payload["ambiguity_score"] == 0.0
    assert payload["passed_gate"] is True
    assert payload["output"] == str(spec)
    assert result.stderr == ""

    spec_text = spec.read_text(encoding="utf-8")
    assert f"session_id: {payload['session_id']}" in spec_text
    assert "project_type: brownfield" in spec_text
    assert "ambiguity_score: 0.0" in spec_text
    assert "Replace MCP orchestration with a one-shot CLI." in spec_text

    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        rows = connection.execute(
            """
            SELECT type, json_extract(payload, '$.category')
            FROM events
            WHERE aggregate_id = ?
            ORDER BY sequence
            """,
            (payload["session_id"],),
        ).fetchall()
    finally:
        connection.close()

    assert [row[0] for row in rows] == [
        "interview.started",
        "interview.question_answered",
        "interview.question_answered",
        "interview.question_answered",
        "interview.question_answered",
        "interview.completed",
    ]
    assert [row[1] for row in rows[1:5]] == ["goal", "constraints", "success", "context"]


def test_interview_rejects_ambiguous_fixture_without_writing_spec(tmp_path: Path) -> None:
    fixture = tmp_path / "ambiguous.yaml"
    spec = tmp_path / "spec.yaml"
    fixture.write_text(
        """
project_type: brownfield
goal: TBD
constraints:
success:
context: unknown
""".strip(),
        encoding="utf-8",
    )

    result = run_mobius(
        "interview",
        "--non-interactive",
        "--input",
        str(fixture),
        "--output",
        str(spec),
        mobius_home=tmp_path / "home",
    )

    assert result.returncode == 3
    assert "ambiguity score" in result.stderr
    assert not spec.exists()
