"""Central configuration for local EvoStrategy processing."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DOCUMENTS_DIR = PROJECT_ROOT / "data" / "raw"
DEMO_DATA_DIR = PROJECT_ROOT / "data" / "demo"
PROCESSED_DIR = Path(os.environ.get("EVOSTRATEGY_DATA_DIR", PROJECT_ROOT / "data" / "processed"))
IMAGE_DIR = PROCESSED_DIR / "images"
EXTRACTION_DIR = PROCESSED_DIR / "extracted"
UPLOAD_DIR = PROCESSED_DIR / "uploads"
REGISTRY_DB = PROCESSED_DIR / "reconciliation.db"

# Stage 2 reconciliation
DEFAULT_TOLERANCE_PERCENT = 2.0
DATE_TOLERANCE_DAYS = 7

# Stage 1 confidence gate: extractions below this are escalated for review.
LOW_CONFIDENCE_THRESHOLD = 0.85
# Per-field gate for the fields reconciliation relies on (amount, date, reference).
# Tuned with scripts/calibrate_confidence.py (plan week 10): Tesseract word
# confidence is noisy for long codes, and 0.85 sent 31% of *correct* key fields
# to review while 0.60 caught the same wrong values with 8.7% false alarms.
# The sample of wrong values was small (2 of 94), so re-run the calibration on
# real documents before relying on this number.
KEY_FIELD_REVIEW_THRESHOLD = 0.60

# Stage 4 forecasting
FORECAST_CONFIDENCE_LEVEL = 0.85
DEFAULT_FORECAST_HORIZON = 6
