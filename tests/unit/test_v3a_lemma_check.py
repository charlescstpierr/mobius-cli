from __future__ import annotations

from mobius.v3a.interview.lemma_check import check_rolling_lemma
from mobius.v3a.interview.socrate import propose_question


def test_generated_justifications_pass_rolling_five_rule_at_99_percent() -> None:
    previous: list[str] = []
    passed = 0

    for index in range(100):
        turn = propose_question(index, previous)
        assert turn.lemma_check is not None
        if turn.lemma_check.passed:
            passed += 1
            previous.append(turn.because)

    assert passed >= 99


def test_convergence_proposing_turn_passes_lemma_check_unconditionally() -> None:
    previous = [
        "convergence ambiguity threshold",
        "convergence ambiguity threshold",
        "convergence ambiguity threshold",
        "convergence ambiguity threshold",
        "convergence ambiguity threshold",
    ]

    result = check_rolling_lemma(
        "convergence ambiguity threshold",
        previous,
        convergence_proposal=True,
    )

    assert result.passed is True
    assert result.reason == "convergence proposal exempt"


def test_non_convergence_repetition_is_blocked() -> None:
    previous = [
        "surface contract",
        "surface contract",
        "surface contract",
        "surface contract",
        "surface contract",
    ]

    result = check_rolling_lemma("surface contract", previous)

    assert result.passed is False
