from __future__ import annotations

from mobius.v3a.scoring.llm_judge import (
    LLMJudgeInputs,
    build_prompt,
    hash_prompt,
    judge_llm_dimensions,
)


def test_llm_portion_stamps_model_temp_and_stable_prompt_hash(monkeypatch, scoring_spec) -> None:
    monkeypatch.setenv(
        "MOBIUS_LLM_MOCK_PATTERN",
        "goal_alignment=111,code_quality=010,test_quality=110",
    )
    inputs = LLMJudgeInputs(
        spec=scoring_spec,
        mechanical_breakdown={"spec_completeness": 1, "coverage": 1},
        artifacts={"b": ["two", "items"], "a": 1},
        model="mock-model",
        temp=0.0,
    )

    first = judge_llm_dimensions(inputs)
    second = judge_llm_dimensions(inputs)

    assert first.prompt_hash == second.prompt_hash
    assert first.breakdown["prompt_hash"] == second.breakdown["prompt_hash"]
    assert first.breakdown["model"] == "mock-model"
    assert first.breakdown["temp"] == 0.0
    assert first.dimension_scores == {
        "goal_alignment": 1,
        "code_quality": 0,
        "test_quality": 1,
    }


def test_prompt_hash_uses_canonical_prompt_for_same_inputs(scoring_spec) -> None:
    first = LLMJudgeInputs(
        spec=scoring_spec,
        mechanical_breakdown={"coverage": 1, "spec_completeness": 1},
        artifacts={"z": 2, "a": 1},
    )
    second = LLMJudgeInputs(
        spec=scoring_spec,
        mechanical_breakdown={"spec_completeness": 1, "coverage": 1},
        artifacts={"a": 1, "z": 2},
    )

    assert build_prompt(first) == build_prompt(second)
    assert hash_prompt(build_prompt(first)) == hash_prompt(build_prompt(second))
