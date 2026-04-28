"""Verification command execution for proof-based QA."""

from __future__ import annotations

import shlex
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mobius.persistence.event_store import iso8601_utc_now

_DEFAULT_TIMEOUT_SECONDS = 60
_DEFAULT_MAX_OUTPUT_BYTES = 64 * 1024
_TRUNCATED_MARKER = "\n[truncated at 64KB]"


@dataclass(frozen=True)
class ProofRecord:
    """Captured proof for one verification command."""

    command: str
    criterion_ref: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    truncated: bool
    timed_out: bool
    started_at: str

    @property
    def verdict(self) -> str:
        """Return the command verdict used by QA."""
        return "PASS" if self.exit_code == 0 and not self.timed_out else "FAIL"

    def executed_event_payload(self) -> dict[str, Any]:
        """Return the ``qa.verification_executed`` event payload."""
        return {
            "command": self.command,
            "criterion_ref": self.criterion_ref,
            "started_at": self.started_at,
        }

    def proof_event_payload(self) -> dict[str, Any]:
        """Return the ``qa.proof_collected`` event payload."""
        return {
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "criterion_ref": self.criterion_ref,
            "truncated": self.truncated,
            "timed_out": self.timed_out,
        }


def run_verification(
    command_spec: Mapping[str, Any],
    cwd: Path,
    config: Mapping[str, Any],
) -> ProofRecord:
    """Run one verification command and return captured proof.

    Command process failures are represented as a failing ``ProofRecord``.
    ``ValueError`` is reserved for malformed command specifications.
    """
    command = _command_text(command_spec)
    criterion_ref = _criterion_ref(command_spec)
    timeout_s = _timeout_seconds(command_spec, config)
    max_output_bytes = _max_output_bytes(config)
    shell = _shell_enabled(command_spec)
    run_command: str | list[str] = command if shell else shlex.split(command)
    started_at = iso8601_utc_now()
    start = time.monotonic()

    try:
        completed = subprocess.run(
            run_command,
            shell=shell,
            timeout=timeout_s,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = _duration_ms(start)
        stdout, stderr, truncated = _cap_outputs(
            _coerce_output(exc.stdout),
            _coerce_output(exc.stderr),
            max_output_bytes,
        )
        return ProofRecord(
            command=command,
            criterion_ref=criterion_ref,
            stdout=stdout,
            stderr=stderr,
            exit_code=124,
            duration_ms=duration_ms,
            truncated=truncated,
            timed_out=True,
            started_at=started_at,
        )
    except OSError as exc:
        duration_ms = _duration_ms(start)
        stdout, stderr, truncated = _cap_outputs("", str(exc), max_output_bytes)
        return ProofRecord(
            command=command,
            criterion_ref=criterion_ref,
            stdout=stdout,
            stderr=stderr,
            exit_code=127,
            duration_ms=duration_ms,
            truncated=truncated,
            timed_out=False,
            started_at=started_at,
        )

    duration_ms = _duration_ms(start)
    stdout, stderr, truncated = _cap_outputs(
        completed.stdout,
        completed.stderr,
        max_output_bytes,
    )
    return ProofRecord(
        command=command,
        criterion_ref=criterion_ref,
        stdout=stdout,
        stderr=stderr,
        exit_code=int(completed.returncode),
        duration_ms=duration_ms,
        truncated=truncated,
        timed_out=False,
        started_at=started_at,
    )


def _command_text(command_spec: Mapping[str, Any]) -> str:
    value = command_spec.get("command")
    if not isinstance(value, str) or not value.strip():
        msg = "verification command requires a non-empty 'command' string"
        raise ValueError(msg)
    return value


def _criterion_ref(command_spec: Mapping[str, Any]) -> str:
    for key in ("criterion_ref", "criterion_refs", "criteria"):
        value = command_spec.get(key)
        if isinstance(value, list) and value:
            return str(value[0]).strip()
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _timeout_seconds(command_spec: Mapping[str, Any], config: Mapping[str, Any]) -> float:
    value = command_spec.get(
        "timeout_s",
        config.get("verification_timeout_s", config.get("timeout_s", _DEFAULT_TIMEOUT_SECONDS)),
    )
    try:
        timeout_s = float(str(value))
    except (TypeError, ValueError) as exc:
        msg = "verification timeout_s must be numeric"
        raise ValueError(msg) from exc
    if timeout_s <= 0:
        msg = "verification timeout_s must be greater than zero"
        raise ValueError(msg)
    return timeout_s


def _max_output_bytes(config: Mapping[str, Any]) -> int:
    value = config.get("max_output_bytes", _DEFAULT_MAX_OUTPUT_BYTES)
    try:
        max_output_bytes = int(str(value))
    except (TypeError, ValueError) as exc:
        msg = "verification max_output_bytes must be an integer"
        raise ValueError(msg) from exc
    if max_output_bytes <= 0:
        msg = "verification max_output_bytes must be greater than zero"
        raise ValueError(msg)
    return max_output_bytes


def _shell_enabled(command_spec: Mapping[str, Any]) -> bool:
    value = command_spec.get("shell", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    msg = "verification shell must be a boolean"
    raise ValueError(msg)


def _duration_ms(start: float) -> int:
    return max(0, round((time.monotonic() - start) * 1000))


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _cap_outputs(stdout: str, stderr: str, max_bytes: int) -> tuple[str, str, bool]:
    stdout_bytes = stdout.encode("utf-8")
    stderr_bytes = stderr.encode("utf-8")
    if len(stdout_bytes) + len(stderr_bytes) <= max_bytes:
        return stdout, stderr, False

    remaining = max_bytes
    capped_stdout, remaining = _take_with_marker(stdout, remaining)
    capped_stderr = ""
    if remaining > 0:
        capped_stderr, remaining = _take_with_marker(stderr, remaining)
    _ = remaining
    return capped_stdout, capped_stderr, True


def _take_with_marker(value: str, budget: int) -> tuple[str, int]:
    if budget <= 0:
        return "", 0
    value_bytes = value.encode("utf-8")
    if len(value_bytes) <= budget:
        return value, budget - len(value_bytes)

    marker_bytes = _TRUNCATED_MARKER.encode("utf-8")
    if budget <= len(marker_bytes):
        return marker_bytes[:budget].decode("utf-8", errors="ignore"), 0
    content_budget = budget - len(marker_bytes)
    content = value_bytes[:content_budget].decode("utf-8", errors="ignore")
    return f"{content}{_TRUNCATED_MARKER}", 0
