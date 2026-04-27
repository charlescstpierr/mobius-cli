from pathlib import Path
from typing import Any


def pytest_configure(config: Any) -> None:
    """Keep the standalone chaos suite focused on crash invariants, not total coverage."""
    chaos_dir = Path(__file__).parent.resolve()
    selected_paths = [Path(arg).resolve() for arg in config.args]
    only_chaos_paths = selected_paths and all(
        path == chaos_dir or chaos_dir in path.parents for path in selected_paths
    )
    if only_chaos_paths:
        config.option.cov_fail_under = 0
        cov_plugin = config.pluginmanager.getplugin("_cov")
        if cov_plugin is not None:
            cov_plugin.options.cov_fail_under = 0
