"""Pure dashboard data services for real extraction and reconciliation output."""

import json
from pathlib import Path
from typing import Any

from ingestion.schemas.contracts import SourceDocument, source_document_from_extraction
from ingestion.schemas.invoice_schema import DocumentExtraction
# from ..ingestion.schemas.contracts import SourceDocument, source_document_from_extraction
# from ..ingestion.schemas.invoice_schema import DocumentExtraction
from normalization.mapper import map_document
from reconciliation.engine import reconcile_transactions
from storage.registry import upsert_cases
from utils.config import EXTRACTION_DIR, REGISTRY_DB


def load_extraction_files(directory: Path = EXTRACTION_DIR) -> dict[str, DocumentExtraction]:
    """Load valid extracted JSON documents from a configured directory."""
    documents: dict[str, DocumentExtraction] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text())
        documents[path.name] = DocumentExtraction(**payload)
    return documents


def build_source_document(
    filename: str, extraction: DocumentExtraction
) -> SourceDocument:
    """Adapt one extracted JSON document into the shared source contract."""
    return source_document_from_extraction(filename, filename, extraction)


def reconcile_files(
    left_filename: str,
    right_filename: str,
    documents: dict[str, DocumentExtraction],
    db_path: Path = REGISTRY_DB,
) -> dict[str, Any]:
    """Reconcile two loaded extraction files and persist one dashboard case."""
    left_source = build_source_document(left_filename, documents[left_filename])
    right_source = build_source_document(right_filename, documents[right_filename])
    left_transaction = map_document(left_source)
    right_transaction = map_document(right_source)
    results = reconcile_transactions(left_transaction, right_transaction)
    case_id = f"{left_filename}:{right_filename}"
    overall_status = (
        "ESCALATED"
        if any(result["status"] in {"ESCALATED", "MISSING"} for result in results)
        else "AUTO_RESOLVED"
        if any(result["status"] == "AUTO_RESOLVED" for result in results)
        else "MATCHED"
    )
    case = {
        "case_id": case_id,
        "transaction_id": left_transaction.transaction_id,
        "left_document": left_filename,
        "right_document": right_filename,
        "status": overall_status,
        "mapping": {
            "left": left_transaction.model_dump(),
            "right": right_transaction.model_dump(),
        },
        "results": results,
    }
    upsert_cases([case], db_path)
    return case
