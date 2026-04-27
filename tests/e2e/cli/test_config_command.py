import json
import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def run_mobius(*args: str, mobius_home: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "mobius", *args],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "MOBIUS_HOME": str(mobius_home), "NO_COLOR": "1"},
    )


def test_config_show_auto_creates_state_dir_and_event_store_with_restricted_modes(
    tmp_path: Path,
) -> None:
    mobius_home = tmp_path / "mobius-home"

    result = run_mobius("config", "show", "--json", mobius_home=mobius_home)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["state_dir"] == str(mobius_home)
    assert payload["event_store"] == str(mobius_home / "events.db")
    assert payload["busy_timeout"] == 30_000
    assert (mobius_home.stat().st_mode & 0o777) == 0o700
    assert ((mobius_home / "events.db").stat().st_mode & 0o777) == 0o600
    assert result.stderr == ""


def test_config_set_is_idempotent_and_persists_across_invocations(tmp_path: Path) -> None:
    mobius_home = tmp_path / "mobius-home"

    first = run_mobius("config", "set", "log_level", "info", mobius_home=mobius_home)
    second = run_mobius("config", "set", "log_level", "info", mobius_home=mobius_home)
    get = run_mobius("config", "get", "log_level", mobius_home=mobius_home)

    assert first.returncode == 0
    assert second.returncode == 0
    assert get.returncode == 0
    assert first.stdout == "log_level=info\n"
    assert second.stdout == "log_level=info\n"
    assert get.stdout == "info\n"
    assert first.stderr == second.stderr == get.stderr == ""


def test_config_global_json_flag_yields_valid_json(tmp_path: Path) -> None:
    result = run_mobius("--json", "config", "set", "profile", "prod", mobius_home=tmp_path)

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"key": "profile", "value": "prod"}
    assert result.stderr == ""


def test_config_get_unknown_key_exits_not_found(tmp_path: Path) -> None:
    result = run_mobius("config", "get", "missing", mobius_home=tmp_path)

    assert result.returncode == 4
    assert result.stdout == ""
    assert "not found" in result.stderr
