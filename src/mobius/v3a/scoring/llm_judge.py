"""Stable LLM-style binary judgments for the v3a score."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any

from mobius.workflow.seed import SeedSpec

LLM_DIMENSIONS: tuple[str, ...] = ("goal_alignment", "code_quality", "test_quality")
DEFAULT_MODEL = "mobius-v3a-mock-judge"
DEFAULT_TEMP = 0.0


@dataclass(frozen=True)
class LLMJudgeInputs:
    """Inputs sent to the three binary LLM dimension judges."""

    spec: SeedSpec
    mechanical_breakdown: dict[str, int]
    artifacts: dict[str, Any] = field(default_factory=dict)
    model: str = DEFAULT_MODEL
    temp: float = DEFAULT_TEMP


@dataclass(frozen=True)
class LLMJudgeResult:
    """Median-of-three LLM score result."""

    breakdown: dict[str, int | str | float]
    prompt_hash: str
    calls: dict[str, tuple[bool, bool, bool]]

    @property
    def dimension_scores(self) -> dict[str, int]:
        """Return only the three binary LLM dimension scores."""
        return {dim: int(self.breakdown[dim]) for dim in LLM_DIMENSIONS}


def judge_llm_dimensions(inputs: LLMJudgeInputs) -> LLMJudgeResult:
    """Judge the three LLM dimensions by median of three yes/no calls."""
    prompt = build_prompt(inputs)
    prompt_hash = hash_prompt(prompt)
    calls: dict[str, tuple[bool, bool, bool]] = {}
    scores: dict[str, int | str | float] = {}
    for dimension in LLM_DIMENSIONS:
        judgments = (
            _judge_once(dimension, prompt, 0),
            _judge_once(dimension, prompt, 1),
            _judge_once(dimension, prompt, 2),
        )
        calls[dimension] = judgments
        scores[dimension] = int(sum(1 for value in judgments if value) >= 2)
    scores["model"] = inputs.model
    scores["temp"] = inputs.temp
    scores["prompt_hash"] = prompt_hash
    return LLMJudgeResult(breakdown=scores, prompt_hash=prompt_hash, calls=calls)


def build_prompt(inputs: LLMJudgeInputs) -> str:
    """Build a canonical, hash-stable prompt for LLM scoring."""
    payload = {
        "goal": inputs.spec.goal,
        "constraints": list(inputs.spec.constraints),
        "success_criteria": list(inputs.spec.success_criteria),
        "context": inputs.spec.context,
        "mechanical_breakdown": dict(sorted(inputs.mechanical_breakdown.items())),
        "artifacts": _canonicalize(inputs.artifacts),
        "dimensions": list(LLM_DIMENSIONS),
        "instruction": "Return yes/no for goal_alignment, code_quality, and test_quality.",
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_prompt(prompt: str) -> str:
    """Return the required sha256 prompt stamp."""
    return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def _judge_once(dimension: str, prompt: str, call_index: int) -> bool:
    mode = os.environ.get("MOBIUS_LLM_MODE", "mock").strip().lower()
    if mode != "mock":
        # v3a keeps real-provider integration out of the core engine; non-mock
        # mode remains deterministic and side-effect free until a later adapter
        # owns authenticated provider calls.
        return _deterministic_yes(dimension, prompt, call_index)
    pattern = os.environ.get("MOBIUS_LLM_MOCK_PATTERN", "").strip()
    if pattern:
        return _pattern_value(pattern, dimension, call_index)
    return _deterministic_yes(dimension, prompt, call_index)


def _deterministic_yes(dimension: str, prompt: str, call_index: int) -> bool:
    _ = (dimension, prompt, call_index)
    return True


def _pattern_value(pattern: str, dimension: str, call_index: int) -> bool:
    entries = {
        item.split("=", 1)[0].strip(): item.split("=", 1)[1].strip()
        for item in pattern.split(",")
        if "=" in item
    }
    raw = entries.get(dimension, "111")
    if not raw:
        return True
    index = min(call_index, len(raw) - 1)
    return raw[index] in {"1", "y", "Y", "t", "T"}


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_canonicalize(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
