from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest
from typer.testing import CliRunner

from mobius.workflow.seed import SeedSpec


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def reloaded_command() -> Callable[[str], ModuleType]:
    def _reload(module_name: str) -> ModuleType:
        sys.modules.pop(module_name, None)
        return importlib.import_module(module_name)

    return _reload


@pytest.fixture(autouse=True)
def mock_llm() -> Iterator[None]:
    previous = os.environ.get("MOBIUS_LLM_MODE")
    os.environ["MOBIUS_LLM_MODE"] = "mock"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("MOBIUS_LLM_MODE", None)
        else:
            os.environ["MOBIUS_LLM_MODE"] = previous


@pytest.fixture
def scoring_spec() -> SeedSpec:
    return SeedSpec(
        source_session_id=None,
        project_type="greenfield",
        goal="Ship a deterministic TODO CLI with local storage and clear output.",
        constraints=["Keep state local", "Avoid network services"],
        success_criteria=[
            "Add a TODO item and show it in the list output.",
            "Complete a TODO item and mark it done in the list output.",
            "Empty input returns a helpful validation error.",
        ],
        context="",
        verification_commands=[
            {"command": "uv run pytest -q", "criterion_ref": "1", "timeout_s": 60},
            {"command": "uv run pytest -q", "criterion_ref": "2", "timeout_s": 60},
            {"command": "uv run pytest -q", "criterion_ref": "3", "timeout_s": 60},
        ],
        template="cli",
    )


@pytest.fixture
def spec_factory() -> Callable[[Path], Path]:
    def _write(
        path: Path,
        *,
        matrix_block: str = "",
        body: str | None = None,
    ) -> Path:
        spec_body = body or (
            "goal: trivial fixture goal\n"
            "constraints:\n"
            "  - constraint a\n"
            "success_criteria:\n"
            "  - criterion a\n"
            f"{matrix_block}"
        )
        path.write_text(spec_body, encoding="utf-8")
        return path

    return _write
