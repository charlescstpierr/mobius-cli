import subprocess
from collections.abc import Sequence
from pathlib import Path

from mobius.persistence.event_store import EventStore
from mobius.workflow import smoke


def test_run_smoke_executes_full_pipeline_and_cleans_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    workspace = tmp_path / "mobius-smoke-fixed"
    store_path = workspace / ".mobius" / "events.db"

    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fixed"})())

    def fake_run_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> smoke._CommandResult:
        commands.append(list(command))
        assert env["MOBIUS_HOME"] == str(workspace / ".mobius")
        assert env["MOBIUS_SMOKE_OFFLINE"] == "1"
        if command[1] == "init":
            workspace.mkdir(parents=True, exist_ok=True)
        if command[1] == "run":
            with EventStore(store_path) as store:
                store.create_session("run_smoke", runtime="run", status="completed")
        return smoke._CommandResult(exit_code=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(smoke, "_run_command", fake_run_command)

    report = smoke.run_smoke()

    assert report.passed is True
    assert report.run_id == "run_smoke"
    assert [step.name for step in report.steps] == [
        "init",
        "interview",
        "seed",
        "run",
        "status",
        "qa",
    ]
    assert [cmd[1:3] for cmd in commands] == [
        ["init", "--template"],
        ["interview", "--non-interactive"],
        ["seed", str(workspace / "spec.yaml")],
        ["run", "--foreground"],
        ["status", "run_smoke"],
        ["qa", "run_smoke"],
    ]
    assert not workspace.exists()


def test_run_smoke_reports_failed_step_and_skips_remaining(
    tmp_path: Path,
    monkeypatch,
) -> None:
    commands: list[list[str]] = []
    workspace = tmp_path / "mobius-smoke-fixed"

    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fixed"})())

    def fake_run_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> smoke._CommandResult:
        commands.append(list(command))
        if command[1] == "init":
            workspace.mkdir(parents=True, exist_ok=True)
            return smoke._CommandResult(exit_code=0, stdout="ok\n", stderr="")
        return smoke._CommandResult(exit_code=3, stdout="", stderr="bad spec\n")

    monkeypatch.setattr(smoke, "_run_command", fake_run_command)

    report = smoke.run_smoke()

    assert report.passed is False
    assert [step.name for step in report.steps] == ["init", "interview"]
    assert report.steps[-1].exit_code == 3
    assert report.steps[-1].detail == "bad spec"
    assert len(commands) == 2


def test_run_smoke_records_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fixed"})())

    def timeout_run_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> smoke._CommandResult:
        raise subprocess.TimeoutExpired(cmd=list(command), timeout=8)

    monkeypatch.setattr(smoke, "_run_command", timeout_run_command)

    report = smoke.run_smoke()

    assert report.passed is False
    assert report.steps[0].name == "init"
    assert report.steps[0].exit_code == 124
    assert "timed out" in report.steps[0].detail


def test_run_smoke_reports_missing_run_id_and_keeps_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "mobius-smoke-fixed"

    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fixed"})())

    def fake_run_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> smoke._CommandResult:
        if command[1] == "init":
            workspace.mkdir(parents=True, exist_ok=True)
        return smoke._CommandResult(exit_code=0, stdout="", stderr="ok\n")

    monkeypatch.setattr(smoke, "_run_command", fake_run_command)

    report = smoke.run_smoke(keep_workspace=True)

    assert report.passed is False
    assert workspace.exists()
    assert report.steps[-1].name == "resolve_run_id"
    assert report.steps[-1].detail == "no run session found"


def test_run_smoke_records_duration_budget_failure(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "mobius-smoke-fixed"
    store_path = workspace / ".mobius" / "events.db"
    ticks = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 11.0])

    monkeypatch.setattr(smoke.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(smoke.uuid, "uuid4", lambda: type("Uuid", (), {"hex": "fixed"})())
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks, 11.0))

    def fake_run_command(
        command: Sequence[str],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> smoke._CommandResult:
        if command[1] == "init":
            workspace.mkdir(parents=True, exist_ok=True)
        if command[1] == "run":
            with EventStore(store_path) as store:
                store.create_session("run_smoke", runtime="run", status="completed")
        return smoke._CommandResult(exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(smoke, "_run_command", fake_run_command)

    report = smoke.run_smoke()

    assert report.passed is False
    assert report.steps[-1].name == "duration"
    assert "smoke exceeded 10s budget" in report.steps[-1].detail


def test_smoke_detail_prefers_combined_failure_context() -> None:
    result = smoke._CommandResult(exit_code=2, stdout="first\nlast out\n", stderr="bad\nlast err\n")

    assert smoke._detail(result) == "last err; stdout=last out"
    assert smoke._detail(smoke._CommandResult(exit_code=0, stdout="", stderr="ok\n")) == "ok"
