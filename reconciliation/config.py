"""
Tolerance configuration.

Kept separate from comparator.py so the % threshold can be tuned
(e.g. during Month 3 ground-truth validation) without touching the
comparison logic itself.
"""

# Project spec default: 2% tolerance band before a numeric mismatch escalates.
DEFAULT_TOLERANCE_PERCENT = 2.0

# Per-field overrides, if some fields need a tighter or looser band.
# Example: GST figures might warrant a tighter tolerance than freight charges.
TOLERANCE_OVERRIDES = {
    # "gst": 0.5,
}

def get_tolerance(field: str) -> float:
    #return the field tolerence value if it exists, otherwise just return that 2%
    return TOLERANCE_OVERRIDES.get(field, DEFAULT_TOLERANCE_PERCENT)
