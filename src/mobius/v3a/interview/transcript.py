"""Markdown transcript writing and parsing for v3a interviews."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptTurn:
    """One transcript turn."""

    turn: int
    socrate: str
    because: str
    human: str
    avocat: str
    architecte: tuple[str, ...]


class TranscriptWriter:
    """Append-only markdown transcript writer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("# Mobius v3a interview transcript\n\n", encoding="utf-8")

    def append_turn(self, turn: TranscriptTurn) -> None:
        """Append one turn to the transcript."""
        options = "\n".join(f"- {item}" for item in turn.architecte)
        block = (
            f"## Turn {turn.turn}\n\n"
            f"**Avocat:** {turn.avocat}\n\n"
            f"**Socrate:** {turn.socrate}\n\n"
            f"**because:** {turn.because}\n\n"
            f"**Architecte:**\n{options}\n\n"
            f"**Human:** {turn.human}\n\n"
        )
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(block)


def parse_transcript(text: str) -> list[TranscriptTurn]:
    """Parse transcripts emitted by ``TranscriptWriter``."""
    turns: list[TranscriptTurn] = []
    for block in text.split("## Turn ")[1:]:
        header, _, rest = block.partition("\n")
        try:
            turn_number = int(header.strip())
        except ValueError:
            continue
        turns.append(
            TranscriptTurn(
                turn=turn_number,
                socrate=_field(rest, "**Socrate:**", "**because:**"),
                because=_field(rest, "**because:**", "**Architecte:**"),
                human=_field(rest, "**Human:**", "\n\n"),
                avocat=_field(rest, "**Avocat:**", "**Socrate:**"),
                architecte=tuple(
                    line.removeprefix("- ").strip()
                    for line in _field(rest, "**Architecte:**", "**Human:**").splitlines()
                    if line.strip().startswith("- ")
                ),
            )
        )
    return turns


def _field(text: str, start: str, end: str) -> str:
    _, marker, tail = text.partition(start)
    if not marker:
        return ""
    value, _, _ = tail.partition(end)
    return value.strip()
