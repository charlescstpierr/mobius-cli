import os
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_uv_build_wheel_metadata_and_fresh_venv_smoke(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    build = subprocess.run(
        ["uv", "build", "--out-dir", str(dist_dir)],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert build.returncode == 0, build.stderr
    wheels = sorted(dist_dir.glob("mobius-*.whl"))
    sdists = sorted(dist_dir.glob("mobius-*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1

    with zipfile.ZipFile(wheels[0]) as wheel:
        metadata_names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        assert len(metadata_names) == 1
        metadata = wheel.read(metadata_names[0]).decode("utf-8")

    requires_dist = [
        line.removeprefix("Requires-Dist:").strip().lower()
        for line in metadata.splitlines()
        if line.lower().startswith("requires-dist:")
    ]
    assert all(not requirement.startswith("mcp") for requirement in requires_dist)

    smoke_venv = tmp_path / "smoke-venv"
    venv = subprocess.run(
        [sys.executable, "-m", "venv", str(smoke_venv)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert venv.returncode == 0, venv.stderr

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    pip = smoke_venv / bin_dir / "pip"
    mobius = smoke_venv / bin_dir / "mobius"

    install = subprocess.run(
        [str(pip), "install", str(wheels[0])],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert install.returncode == 0, install.stderr

    help_result = subprocess.run(
        [str(mobius), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "MOBIUS_HOME": str(tmp_path / "mobius-home"), "NO_COLOR": "1"},
    )
    assert help_result.returncode == 0
    assert "Usage:" in help_result.stdout
    assert "interview" in help_result.stdout
    assert help_result.stderr == ""
