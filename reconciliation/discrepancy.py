"""
Decision rules for reconciliation.

Two small, pure functions — no I/O, nothing about documents — just:
"given this % difference, what status and what kind of discrepancy?"
Kept separate from comparator.py so these rules are easy to unit test
and easy to change later without touching how values get compared.
"""

from .model import ReconciliationStatus


def determine_status(difference_percent: float, tolerance: float) -> ReconciliationStatus:
    """
    difference_percent: absolute % difference between the two values.
    tolerance: the allowed band (e.g. 2.0 for 2%) below which small
    gaps are auto-resolved instead of escalated to a human reviewer.
    """
    if difference_percent == 0:
        return ReconciliationStatus.MATCHED
    if difference_percent <= tolerance:
        return ReconciliationStatus.AUTO_RESOLVED
    return ReconciliationStatus.ESCALATED


def classify_discrepancy(field: str, difference_percent: float, tolerance: float) -> str:
    """
    Only called when there IS a discrepancy (status != MATCHED).
    Gives Stage 3's dashboard something human-readable to show the
    reviewer, beyond just a raw percentage.
    """
    if difference_percent <= tolerance:
        return "rounding_variance"
    if difference_percent > tolerance * 5:
        return "major_amount_mismatch"
    return "amount_mismatch"
