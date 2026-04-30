"""Matrix-aware scoring and diff for the F10 anti-regression CI guardrail.

The package initializer intentionally avoids re-exports so matrix modules stay
lazy-imported by the CLI and keep cold-start overhead local to v3a commands.
"""
