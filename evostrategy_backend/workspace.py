"""Read models for the workspace screens (summary, review queue, records)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from analytics.verified import OPEN_CASE_STATUSES, load_transactions
from storage import registry

_SEVERITY_ORDER = {"ESCALATED": 0, "MISSING": 1, "AMBIGUOUS": 2, "AUTO_RESOLVED": 3,
                   "CORRECTED": 4, "REJECTED": 5, "ACCEPTED": 6, "MATCHED": 7}


def summary() -> dict[str, Any]:
    documents = registry.get_documents()
    cases = registry.get_cases()
    transactions = load_transactions()
    run = registry.get_last_run()
    verified = [t for t in transactions if t["verified"]]
    auto_verified = [t for t in transactions if t["verification_status"] in {"RECONCILED", "SINGLE_SOURCE"}]
    open_cases = [c for c in cases if c["status"] in OPEN_CASE_STATUSES]
    reviewed = [c for c in cases if c["status"] in {"ACCEPTED", "REJECTED", "CORRECTED"}]
    categories = Counter(t.get("category") for t in transactions if t.get("category"))
    doc_types = Counter((run or {}).get("document_types", {}))
    return {
        "has_data": bool(documents),
        "documents": len(documents),
        "source_files": len({d.get("source_name") for d in documents}),
        "fields": sum(len(d.get("fields", [])) for d in documents),
        "transactions": len(transactions),
        "verified_transactions": len(verified),
        "auto_verified_rate": round(len(auto_verified) / len(transactions), 4) if transactions else None,
        "verified_rate": round(len(verified) / len(transactions), 4) if transactions else None,
        "open_cases": len(open_cases),
        "reviewed_cases": len(reviewed),
        "total_cases": len(cases),
        "case_status_counts": dict(Counter(c["status"] for c in cases)),
        "discrepancy_types": dict(Counter(t for c in open_cases for t in c.get("discrepancy_types", []))),
        "document_types": dict(doc_types),
        "categories": [name for name, _ in categories.most_common(12)],
        "low_confidence_documents": sum(1 for d in documents if d.get("low_confidence")),
        "extraction_methods": dict(Counter(_method(d.get("extraction_method")) for d in documents)),
        "last_run_at": (run or {}).get("created_at"),
    }


def _method(value: str | None) -> str:
    if not value:
        return "unknown"
    return value.split(" ")[0]


def list_cases(status: str | None = None) -> list[dict[str, Any]]:
    cases = registry.get_cases()
    if status == "open":
        cases = [c for c in cases if c["status"] in OPEN_CASE_STATUSES]
    elif status == "reviewed":
        cases = [c for c in cases if c["status"] in {"ACCEPTED", "REJECTED", "CORRECTED"}]
    elif status:
        cases = [c for c in cases if c["status"] == status.upper()]
    cases.sort(key=lambda c: (_SEVERITY_ORDER.get(c["status"], 9), c["case_id"]))
    return [
        {
            "case_id": c["case_id"],
            "case_type": c.get("case_type"),
            "status": c["status"],
            "computed_status": c.get("computed_status"),
            "relationship": c.get("relationship"),
            "discrepancy_types": c.get("discrepancy_types", []),
            "explanation": c.get("explanation"),
            "transaction_id": c.get("transaction_id"),
            "documents": [
                {key: d.get(key) for key in ("document_id", "source_name", "document_type", "amount", "date")}
                for d in c.get("documents", [])
            ],
            "updated_at": c.get("updated_at"),
        }
        for c in cases
    ]


def _document_view(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": document["document_id"],
        "source_name": document.get("source_name"),
        "source_row": document.get("source_row"),
        "extraction_method": document.get("extraction_method"),
        "extraction_confidence": document.get("extraction_confidence"),
        "ocr_confidence": document.get("ocr_confidence"),
        "low_confidence": document.get("low_confidence"),
        "page_count": len(document.get("page_images") or []),
        "fields": [
            {key: field.get(key) for key in ("field_id", "label", "value", "confidence")}
            for field in document.get("fields", [])
        ],
        "tables": document.get("tables", []),
    }


def case_detail(case_id: str) -> dict[str, Any] | None:
    case = registry.get_case(case_id)
    if not case:
        return None
    documents = []
    for facts in case.get("documents", []):
        stored = registry.get_document(facts["document_id"])
        documents.append({"facts": facts, "source": _document_view(stored) if stored else None})
    return {
        **{key: value for key, value in case.items() if key != "documents"},
        "documents": documents,
        "history": registry.get_review_actions(case_id),
        "allowed_actions": ["ACCEPT", "REJECT", "CORRECT"],
    }


def list_documents() -> list[dict[str, Any]]:
    transactions = load_transactions()
    by_document = {doc_id: t for t in transactions for doc_id in t.get("document_ids", [])}
    rows = []
    for document in registry.get_documents():
        transaction = by_document.get(document["document_id"], {})
        rows.append({
            "document_id": document["document_id"],
            "source_name": document.get("source_name"),
            "source_row": document.get("source_row"),
            "extraction_method": _method(document.get("extraction_method")),
            "extraction_confidence": document.get("extraction_confidence"),
            "low_confidence": document.get("low_confidence"),
            "field_count": len(document.get("fields", [])),
            "transaction_id": transaction.get("transaction_id"),
            "document_types": transaction.get("document_types"),
            "kind": transaction.get("kind"),
            "category": transaction.get("category"),
            "amount": transaction.get("amount"),
            "date": transaction.get("date"),
            "verification_status": transaction.get("verification_status"),
        })
    return rows


def document_detail(document_id: str) -> dict[str, Any] | None:
    document = registry.get_document(document_id)
    if not document:
        return None
    transaction = next(
        (t for t in load_transactions() if document_id in t.get("document_ids", [])), None
    )
    cases = [registry.get_case(case_id) for case_id in (transaction or {}).get("case_ids", [])]
    return {
        **_document_view(document),
        "ocr_text": document.get("ocr_text"),
        "transaction": transaction,
        "cases": [
            {"case_id": c["case_id"], "status": c["status"], "explanation": c.get("explanation")}
            for c in cases if c
        ],
    }
