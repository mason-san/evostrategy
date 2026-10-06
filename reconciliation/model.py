"""Typed reconciliation result contracts."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Union


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    ESCALATED = "ESCALATED"
    MISSING = "MISSING"


@dataclass
class ReconciliationResult:
    """Result of comparing one canonical field."""

    status: ReconciliationStatus
    field: str
    left_value: Optional[Union[str, float]] = None
    right_value: Optional[Union[str, float]] = None
    difference: Optional[float] = None
    difference_percent: Optional[float] = None
    discrepancy_type: Optional[str] = None

    def as_dict(self) -> dict:
        """Return a JSON-compatible representation."""
        return {
            "status": self.status.value,
            "field": self.field,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "difference": self.difference,
            "difference_percent": self.difference_percent,
            "discrepancy_type": self.discrepancy_type,
        }
