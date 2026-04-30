"""Compatibility re-exports for CLI output writers.

The implementation lives in :mod:`mobius.cli.formatter`; this module remains a
thin adapter for command handlers and tests that still import ``mobius.cli.output``.
"""

from __future__ import annotations

from mobius.cli.formatter import write_error_line, write_json, write_line, write_rich

__all__ = ["write_error_line", "write_json", "write_line", "write_rich"]
