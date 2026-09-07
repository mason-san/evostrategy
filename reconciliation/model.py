"""
Data shapes for the reconciliation engine.

Everything downstream (comparator, discrepancy, reconcile) returns a
ReconciliationResult — defining this first means every other file has
a fixed contract to write against.
"""

from dataclasses import dataclass, field as dc_field
from enum import Enum
from typing import Optional, Union

#The four possible outcomes for a given set of documents
class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    AUTO_RESOLVED = "AUTO_RESOLVED"
    ESCALATED = "ESCALATED"
    MISSING = "MISSING"


@dataclass
class ReconciliationResult:
    status: ReconciliationStatus
    field: str
    left_value: Optional[Union[str, float]] = None
    right_value: Optional[Union[str, float]] = None
    difference: Optional[float] = None
    difference_percent: Optional[float] = None
    discrepancy_type: Optional[str] = None

    def as_dict(self) -> dict:
        """Handy for logging / feeding into Stage 3's audit log later."""
        return {
            "status": self.status.value,
            "field": self.field,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "difference": self.difference,
            "difference_percent": self.difference_percent,
            "discrepancy_type": self.discrepancy_type,
        }


