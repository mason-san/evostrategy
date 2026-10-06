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

# Stage 4 forecasting
FORECAST_CONFIDENCE_LEVEL = 0.85
DEFAULT_FORECAST_HORIZON = 6
