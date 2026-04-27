from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_declares_required_jobs_and_actions() -> None:
    workflow = WORKFLOW.read_text()

    assert "uses: actions/setup-python@v5" in workflow
    assert 'python-version: "3.12"' in workflow
    assert "uses: astral-sh/setup-uv@v3" in workflow

    for job_name in ("lint", "test", "build", "bench"):
        assert f"  {job_name}:" in workflow
        assert "runs-on: ubuntu-latest" in workflow


def test_ci_workflow_gates_lint_test_build_and_bench() -> None:
    workflow = WORKFLOW.read_text()

    required_commands = [
        "uv run ruff check src/ tests/",
        "uv run ruff format --check src/ tests/",
        "uv run mypy --strict src/mobius/",
        "uv run pytest -q",
        "uv run pytest tests/chaos/ -q",
        "uv build",
        "uv run python bench/cold_start.py",
        "uv run python bench/status.py",
    ]
    for command in required_commands:
        assert command in workflow

    assert "continue-on-error" not in workflow
    assert "|| true" not in workflow
