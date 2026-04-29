from __future__ import annotations

import time
from pathlib import Path

from mobius.v3a.maturity.scorer import score_spec


def test_maturity_calc_under_300ms_on_50_criterion_spec(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.yaml"
    lines = [
        "spec_version: 2",
        "project_type: greenfield",
        "goal: Ship a broad deterministic CLI.",
        "constraints:",
        "  - deterministic command behavior",
        "success_criteria:",
    ]
    for index in range(1, 51):
        lines.append(f"  - Edge case criterion {index}: invalid input path reports error {index}.")
    lines.append("verification_commands:")
    for index in range(1, 51):
        lines.extend(
            [
                "  - command: uv run pytest -q",
                f"    criterion_ref: {index}",
                "    timeout_s: 60",
                "    shell: true",
            ]
        )
    spec_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    started = time.perf_counter()
    report = score_spec(spec_path)
    elapsed = time.perf_counter() - started

    assert report.score >= 0.8
    assert elapsed < 0.300
