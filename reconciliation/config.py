"""Reconciliation policy configuration."""

from utils.config import DEFAULT_TOLERANCE_PERCENT

TOLERANCE_OVERRIDES: dict[str, float] = {}


def get_tolerance(field: str) -> float:
    """Return the configured tolerance for a field."""
    return TOLERANCE_OVERRIDES.get(field, DEFAULT_TOLERANCE_PERCENT)

