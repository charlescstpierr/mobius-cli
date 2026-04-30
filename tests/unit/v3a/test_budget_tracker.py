from __future__ import annotations

from pathlib import Path

from mobius.v3a.interview.runner import run_interview


class FakeBudgetTracker:
    def __init__(self) -> None:
        self.usd_spent = 1.25
        self.turns_recorded = 0

    def record_mock_turn(self) -> float:
        self.turns_recorded += 1
        self.usd_spent = round(self.usd_spent + 0.5, 2)
        return self.usd_spent


def test_run_interview_uses_injected_budget_tracker(tmp_path: Path) -> None:
    budget = FakeBudgetTracker()

    result = run_interview(
        intent="tiny TODO CLI",
        run_id="build-test",
        output_dir=tmp_path,
        answers=[
            "Keep state local and deterministic.",
            "Test add and list commands end-to-end.",
            ":enough",
        ],
        budget_tracker=budget,
    )

    assert budget.turns_recorded == 1
    assert result.usd_spent == 1.75
