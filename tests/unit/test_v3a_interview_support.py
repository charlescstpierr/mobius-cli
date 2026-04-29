from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mobius.v3a.cli.commands import run_build
from mobius.v3a.interview.architecte import propose_options
from mobius.v3a.interview.lemma_check import LemmaWindow
from mobius.v3a.interview.oracle import measure_rejections, propose_verifications
from mobius.v3a.interview.runner import run_interview
from mobius.v3a.interview.socrate import Keystroke, parse_keystroke, propose_question
from mobius.v3a.interview.transcript import TranscriptTurn, TranscriptWriter, parse_transcript


def test_transcript_writer_round_trips_turns(tmp_path: Path) -> None:
    path = tmp_path / "transcript.md"
    writer = TranscriptWriter(path)
    writer.append_turn(
        TranscriptTurn(
            turn=1,
            socrate="What should ship first?",
            because="outcome scope",
            human="A CLI.",
            avocat="Hypothetical: empty input appears.",
            architecte=("single-command CLI: fast", "library wrapper: testable"),
        )
    )

    turns = parse_transcript(path.read_text(encoding="utf-8"))

    assert turns == [
        TranscriptTurn(
            turn=1,
            socrate="What should ship first?",
            because="outcome scope",
            human="A CLI.",
            avocat="Hypothetical: empty input appears.",
            architecte=("single-command CLI: fast", "library wrapper: testable"),
        )
    ]
    assert parse_transcript("## Turn not-a-number\n\n") == []


def test_oracle_empty_and_mapping_fallback_paths() -> None:
    empty = propose_verifications([])
    assert empty.criterion_count == 0
    assert empty.heuristic_coverage_rate == 1.0
    assert empty.proposed_criteria_rate == 1.0
    assert empty.all_commands == []
    assert measure_rejections(empty, {"C1"}).reject_rate == 0.0

    report = propose_verifications(
        ["Users feel successful."],
        fallback=lambda _criterion, _index, _transcript: [
            {},
            {"command": ""},
            {"command": "uv run pytest -q tests/e2e", "timeout_s": 90},
        ],
    )

    assert report.all_commands == [
        {
            "command": "uv run pytest -q tests/e2e",
            "timeout_s": 90,
            "criterion_ref": "C1",
            "shell": True,
        }
    ]


def test_socrate_invalid_keystrokes_and_fallback_question() -> None:
    assert parse_keystroke(":") is None
    assert parse_keystroke(":unknown") is None
    parsed = parse_keystroke(":back many")
    assert parsed is not None
    assert parsed.kind is Keystroke.BACK
    assert parsed.count == 1

    previous = [
        "outcome scope first deliverable underspecified surface contract entrypoint "
        "behavior need named interface constraint boundary invariant yet not explicit edgecase "
        "failure exceptional behavior crisp answer verification proof completion "
        "testable signal vocabulary data accepted input domain remain open minimal "
        "example baseline happy path pinned"
    ]
    turn = propose_question(1, previous)

    assert turn.question == "What additional detail would remove the biggest remaining uncertainty?"
    assert "novelty" in turn.because


def test_lemma_window_records_accepted_justifications() -> None:
    window = LemmaWindow(window=1)
    first = window.check("fresh outcome")
    window.accept("fresh outcome")
    second = window.check("fresh outcome")

    assert first.passed is True
    assert second.passed is False
    assert window.justifications == ("fresh outcome",)


def test_non_cli_architecte_options_and_runner_keystroke_paths(tmp_path: Path) -> None:
    options = propose_options("web API", 2)
    assert [option.name for option in options] == [
        "thin vertical slice",
        "modular core",
        "adapter-first shell",
    ]

    result = run_interview(
        intent="tiny API: ship useful output",
        run_id="support",
        output_dir=tmp_path,
        answers=[
            ":restart",
            "Keep all state local and deterministic.",
            "The CLI output includes a colon: value.",
            ":stop",
        ],
    )

    assert result.human_confirmed is True
    assert '"tiny API: ship useful output"' in result.fixture_path.read_text(encoding="utf-8")


def test_run_build_agent_mode_writes_json_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    context = SimpleNamespace(mobius_home=tmp_path / "home", json_output=True)

    run_build(
        context,
        intent="tiny TODO CLI",
        interactive=False,
        wizard=False,
        agent=True,
        auto_top_up=True,
    )

    payload = _payload_for_phase(capsys.readouterr().out, "seed")
    assert payload["phase_done"] == "seed"
    assert payload["next_phase"] == "maturity"
    assert Path(payload["transcript"]).exists()
    assert Path(payload["fixture"]).exists()
    assert Path(payload["spec_yaml"]).exists()


def test_run_build_non_agent_output_includes_seed_and_backup_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "spec.yaml").write_text("goal: previous\n", encoding="utf-8")
    context = SimpleNamespace(mobius_home=tmp_path / "home", json_output=False)

    run_build(
        context,
        intent="tiny TODO CLI",
        interactive=False,
        wizard=False,
        agent=False,
        auto_top_up=True,
    )

    output = capsys.readouterr().out
    assert "[Phase 1/4 complete — Interview]" in output
    assert "[Phase 2/4 complete — Seed]" in output
    assert "[Phase 4/4 complete — Scoring + Delivery]" in output
    backups = list(tmp_path.glob("spec.yaml.pre-build.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "goal: previous\n"


def _payload_for_phase(stdout: str, phase: str) -> dict[str, object]:
    for line in stdout.splitlines():
        payload = json.loads(line)
        if payload.get("phase_done") == phase:
            return payload
    raise AssertionError(f"missing phase payload for {phase!r}: {stdout}")
