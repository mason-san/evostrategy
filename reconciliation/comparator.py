"""Pure field-level reconciliation comparators."""

from typing import Optional, Union

from .config import get_tolerance
from .model import ReconciliationResult, ReconciliationStatus


def compare_numeric(
    field: str, left: Optional[Union[int, float]], right: Optional[Union[int, float]]
) -> ReconciliationResult:
    """Compare numeric values using the configured field tolerance."""
    if any(value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))) for value in (left, right)):
        raise TypeError("numeric comparison values must be int, float, or None")
    if left is None or right is None:
        return ReconciliationResult(ReconciliationStatus.MISSING, field, left, right, discrepancy_type="missing_value")
    difference = abs(left - right)
    baseline = abs(right) or abs(left) or 1
    difference_percent = round(difference / baseline * 100, 2)
    tolerance = get_tolerance(field)
    status = (
        ReconciliationStatus.MATCHED if difference_percent == 0
        else ReconciliationStatus.AUTO_RESOLVED if difference_percent <= tolerance
        else ReconciliationStatus.ESCALATED
    )
    discrepancy = None if status == ReconciliationStatus.MATCHED else (
        "rounding_variance" if status == ReconciliationStatus.AUTO_RESOLVED else "amount_mismatch"
    )
    return ReconciliationResult(status, field, left, right, difference, difference_percent, discrepancy)


def compare_exact(field: str, left: Optional[str], right: Optional[str]) -> ReconciliationResult:
    """Compare identifiers or text after trimming and case-folding."""
    if left is None or right is None:
        return ReconciliationResult(ReconciliationStatus.MISSING, field, left, right, discrepancy_type="missing_value")
    if str(left).strip().casefold() == str(right).strip().casefold():
        return ReconciliationResult(ReconciliationStatus.MATCHED, field, left, right)
    return ReconciliationResult(ReconciliationStatus.ESCALATED, field, left, right, discrepancy_type="exact_mismatch")

