import json
import sys
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from mobius.cli.main import app
from mobius.persistence.event_store import EventStore


def test_full_pass_yields_gold(tmp_path: Path, monkeypatch: Any) -> None:
    home = tmp_path / "home"
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"""
project_type: greenfield
goal: Demonstrate an end-to-end Gold grade.
constraints:
  - Keep all checks local.
success_criteria:
  - C1 - First proof passes.
  - C2 - Second proof passes.
non_goals:
  - Do not use network services.
owner: qa-team
risks:
  - description: Regression in projection cache.
    mitigation: Run grade after qa.
verification_commands:
  - command: "{sys.executable} -c 'print(1)'"
    criterion_ref: C1
  - command: "{sys.executable} -c 'print(2)'"
    criterion_ref: C2
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOBIUS_HOME", str(home))
    runner = CliRunner()

    seed = runner.invoke(app, ["seed", str(spec)], catch_exceptions=False)
    run = runner.invoke(app, ["run", "--spec", str(spec), "--foreground"], catch_exceptions=False)
    with EventStore(home / "events.db", read_only=True) as store:
        latest = store.get_latest_run()
        assert latest is not None
        run_id = latest.aggregate_id
    qa = runner.invoke(app, ["qa", run_id, "--json"], catch_exceptions=False)
    grade = runner.invoke(app, ["grade", "--json"], catch_exceptions=False)
    payload = json.loads(grade.stdout)

    assert seed.exit_code == 0
    assert run.exit_code == 0
    assert qa.exit_code == 0
    assert grade.exit_code == 0
    assert payload["grade"] == "gold"
    assert payload["details"]["all_success_criteria_passed"] is True
    assert payload["details"]["proof_per_criterion"] is True
    with EventStore(home / "events.db", read_only=True) as store:
        events = store.read_events("mobius.grade")
    assert events[-1].type == "spec.grade_assigned"
    assert events[-1].payload_data["grade"] == "gold"
