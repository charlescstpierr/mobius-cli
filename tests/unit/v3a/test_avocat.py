from __future__ import annotations

from pathlib import Path

from mobius.v3a.interview.avocat import AvocatStatement
from mobius.v3a.interview.runner import run_interview
from mobius.v3a.interview.transcript import parse_transcript


class FakeAvocat:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def inject_edge_case(self, turn_index: int, intent: str) -> AvocatStatement:
        self.calls.append((turn_index, intent))
        return AvocatStatement(statement=f"Fake edge case for turn {turn_index}.")


def test_run_interview_uses_injected_avocat_adapter(tmp_path: Path) -> None:
    avocat = FakeAvocat()

    result = run_interview(
        intent="tiny TODO CLI",
        run_id="build-test",
        output_dir=tmp_path,
        answers=[
            "Keep state local and deterministic.",
            "Test add and list commands end-to-end.",
            ":enough",
        ],
        avocat=avocat,
    )

    transcript = parse_transcript(result.transcript_path.read_text(encoding="utf-8"))

    assert avocat.calls == [(1, "tiny TODO CLI")]
    assert [turn.avocat for turn in transcript] == ["Fake edge case for turn 1."]
