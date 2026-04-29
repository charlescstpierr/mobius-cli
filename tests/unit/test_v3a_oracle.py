from __future__ import annotations

from mobius.v3a.interview.oracle import (
    measure_rejections,
    propose_verification_commands,
    propose_verifications,
)

CORPUS: tuple[str, ...] = (
    "Pytest passes for the complete unit test suite.",
    "Unit tests cover the parser regression paths.",
    "The end-to-end workflow test covers interview to qa.",
    "CLI command returns exit code 2 for bad input.",
    "The --help output documents all supported command flags.",
    "stdout includes the generated run identifier.",
    "stderr contains a clear validation error.",
    "Ruff linting remains clean.",
    "Mypy strict type checking reports zero errors.",
    "The project grade remains Gold.",
    "The workflow smoke test exits successfully.",
    "Cold-start latency stays under 100 ms.",
    "Coverage remains at least 95 percent.",
    "Regression tests cover malformed YAML.",
    "Integration tests exercise the JSON API endpoint.",
    "HTTP requests return a 200 status code.",
    "The JSON response contains the expected payload.",
    "Database migrations preserve existing event store rows.",
    "SQLite recovery handles interrupted writes.",
    "Projection rebuild produces the same snapshot.",
    "Seed spec YAML accepts success_criteria.",
    "Spec.yaml schema rejects unknown keys.",
    "QA returns a passing verdict for complete runs.",
    "Verification proof events are collected.",
    "Agent handoff prompt references Claude, Codex, and Hermes.",
    "The interview transcript includes Socrate rationales.",
    "Ambiguity score converges below the gate.",
    "Avocat injects an edge case statement.",
    "Architecte returns design options with trade-offs.",
    "Browser UI form submits successfully.",
    "The screen shows the completion panel.",
    "Packaging creates an installable wheel.",
    "Installed binary entrypoint starts the CLI.",
    "Security checks reject unauthorized access.",
    "Authentication tokens are not printed in logs.",
    "Permission errors produce actionable messages.",
    "The terminal command lists created TODO items.",
    "The CLI supports add, list, and done commands.",
    "The smoke scenario completes without crashing.",
    "The test suite passes before release.",
    "Type safety is maintained for new modules.",
    "Lint style stays compliant.",
    "The bronze seed validation grade is assigned.",
    "The workflow status command reports progress.",
    "The API endpoint validates malformed JSON.",
    "The event-store projection cache rebuilds deterministically.",
    "The setup command installs agent prompt assets.",
    "The run command writes stdout discipline logs.",
    "The QA command detects unverified criteria.",
    "The handoff output includes each verification command.",
    # Deliberately vague criteria below model cases that should fall through to
    # the LLM/mock fallback and be rejected by the human review fixture.
    "The product feels delightful to first-time users.",
    "The design is polished and memorable.",
    "Users understand the value immediately.",
    "The experience is better than the old workflow.",
    "The implementation is maintainable over time.",
    "The feature makes teams more confident.",
    "The app is ready for real customers.",
    "The output is useful in normal situations.",
    "The process is easier than before.",
    "The result matches the stakeholder's intent.",
)


def _mock_llm_fallback(criterion: str, index: int, transcript: str) -> list[str]:
    assert criterion
    assert index >= 1
    assert "Interview" in transcript
    return ["uv run pytest -q"]


def test_oracle_heuristic_catches_at_least_eighty_percent_of_corpus() -> None:
    report = propose_verifications(
        CORPUS,
        transcript="Interview transcript",
        fallback=_mock_llm_fallback,
    )

    assert report.criterion_count == 60
    assert report.heuristic_coverage_rate >= 0.80
    assert report.proposed_criteria_rate == 1.0


def test_oracle_reject_rate_stays_at_or_below_twenty_percent() -> None:
    report = propose_verifications(
        CORPUS,
        transcript="Interview transcript",
        fallback=_mock_llm_fallback,
    )
    human_rejected_refs = set(report.fallback_refs)

    metrics = measure_rejections(report, human_rejected_refs)

    assert metrics.total >= len(CORPUS)
    assert metrics.reject_rate <= 0.20


def test_oracle_fallback_is_only_used_when_heuristic_yields_nothing() -> None:
    calls: list[str] = []

    def fallback(criterion: str, index: int, transcript: str) -> list[str]:
        calls.append(f"{index}:{criterion}:{transcript}")
        return ["uv run pytest -q"]

    report = propose_verifications(
        ["Ruff linting stays clean.", "Users feel successful."],
        transcript="Interview transcript",
        fallback=fallback,
    )

    assert calls == ["2:Users feel successful.:Interview transcript"]
    assert report.heuristic_refs == frozenset({"C1"})
    assert report.fallback_refs == frozenset({"C2"})


def test_oracle_returns_v2_verification_command_shape() -> None:
    commands = propose_verification_commands(
        ["CLI command returns exit code 2 and prints stderr."],
        transcript="Interview transcript",
    )

    assert commands == [
        {
            "command": "uv run pytest -q tests/e2e/cli",
            "timeout_s": 180,
            "criterion_ref": "C1",
            "shell": True,
        }
    ]
