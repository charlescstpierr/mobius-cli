import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def read_doc(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_readme_quickstart_has_install_and_three_runnable_blocks() -> None:
    readme = read_doc("README.md")
    bash_blocks = re.findall(r"```bash\n(.*?)\n```", readme, flags=re.DOTALL)

    assert len(bash_blocks) >= 3
    assert "uv tool install . --force" in bash_blocks[0]
    assert "mobius --help" in bash_blocks[1]
    assert "mobius interview --non-interactive" in bash_blocks[2]
    assert "mobius seed /tmp/mobius-spec.yaml --json" in bash_blocks[2]
    assert "mobius run --spec /tmp/mobius-spec.yaml" in bash_blocks[2]
    assert 'mobius status "$run_id" --follow' in bash_blocks[2]


def test_cli_reference_lists_every_public_command_flag_and_exit_code() -> None:
    cli_reference = read_doc("docs/cli-reference.md")
    expected_tokens = [
        "## Global options",
        "`--json`",
        "`--version`",
        "`-h`, `--help`",
        "### `mobius interview`",
        "`--non-interactive`",
        "`--input FILE`",
        "`--output FILE`",
        "### `mobius seed`",
        "`SPEC_OR_SESSION_ID`",
        "### `mobius run`",
        "`--spec FILE`",
        "`--detach`",
        "`--foreground`",
        "### `mobius status`",
        "`--read-only`",
        "`--follow`",
        "### `mobius ac-tree`",
        "`--cursor INTEGER`",
        "`--max-nodes INTEGER`",
        "### `mobius qa`",
        "`--offline`",
        "### `mobius cancel`",
        "`--grace-period FLOAT`",
        "### `mobius evolve`",
        "`--from TEXT`",
        "`--generations INTEGER`",
        "### `mobius lineage`",
        "`--hash`",
        "`--aggregate TEXT`",
        "### `mobius setup`",
        "`--runtime TEXT`",
        "`--scope TEXT`",
        "`--dry-run`",
        "`--uninstall`",
        "### `mobius config`",
        "#### `mobius config show`",
        "#### `mobius config get`",
        "#### `mobius config set`",
    ]
    for token in expected_tokens:
        assert token in cli_reference

    for code in ("`0`", "`1`", "`2`", "`3`", "`4`", "`130`"):
        assert code in cli_reference


def test_migration_doc_maps_all_known_ouroboros_mcp_tools() -> None:
    migration = read_doc("docs/migration-from-ouroboros.md")
    tool_names = [
        "ouroboros_execute_seed",
        "ouroboros_start_execute_seed",
        "ouroboros_session_status",
        "ouroboros_job_status",
        "ouroboros_job_wait",
        "ouroboros_job_result",
        "ouroboros_cancel_job",
        "ouroboros_cancel_execution",
        "ouroboros_query_events",
        "ouroboros_generate_seed",
        "ouroboros_interview",
        "ouroboros_pm_interview",
        "ouroboros_brownfield",
        "ouroboros_measure_drift",
        "ouroboros_evaluate",
        "ouroboros_checklist_verify",
        "ouroboros_lateral_think",
        "ouroboros_evolve_step",
        "ouroboros_start_evolve_step",
        "ouroboros_lineage_status",
        "ouroboros_evolve_rewind",
        "ouroboros_ac_dashboard",
        "ouroboros_ac_tree_hud",
        "ouroboros_qa",
    ]

    for tool_name in tool_names:
        assert tool_name in migration

    assert migration.count("| `ouroboros_") >= len(tool_names)
    assert "mobius setup --runtime claude|codex|hermes" in migration


def test_architecture_doc_covers_release_invariants() -> None:
    architecture = read_doc("docs/architecture.md")
    for token in [
        "Lazy import strategy",
        "Detached worker pattern",
        "Event store schema",
        "PRAGMA journal_mode=WAL",
        "PRAGMA busy_timeout=30000",
        "events",
        "sessions",
        "aggregates",
        "schema_migrations",
        "never registers an MCP server",
    ]:
        assert token in architecture
