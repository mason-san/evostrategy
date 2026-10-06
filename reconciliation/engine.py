"""Orchestrate canonical transaction comparisons."""

from normalization.mapper import link_documents
from .comparator import compare_exact, compare_numeric


def reconcile_transactions(left, right) -> list[dict]:
    """Return link and field-level results for two canonical transactions."""
    linked, confidence = link_documents(left, right)
    if not linked:
        return [{"field": "document_link", "status": "ESCALATED", "discrepancy_type": "entity_mismatch", "confidence": confidence}]
    results = []
    for field in ("vendor", "identifier", "date"):
        result = compare_exact(field, getattr(left, field), getattr(right, field))
        results.append({**result.as_dict(), "confidence": confidence})
    amount = compare_numeric("amount", left.amount, right.amount)
    results.append({**amount.as_dict(), "confidence": confidence})
    return results

