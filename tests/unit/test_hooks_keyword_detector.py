import ast
import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOOKS = (
    PROJECT_ROOT / "hooks" / "keyword-detector.py",
    PROJECT_ROOT / "hooks" / "drift-monitor.py",
    PROJECT_ROOT / "hooks" / "session-start.py",
)
KEYWORD_DETECTOR = PROJECT_ROOT / "hooks" / "keyword-detector.py"


def run_keyword_detector(envelope: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(KEYWORD_DETECTOR)],
        input=json.dumps(envelope),
        check=False,
        capture_output=True,
        text=True,
    )


def test_hook_scripts_have_python3_shebang_and_parse() -> None:
    for hook in HOOKS:
        text = hook.read_text(encoding="utf-8")

        assert text.splitlines()[0] == "#!/usr/bin/env python3"
        ast.parse(text)


def test_routes_ooo_run_to_mobius_run() -> None:
    result = run_keyword_detector({"prompt": "ooo run"})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"suggestion": "mobius run"}
    assert result.stderr == ""


def test_routes_first_token_after_ooo_only() -> None:
    result = run_keyword_detector({"prompt": "ooo status run-123"})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {"suggestion": "mobius status"}


def test_ignores_non_matching_prompt() -> None:
    result = run_keyword_detector({"prompt": "please ooo run"})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_ignores_missing_or_non_string_prompt() -> None:
    for envelope in ({}, {"prompt": None}, {"prompt": ["ooo", "run"]}):
        result = run_keyword_detector(envelope)

        assert result.returncode == 0
        assert json.loads(result.stdout) == {}


def test_hook_scripts_do_not_reference_forbidden_tooling() -> None:
    forbidden_tokens = ("node", "npm", "require(")

    for hook in HOOKS:
        text = hook.read_text(encoding="utf-8").lower()

        assert all(token not in text for token in forbidden_tokens)
