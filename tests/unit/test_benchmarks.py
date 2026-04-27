import importlib.util
from pathlib import Path
from types import ModuleType

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cold_start_benchmark_computes_nearest_rank_percentiles_and_passes() -> None:
    cold_start = load_module("bench_cold_start", PROJECT_ROOT / "bench" / "cold_start.py")
    samples = [0.050] * 47 + [0.100, 0.120, 0.149]

    assert cold_start.percentile(samples, 50) == 0.050
    assert cold_start.percentile(samples, 95) == 0.100
    assert cold_start.percentile(samples, 99) == 0.149


def test_cold_start_force_fail_env_returns_nonzero(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    cold_start = load_module("bench_cold_start_force", PROJECT_ROOT / "bench" / "cold_start.py")

    def fake_measure_once(command, env, *, force_fail):  # type: ignore[no-untyped-def]
        assert command == cold_start.COMMAND
        return cold_start.THRESHOLD_SECONDS + 0.010 if force_fail else 0.010

    monkeypatch.setattr(cold_start, "measure_once", fake_measure_once)

    samples, exit_code = cold_start.run_benchmark(
        iterations=50,
        env={cold_start.FORCE_FAIL_ENV: "1"},
    )

    assert len(samples) == 50
    assert cold_start.percentile(samples, 95) > cold_start.THRESHOLD_SECONDS
    assert exit_code == 1


def test_status_benchmark_creates_fixture_and_passes(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    status = load_module("bench_status", PROJECT_ROOT / "bench" / "status.py")
    commands: list[tuple[str, ...]] = []

    def fake_measure_once(command, env, *, force_fail):  # type: ignore[no-untyped-def]
        assert force_fail is False
        assert env["MOBIUS_HOME"] == str(tmp_path)
        commands.append(tuple(command))
        return 0.010

    monkeypatch.setattr(status, "measure_once", fake_measure_once)

    samples, exit_code = status.run_benchmark(iterations=50, env={}, mobius_home=tmp_path)

    assert len(samples) == 50
    assert exit_code == 0
    assert commands == [("mobius", "status", status.FIXTURE_RUN_ID)] * 50
    assert (tmp_path / "events.db").exists()


def test_status_force_fail_env_returns_nonzero(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    status = load_module("bench_status_force", PROJECT_ROOT / "bench" / "status.py")

    def fake_measure_once(command, env, *, force_fail):  # type: ignore[no-untyped-def]
        assert command == ("mobius", "status", status.FIXTURE_RUN_ID)
        return status.THRESHOLD_SECONDS + 0.010 if force_fail else 0.010

    monkeypatch.setattr(status, "measure_once", fake_measure_once)

    samples, exit_code = status.run_benchmark(
        iterations=50,
        env={status.FORCE_FAIL_ENV: "1"},
        mobius_home=tmp_path,
    )

    assert len(samples) == 50
    assert status.percentile(samples, 95) > status.THRESHOLD_SECONDS
    assert exit_code == 1
