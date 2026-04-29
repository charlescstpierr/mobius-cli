from __future__ import annotations

import ast
from pathlib import Path

from mobius.v3a.interview.ambiguity_trend import convergence_conditions_met
from mobius.v3a.interview.runner import run_interview
from mobius.workflow.interview import compute_ambiguity_score, parse_fixture


def test_convergence_on_adversarial_input_reaches_gate_in_at_most_eight_turns(
    tmp_path: Path,
) -> None:
    result = run_interview(
        intent="tiny TODO CLI",
        run_id="build-test",
        output_dir=tmp_path,
        answers=[
            "TBD",
            "Keep all state local and deterministic.",
            "TODO",
            "Empty input returns exit code 2 with a helpful message.",
            "Test add, list, and done commands end-to-end.",
            "Support add, list, done, empty, duplicate, malformed.",
        ],
    )

    assert result.turns <= 8
    assert result.ambiguity_score <= 0.18
    assert result.ambiguity_score < 0.2
    assert result.max_component < 0.4
    assert result.socrate_proposed_done is True
    assert result.human_confirmed is True


def test_ambiguity_scoring_uses_verbatim_v2_symbol(tmp_path: Path) -> None:
    result = run_interview(intent="tiny TODO CLI", run_id="build-test", output_dir=tmp_path)
    fixture = parse_fixture(result.fixture_path)

    first = compute_ambiguity_score(fixture)
    second = compute_ambiguity_score(fixture)

    assert first == second
    assert convergence_conditions_met(fixture)
    source = Path("src/mobius/v3a/interview/ambiguity_trend.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "mobius.workflow.interview"
        for alias in node.names
    }
    assert "compute_ambiguity_score" in imported_names


def test_f01_modules_do_not_instantiate_rich_live() -> None:
    root = Path("src/mobius/v3a/interview")

    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "rich.live" not in source.lower()
        assert "Live(" not in source
