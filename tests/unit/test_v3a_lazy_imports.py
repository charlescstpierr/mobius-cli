from __future__ import annotations

import ast
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given, settings
from hypothesis import strategies as st

from mobius.v3a.interview.transcript import TranscriptTurn, TranscriptWriter, parse_transcript

REPO_ROOT = Path(__file__).resolve().parents[2]
V3A_ROOT = REPO_ROOT / "src" / "mobius" / "v3a"
BANNED_TOP_LEVEL_IMPORTS = {"subprocess", "sqlite3", "rich.live"}


def test_v3a_modules_do_not_import_banned_modules_at_top_level() -> None:
    violations: list[str] = []
    for path in sorted(V3A_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            imported = _top_level_imports(node)
            banned = sorted(imported & BANNED_TOP_LEVEL_IMPORTS)
            if banned:
                relative = path.relative_to(REPO_ROOT)
                violations.append(f"{relative}: {', '.join(banned)}")

    assert violations == []


def _top_level_imports(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if isinstance(node, ast.ImportFrom) and node.module is not None:
        return {node.module}
    return set()


safe_text = st.text(
    alphabet=st.sampled_from(
        list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ 0123456789.,;:!?-_")
    ),
    min_size=0,
    max_size=80,
)


@settings(max_examples=200, deadline=None)
@given(
    turns=st.lists(
        st.fixed_dictionaries(
            {
                "socrate": safe_text,
                "because": safe_text,
                "human": safe_text,
                "avocat": safe_text,
                "architecte": st.lists(safe_text, min_size=0, max_size=3),
            }
        ),
        min_size=0,
        max_size=12,
    )
)
def test_transcript_parser_fuzzes_writer_output(turns: list[dict[str, object]]) -> None:
    with TemporaryDirectory() as directory:
        writer = TranscriptWriter(Path(directory) / "transcript.md")
        _assert_transcript_round_trip(writer, turns)


def _assert_transcript_round_trip(writer: TranscriptWriter, turns: list[dict[str, object]]) -> None:
    expected: list[TranscriptTurn] = []
    for index, raw_turn in enumerate(turns, start=1):
        turn = TranscriptTurn(
            turn=index,
            socrate=str(raw_turn["socrate"]),
            because=str(raw_turn["because"]),
            human=str(raw_turn["human"]),
            avocat=str(raw_turn["avocat"]),
            architecte=tuple(str(item) for item in raw_turn["architecte"]),
        )
        expected.append(turn)
        writer.append_turn(turn)

    parsed = parse_transcript(writer.path.read_text(encoding="utf-8"))

    assert [turn.turn for turn in parsed] == [turn.turn for turn in expected]
    assert len(parsed) == len(expected)
