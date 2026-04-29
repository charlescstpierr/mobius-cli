from __future__ import annotations

from mobius.v3a.interview.socrate import Keystroke, parse_keystroke


def test_universal_interview_keystrokes_are_accepted() -> None:
    assert parse_keystroke(":enough").kind is Keystroke.ENOUGH  # type: ignore[union-attr]
    assert parse_keystroke(":restart").kind is Keystroke.RESTART  # type: ignore[union-attr]
    assert parse_keystroke(":fork").kind is Keystroke.FORK  # type: ignore[union-attr]
    assert parse_keystroke(":why").kind is Keystroke.WHY  # type: ignore[union-attr]
    assert parse_keystroke(":stop").kind is Keystroke.STOP  # type: ignore[union-attr]


def test_back_keystroke_accepts_count() -> None:
    parsed = parse_keystroke(":back 3")

    assert parsed is not None
    assert parsed.kind is Keystroke.BACK
    assert parsed.count == 3


def test_normal_answer_is_not_a_keystroke() -> None:
    assert parse_keystroke("please build a TODO CLI") is None
