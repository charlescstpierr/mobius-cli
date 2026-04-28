"""Projection-backed HUD summaries for Mobius."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from mobius.persistence.event_store import EventStore
from mobius.persistence.projections import load_projection_snapshot


class HudCriterion(BaseModel):
    """One criterion row displayed by ``mobius hud``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    verdict: str
    commands: list[str]


class HudSpec(BaseModel):
    """Current spec metadata from the projection cache."""

    model_config = ConfigDict(extra="forbid")

    goal: str
    owner: str
    grade: str


class HudRun(BaseModel):
    """Latest run metadata from the projection cache."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    status: str
    duration: str


class HudSummary(BaseModel):
    """Full HUD payload derived from one projection snapshot."""

    model_config = ConfigDict(extra="forbid")

    spec: HudSpec
    latest_run: HudRun
    criteria: list[HudCriterion]
    next_recommended_command: str | None
    proofs_collected: int
    last_qa_timestamp: str
    stale: bool


@dataclass(frozen=True)
class HudLoadResult:
    """HUD payload with the raw projection snapshot used to build it."""

    summary: HudSummary
    projection_snapshot: dict[str, Any]


def load_hud(event_store_path: Path) -> HudLoadResult:
    """Load the HUD strictly from the projection cache, never replaying events."""
    if not event_store_path.exists():
        snapshot: dict[str, Any] = {}
    else:
        with EventStore(event_store_path, read_only=True) as store:
            snapshot = load_projection_snapshot(store.connection)
    return HudLoadResult(
        summary=build_hud_summary(snapshot),
        projection_snapshot=snapshot,
    )


def build_hud_summary(snapshot: dict[str, Any]) -> HudSummary:
    """Build a typed HUD payload from a projection snapshot."""
    spec = _dict(snapshot.get("current_spec"))
    grade = _dict(snapshot.get("last_grade"))
    latest_run = _dict(snapshot.get("latest_run"))
    criteria = _criteria(snapshot)
    return HudSummary(
        spec=HudSpec(
            goal=_text(spec.get("goal"), "(unknown)"),
            owner=_owner_text(spec.get("owner")),
            grade=_text(grade.get("grade"), "ungraded"),
        ),
        latest_run=HudRun(
            id=_text(latest_run.get("id"), "(none)"),
            title=_text(latest_run.get("title"), "(none)"),
            status=_text(latest_run.get("status"), "unknown"),
            duration=_duration(latest_run),
        ),
        criteria=criteria,
        next_recommended_command=_next_command(criteria),
        proofs_collected=_int(snapshot.get("proofs_collected")),
        last_qa_timestamp=_text(snapshot.get("last_qa_timestamp"), "(none)"),
        stale=bool(snapshot.get("stale", False)),
    )


def _criteria(snapshot: dict[str, Any]) -> list[HudCriterion]:
    raw = snapshot.get("criteria")
    if isinstance(raw, list):
        rows: list[HudCriterion] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, dict):
                continue
            commands_raw = item.get("commands")
            commands = (
                [str(command) for command in commands_raw]
                if isinstance(commands_raw, list)
                else []
            )
            rows.append(
                HudCriterion(
                    id=_text(item.get("id"), f"C{index}"),
                    label=_text(item.get("label"), _text(item.get("id"), f"Criterion {index}")),
                    verdict=_text(item.get("verdict"), "unverified").lower(),
                    commands=commands,
                )
            )
        if rows:
            return rows

    summary = _dict(snapshot.get("criteria_summary"))
    by_criterion = _dict(summary.get("by_criterion"))
    return [
        HudCriterion(id=str(key), label=str(key), verdict=str(value).lower(), commands=[])
        for key, value in sorted(by_criterion.items())
    ]


def _next_command(criteria: list[HudCriterion]) -> str | None:
    for criterion in criteria:
        if criterion.verdict.lower() == "unverified" and criterion.commands:
            return criterion.commands[0]
    return None


def _duration(latest_run: dict[str, Any]) -> str:
    started_at = _text(latest_run.get("started_at"), "")
    ended_at = _text(latest_run.get("ended_at"), "") or _text(latest_run.get("last_event_at"), "")
    if not started_at:
        return "unknown"
    if not ended_at:
        return "running"
    started = _parse_utc(started_at)
    ended = _parse_utc(ended_at)
    if started is None or ended is None:
        return "unknown"
    seconds = max(0.0, (ended - started).total_seconds())
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, remaining = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remaining}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _owner_text(value: object) -> str:
    if isinstance(value, list):
        text = ", ".join(str(item).strip() for item in value if str(item).strip())
        return text or "(none)"
    return _text(value, "(none)")


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0
