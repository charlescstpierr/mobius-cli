from __future__ import annotations

from mobius.v3a.scoring.rationale import build_score_rationale, mentioned_dimension_count


def test_rationale_has_three_sentences_llm_prefix_and_six_dimensions() -> None:
    rationale = build_score_rationale(
        mechanical={
            "spec_completeness": 1,
            "coverage": 1,
            "mypy": 1,
            "verifications_pass": 1,
            "ambiguity": 1,
            "no_timeouts": 1,
            "ruff_clean": 1,
        },
        llm={"goal_alignment": 1, "code_quality": 0, "test_quality": 1},
    )

    sentences = [sentence.strip() for sentence in rationale.split(".") if sentence.strip()]

    assert len(sentences) >= 3
    assert any(sentence.startswith("[LLM]") for sentence in sentences)
    assert all(
        sentence.startswith("[LLM]")
        for sentence in sentences
        if any(dim in sentence for dim in ("goal_alignment", "code_quality", "test_quality"))
    )
    assert mentioned_dimension_count(rationale) >= 6
