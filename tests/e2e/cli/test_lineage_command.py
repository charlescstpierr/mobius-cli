import json
import os
import re
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
project_type: greenfield
goal: Exercise lineage output.
constraints:
  - Preserve ancestry
success_criteria:
  - Lineage includes descendants
""".strip(),
        encoding="utf-8",
    )


def create_completed_run_and_evolution(tmp_path: Path, mobius_home: Path) -> tuple[str, str]:
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        run_id = str(
            connection.execute("SELECT session_id FROM sessions WHERE runtime = 'run'").fetchone()[
                0
            ]
        )
    finally:
        connection.close()

    evolve_result = run_mobius(
        "evolve",
        "--foreground",
        "--from",
        run_id,
        "--generations",
        "1",
        mobius_home=mobius_home,
    )
    assert evolve_result.returncode == 0
    connection = sqlite3.connect(mobius_home / "events.db")
    try:
        evolution_id = str(
            connection.execute(
                "SELECT session_id FROM sessions WHERE runtime = 'evolution'"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return run_id, evolution_id


def test_lineage_help_documents_json_and_hash_flags(tmp_path: Path) -> None:
    result = run_mobius("lineage", "--help", mobius_home=tmp_path / "home")

    assert result.returncode == 0
    assert "--json" in result.stdout
    assert "--hash" in result.stdout


def test_lineage_prints_markdown_tree(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id, evolution_id = create_completed_run_and_evolution(tmp_path, mobius_home)

    result = run_mobius("lineage", run_id, mobius_home=mobius_home)

    assert result.returncode == 0
    assert result.stderr == ""
    assert f"# Lineage {run_id}" in result.stdout
    assert f"- Run `{run_id}`" in result.stdout
    assert f"- Evolution `{evolution_id}`" in result.stdout


def test_lineage_json_returns_ancestors_and_descendants(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id, evolution_id = create_completed_run_and_evolution(tmp_path, mobius_home)

    result = run_mobius("lineage", evolution_id, "--json", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["aggregate_id"] == evolution_id
    assert [node["aggregate_id"] for node in payload["ancestors"]] == [run_id]
    assert payload["descendants"] == []


def test_lineage_unknown_id_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("lineage", "missing", mobius_home=tmp_path / "home")

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()


def test_lineage_hash_prints_deterministic_replay_sha256(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    run_id, _evolution_id = create_completed_run_and_evolution(tmp_path, mobius_home)

    first = run_mobius("lineage", run_id, "--hash", mobius_home=mobius_home)
    second = run_mobius("lineage", "--aggregate", run_id, "--hash", mobius_home=mobius_home)

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout
    assert re.fullmatch(r"[0-9a-f]{64}\n", first.stdout)
