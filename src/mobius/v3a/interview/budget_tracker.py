"""Small deterministic budget tracker for v3a interview phases."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetTracker:
    """Track estimated interview spend in USD."""

    usd_spent: float = 0.0

    def record_mock_turn(self) -> float:
        """Record the deterministic mock cost for one 3-agent turn."""
        self.usd_spent = round(self.usd_spent + 0.02, 2)
        return self.usd_spent
