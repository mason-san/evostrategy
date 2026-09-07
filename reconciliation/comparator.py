"""
Field-level comparators.

These are the functions your teammate (and eventually Stage 1/2
integration) will call directly. They know nothing about OCR, PDFs,
or how a value was extracted — they just receive two already-mapped
values and decide whether they reconcile.
"""

from typing import Optional, Union

from .config import get_tolerance
from .discrepancy import classify_discrepancy, determine_status
from .model import ReconciliationResult, ReconciliationStatus


def _validate_numeric_value(value: Optional[Union[int, float]], name: str) -> None:
    """Raise a clear error when a comparison value is not numeric."""
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, (int, float))
    ):
        raise TypeError(
            f"{name} must be an int, float, or None; got {type(value).__name__}"
        )


def compare_numeric(
    field: str,
    left: Optional[Union[int, float]],
    right: Optional[Union[int, float]],
) -> ReconciliationResult:
    _validate_numeric_value(left, "left")
    _validate_numeric_value(right, "right")

    if left is None or right is None:
        return ReconciliationResult(
            status=ReconciliationStatus.MISSING,
            field=field,
            left_value=left,
            right_value=right,
            discrepancy_type="missing_value",
        )

    difference = abs(left - right)
    # guard against division by zero when both values could be 0
    base = right if right != 0 else (left if left != 0 else 1)
    # MZN: The percent is calculated from dividing both difference and the base
    # MZN: Then you round it to two points. A float value.
    difference_percent = round((difference / abs(base)) * 100, 2)

    tolerance = get_tolerance(field)
    status = determine_status(difference_percent, tolerance)
    #MZN: discrepancy type is given only if the status is not equal to
    #MZN: whatever the reconciliation status, otherwise you give None.
    discrepancy_type = (
        classify_discrepancy(field, difference_percent, tolerance)
        if status != ReconciliationStatus.MATCHED
        else None
    )

    return ReconciliationResult(
        status=status,
        field=field,
        left_value=left,
        right_value=right,
        difference=difference,
        difference_percent=difference_percent,
        discrepancy_type=discrepancy_type,
    )


def compare_exact(
    field: str,
    left: Optional[str],
    right: Optional[str],
) -> ReconciliationResult:
    if left is None or right is None:
        return ReconciliationResult(
            status=ReconciliationStatus.MISSING,
            field=field,
            left_value=left,
            right_value=right,
            discrepancy_type="missing_value",
        )

    if str(left).strip().lower() == str(right).strip().lower():
        return ReconciliationResult(
            status=ReconciliationStatus.MATCHED,
            field=field,
            left_value=left,
            right_value=right,
        )

    return ReconciliationResult(
        status=ReconciliationStatus.ESCALATED,
        field=field,
        left_value=left,
        right_value=right,
        discrepancy_type="exact_mismatch",
    )


# Convenience wrapper matching the exact examples from the planning doc —
# handy for quick manual checks and for the tests below.
def compare_amounts(
    left: Optional[Union[int, float]],
    right: Optional[Union[int, float]],
) -> ReconciliationResult:
    return compare_numeric("amount", left, right)
