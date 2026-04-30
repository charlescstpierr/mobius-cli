"""Lazily imported Typer command handlers.

This package intentionally does not re-export handlers: top-level command
registration uses lazy imports to protect the CLI cold-start budget.
"""
