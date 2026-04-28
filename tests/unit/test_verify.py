from __future__ import annotations

import sys
from pathlib import Path

from mobius.workflow.verify import run_verification


def test_command_timeout(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c 'import time; time.sleep(5)'",
            "timeout_s": 0.1,
            "criterion_ref": "timeout",
            "shell": False,
        },
        tmp_path,
        {},
    )

    assert proof.timed_out is True
    assert proof.exit_code == 124
    assert proof.verdict == "FAIL"


def test_no_shell_uses_shlex(tmp_path: Path) -> None:
    (tmp_path / "expanded-by-shell.txt").write_text("fixture", encoding="utf-8")

    proof = run_verification(
        {
            "command": f"{sys.executable} -c 'import sys; print(sys.argv[1])' *",
            "timeout_s": 5,
            "criterion_ref": "no-shell",
            "shell": False,
        },
        tmp_path,
        {},
    )

    assert proof.exit_code == 0
    assert proof.stdout.strip() == "*"


def test_output_capped_at_64kb(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c \"print('x' * (1024 * 1024))\"",
            "timeout_s": 5,
            "criterion_ref": "output-cap",
        },
        tmp_path,
        {"max_output_bytes": 64 * 1024},
    )

    assert proof.exit_code == 0
    assert proof.truncated is True
    assert len(proof.stdout.encode("utf-8")) <= 64 * 1024
    assert proof.stdout.endswith("\n[truncated at 64KB]")


def test_proof_event_payload_shape(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c 'print(7)'",
            "timeout_s": 5,
            "criterion_ref": "B9",
        },
        tmp_path,
        {},
    )

    executed = proof.executed_event_payload()
    payload = proof.proof_event_payload()

    assert executed == {
        "command": proof.command,
        "criterion_ref": "B9",
        "started_at": proof.started_at,
    }
    assert payload["command"] == proof.command
    assert payload["stdout"].strip() == "7"
    assert payload["stderr"] == ""
    assert payload["exit_code"] == 0
    assert isinstance(payload["duration_ms"], int)
    assert payload["criterion_ref"] == "B9"
    assert payload["truncated"] is False
    assert payload["timed_out"] is False


def test_missing_executable_becomes_failed_proof(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": "definitely-not-a-mobius-command",
            "criterion_refs": ["missing-executable"],
            "shell": False,
        },
        tmp_path,
        {},
    )

    assert proof.exit_code == 127
    assert proof.timed_out is False
    assert proof.criterion_ref == "missing-executable"
    assert proof.stderr


def test_shell_string_false_and_config_timeout(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c 'print(8)'",
            "criterion_ref": "string-shell",
            "shell": "false",
        },
        tmp_path,
        {"verification_timeout_s": "5"},
    )

    assert proof.exit_code == 0
    assert proof.stdout.strip() == "8"


def test_shell_string_true_and_default_criterion_ref(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c 'print(9)'",
            "criteria": "criterion-from-criteria",
            "shell": "true",
        },
        tmp_path,
        {"timeout_s": "5"},
    )

    assert proof.exit_code == 0
    assert proof.criterion_ref == "criterion-from-criteria"


def test_stderr_receives_remaining_output_budget(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": (
                f"{sys.executable} -c \"import sys; "
                "sys.stdout.write('out'); sys.stderr.write('e' * 200)\""
            ),
            "timeout_s": 5,
            "criterion_ref": "stderr-cap",
        },
        tmp_path,
        {"max_output_bytes": 64},
    )

    assert proof.truncated is True
    assert proof.stdout == "out"
    assert proof.stderr.endswith("\n[truncated at 64KB]")
    assert len((proof.stdout + proof.stderr).encode("utf-8")) <= 64


def test_tiny_output_budget_still_caps(tmp_path: Path) -> None:
    proof = run_verification(
        {
            "command": f"{sys.executable} -c \"print('abcdef')\"",
            "timeout_s": 5,
            "criterion_ref": "tiny-cap",
        },
        tmp_path,
        {"max_output_bytes": 4},
    )

    assert proof.truncated is True
    assert len((proof.stdout + proof.stderr).encode("utf-8")) <= 4


def test_bad_command_spec_shape_raises_value_error(tmp_path: Path) -> None:
    bad_specs = [
        {},
        {"command": "echo hi", "timeout_s": "not-a-number"},
        {"command": "echo hi", "timeout_s": 0},
        {"command": "echo hi", "shell": "maybe"},
    ]

    for spec in bad_specs:
        try:
            run_verification(spec, tmp_path, {})
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {spec}")
