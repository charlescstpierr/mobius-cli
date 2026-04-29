"""Heuristic-first verification command extraction for v3a interviews."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

VerificationCommand = dict[str, object]
FallbackResult = str | Mapping[str, object]
VerificationFallback = Callable[[str, int, str], Sequence[FallbackResult]]


@dataclass(frozen=True)
class OracleReport:
    """Verification proposals and extraction metrics for one criteria set."""

    proposals_by_criterion: dict[str, list[VerificationCommand]]
    heuristic_refs: frozenset[str]
    fallback_refs: frozenset[str]

    @property
    def criterion_count(self) -> int:
        """Total number of success criteria inspected."""
        return len(self.proposals_by_criterion)

    @property
    def heuristically_matched(self) -> int:
        """Number of criteria that produced at least one heuristic proposal."""
        return len(self.heuristic_refs)

    @property
    def heuristic_coverage_rate(self) -> float:
        """Share of criteria covered without fallback."""
        if self.criterion_count == 0:
            return 1.0
        return self.heuristically_matched / self.criterion_count

    @property
    def proposed_criteria_rate(self) -> float:
        """Share of criteria with at least one proposed verification command."""
        if self.criterion_count == 0:
            return 1.0
        proposed = sum(1 for commands in self.proposals_by_criterion.values() if commands)
        return proposed / self.criterion_count

    @property
    def all_commands(self) -> list[VerificationCommand]:
        """Flattened proposals in criterion order."""
        commands: list[VerificationCommand] = []
        for ref in self.proposals_by_criterion:
            commands.extend(self.proposals_by_criterion[ref])
        return commands


@dataclass(frozen=True)
class RejectionMetrics:
    """Human-review rejection summary for proposed verification commands."""

    total: int
    rejected: int

    @property
    def reject_rate(self) -> float:
        """Rejected proposals divided by total proposals."""
        if self.total == 0:
            return 0.0
        return self.rejected / self.total


@dataclass(frozen=True)
class _Heuristic:
    pattern: re.Pattern[str]
    command: str
    timeout_s: int


_HEURISTICS: tuple[_Heuristic, ...] = (
    _Heuristic(
        re.compile(r"\b(mypy|type[- ]?check|typing|type safety|types?)\b", re.IGNORECASE),
        "uv run mypy --strict src/mobius/",
        120,
    ),
    _Heuristic(
        re.compile(r"\b(ruff|lint|linting|style|formatting?)\b", re.IGNORECASE),
        "uv run ruff check src/ tests/",
        120,
    ),
    _Heuristic(
        re.compile(r"\b(grade|gold|silver|bronze)\b", re.IGNORECASE),
        "uv run mobius grade",
        120,
    ),
    _Heuristic(
        re.compile(r"\b(workflow smoke|smoke test|smoke)\b", re.IGNORECASE),
        "uv run mobius workflow smoke",
        120,
    ),
    _Heuristic(
        re.compile(
            r"\b(cold[- ]?start|startup|start-up|latency|performance|under \d+\s*ms)\b",
            re.IGNORECASE,
        ),
        "uv run pytest -q tests/unit/test_cold_start.py",
        120,
    ),
    _Heuristic(
        re.compile(
            r"\b(coverage|pytest|unit test|unit tests|tests? pass|test suite|regression)\b",
            re.IGNORECASE,
        ),
        "uv run pytest -q",
        180,
    ),
    _Heuristic(
        re.compile(r"\b(e2e|end[- ]to[- ]end|integration|user flow|workflow)\b", re.IGNORECASE),
        "uv run pytest -q tests/e2e",
        180,
    ),
    _Heuristic(
        re.compile(r"\b(cli|command|--help|exit code|stdout|stderr|terminal)\b", re.IGNORECASE),
        "uv run pytest -q tests/e2e/cli",
        180,
    ),
    _Heuristic(
        re.compile(r"\b(api|endpoint|http|json response|status code|request)\b", re.IGNORECASE),
        "uv run pytest -q tests/e2e",
        180,
    ),
    _Heuristic(
        re.compile(
            r"\b(database|sqlite|event store|event-store|migration|projection)\b",
            re.IGNORECASE,
        ),
        "uv run pytest -q tests/unit/persistence",
        180,
    ),
    _Heuristic(
        re.compile(r"\b(yaml|spec\.yaml|seed spec|seed|schema)\b", re.IGNORECASE),
        "uv run pytest -q tests/unit/workflow/test_seed.py",
        120,
    ),
    _Heuristic(
        re.compile(r"\b(qa|quality assurance|verdict|verification proof)\b", re.IGNORECASE),
        "uv run pytest -q tests/unit/workflow/test_qa.py",
        120,
    ),
    _Heuristic(
        re.compile(r"\b(handoff|agent prompt|claude|codex|hermes)\b", re.IGNORECASE),
        "uv run pytest -q tests/unit/test_handoff.py",
        120,
    ),
    _Heuristic(
        re.compile(
            r"\b(interview|transcript|socrate|avocat|architecte|ambiguity)\b",
            re.IGNORECASE,
        ),
        (
            "uv run pytest -q tests/unit/test_v3a_interview_core.py "
            "tests/e2e/test_v3a_interview_todo.py"
        ),
        180,
    ),
    _Heuristic(
        re.compile(r"\b(ui|browser|page|screen|form|button)\b", re.IGNORECASE),
        "uv run pytest -q tests/e2e",
        180,
    ),
    _Heuristic(
        re.compile(r"\b(package|packaging|install|wheel|entrypoint|binary)\b", re.IGNORECASE),
        (
            "uv run pytest -q tests/e2e/test_packaging_release.py "
            "tests/e2e/test_installed_binary_contract.py"
        ),
        180,
    ),
    _Heuristic(
        re.compile(r"\b(security|auth|permission|access control|token)\b", re.IGNORECASE),
        "uv run pytest -q tests",
        180,
    ),
)


def propose_verifications(
    success_criteria: Sequence[str],
    *,
    transcript: str = "",
    fallback: VerificationFallback | None = None,
) -> OracleReport:
    """Propose v2-compatible ``verification_commands`` for success criteria.

    Extraction is deliberately heuristic-first: every criterion is matched
    against deterministic regex/keyword rules before any fallback is invoked.
    The fallback hook exists for a future/mock LLM; it is only called when the
    cheap heuristic pass yields no command for that specific criterion.
    """
    proposals: dict[str, list[VerificationCommand]] = {}
    heuristic_refs: set[str] = set()
    fallback_refs: set[str] = set()

    for index, raw_criterion in enumerate(success_criteria, start=1):
        criterion = str(raw_criterion).strip()
        ref = criterion_ref(index)
        commands = _heuristic_commands(criterion, index)
        if commands:
            heuristic_refs.add(ref)
        else:
            commands = _fallback_commands(criterion, index, transcript, fallback)
            if commands:
                fallback_refs.add(ref)
        proposals[ref] = commands

    return OracleReport(
        proposals_by_criterion=proposals,
        heuristic_refs=frozenset(heuristic_refs),
        fallback_refs=frozenset(fallback_refs),
    )


def propose_verification_commands(
    success_criteria: Sequence[str],
    *,
    transcript: str = "",
    fallback: VerificationFallback | None = None,
) -> list[VerificationCommand]:
    """Return flattened v2 ``verification_commands`` for a seed spec."""
    return propose_verifications(
        success_criteria,
        transcript=transcript,
        fallback=fallback,
    ).all_commands


def measure_rejections(
    report: OracleReport,
    rejected_refs: set[str] | frozenset[str],
) -> RejectionMetrics:
    """Measure human-marked invalid proposals by criterion reference."""
    total = 0
    rejected = 0
    normalized_rejected = {_normalize_ref(ref) for ref in rejected_refs}
    for ref, commands in report.proposals_by_criterion.items():
        total += len(commands)
        if _normalize_ref(ref) in normalized_rejected:
            rejected += len(commands)
    return RejectionMetrics(total=total, rejected=rejected)


def criterion_ref(index: int) -> str:
    """Return the v2-compatible criterion reference used by QA matching."""
    return f"C{index}"


def _heuristic_commands(criterion: str, index: int) -> list[VerificationCommand]:
    commands: list[VerificationCommand] = []
    seen: set[str] = set()
    for heuristic in _HEURISTICS:
        if not heuristic.pattern.search(criterion):
            continue
        if heuristic.command in seen:
            continue
        seen.add(heuristic.command)
        commands.append(_command(heuristic.command, index=index, timeout_s=heuristic.timeout_s))
    return commands


def _fallback_commands(
    criterion: str,
    index: int,
    transcript: str,
    fallback: VerificationFallback | None,
) -> list[VerificationCommand]:
    if fallback is None:
        return []

    commands: list[VerificationCommand] = []
    for item in fallback(criterion, index, transcript):
        if isinstance(item, str):
            if item.strip():
                commands.append(_command(item, index=index, timeout_s=180))
            continue
        raw_command = item.get("command")
        if not isinstance(raw_command, str) or not raw_command.strip():
            continue
        normalized = dict(item)
        normalized.setdefault("criterion_ref", criterion_ref(index))
        normalized.setdefault("timeout_s", 180)
        normalized.setdefault("shell", True)
        commands.append(normalized)
    return commands


def _command(command: str, *, index: int, timeout_s: int) -> VerificationCommand:
    return {
        "command": command,
        "timeout_s": timeout_s,
        "criterion_ref": criterion_ref(index),
        "shell": True,
    }


def _normalize_ref(value: object) -> str:
    return " ".join(str(value).strip().split()).lower()
