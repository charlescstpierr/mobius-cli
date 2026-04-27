import json
import os
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


def write_valid_spec(path: Path, *, success_count: int = 2) -> None:
    success_lines = "\n".join(f"  - AC item {index}" for index in range(success_count))
    path.write_text(
        f"""
project_type: greenfield
goal: Render the AC tree.
constraints:
  - Use markdown by default
  - Emit structured JSON on request
success_criteria:
{success_lines}
""".strip(),
        encoding="utf-8",
    )


def test_ac_tree_outputs_markdown_and_json(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0

    run_id = next((mobius_home / "runs").glob("run_*/metadata.json")).parent.name

    markdown = run_mobius("ac-tree", run_id, mobius_home=mobius_home)
    assert markdown.returncode == 0
    assert f"# AC Tree {run_id}" in markdown.stdout
    assert "Goal: Render the AC tree." in markdown.stdout
    assert "AC item 1" in markdown.stdout
    assert markdown.stderr == ""

    json_result = run_mobius("ac-tree", run_id, "--json", mobius_home=mobius_home)
    assert json_result.returncode == 0
    payload = json.loads(json_result.stdout)
    assert payload["run_id"] == run_id
    assert payload["state"] == "completed"
    assert payload["nodes"]
    assert payload["edges"]
    assert json_result.stderr == ""


def test_ac_tree_cursor_filters_event_delta_nodes(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0
    run_id = next((mobius_home / "runs").glob("run_*/metadata.json")).parent.name

    result = run_mobius("ac-tree", run_id, "--json", "--cursor", "2", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    event_sequences = [node["sequence"] for node in payload["nodes"] if node["type"] == "event"]
    assert event_sequences == [3, 4, 5, 6]


def test_ac_tree_truncates_large_trees(tmp_path: Path) -> None:
    mobius_home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    write_valid_spec(spec, success_count=80)
    run_result = run_mobius("run", "--foreground", "--spec", str(spec), mobius_home=mobius_home)
    assert run_result.returncode == 0
    run_id = next((mobius_home / "runs").glob("run_*/metadata.json")).parent.name

    result = run_mobius("ac-tree", run_id, "--json", "--max-nodes", "12", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["truncated"] is True
    assert payload["omitted_nodes"] > 0
    assert len(payload["nodes"]) == 12
    assert payload["nodes"][-1]["type"] == "truncation"


def test_ac_tree_unknown_run_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("ac-tree", "run_missing", mobius_home=tmp_path / "home")

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr.lower()
