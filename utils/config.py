"""Central configuration for local EvoStrategy processing."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DOCUMENTS_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
IMAGE_DIR = PROCESSED_DIR / "images"
EXTRACTION_DIR = PROCESSED_DIR / "extracted"
REGISTRY_DB = PROCESSED_DIR / "reconciliation.db"

DEFAULT_TOLERANCE_PERCENT = 2.0

