"""Human-review efficiency (implementation plan hypothesis: >= 60% less manual effort).

What "manual effort" means here
- Fully manual baseline: a finance reviewer cross-checks every document that
  needs reconciling (each invoice, payment and referenced ledger posting) by
  finding its counterpart and comparing amount, date and reference.
- With EvoStrategy: the reviewer only opens the documents that sit in an open
  case (escalated or missing). Everything matched or auto-resolved within
  tolerance needs no human look.

reduction = 1 - documents_in_open_cases / documents_needing_reconciliation

Two caveats are reported with the number, not hidden:
- It counts documents, not minutes. A timed study with real reviewers (plan,
  week 22) would give the stronger evidence.
- Ledger rows with no reference to any invoice (payroll, rent...) are left out
  of the baseline, because nobody would reconcile them against invoices by
  hand either; counting them would inflate the result.
"""

from __future__ import annotations

from typing import Any

OPEN = {"ESCALATED", "MISSING", "AMBIGUOUS"}
TARGET = 0.60


def review_efficiency(cases: list[dict[str, Any]], transactions: list[dict[str, Any]]) -> dict[str, Any]:
    in_cases = {doc_id for case in cases for doc_id in case.get("document_ids", [])}
    needing = set()
    for transaction in transactions:
        doc_types = set(transaction.get("document_types", []))
        ids = transaction.get("document_ids", [])
        if doc_types & {"INVOICE", "PAYMENT", "PURCHASE_ORDER"} or len(ids) > 1:
            needing.update(ids)
    needing |= in_cases
    open_docs = {doc_id for case in cases if case.get("status") in OPEN for doc_id in case.get("document_ids", [])}
    reviewed_docs = {doc_id for case in cases if case.get("status") in {"ACCEPTED", "REJECTED", "CORRECTED"}
                     for doc_id in case.get("document_ids", [])}
    human = open_docs | reviewed_docs
    total = len(needing)
    reduction = 1 - len(human) / total if total else None
    return {
        "documents_needing_reconciliation": total,
        "documents_needing_a_human": len(human),
        "documents_cleared_automatically": total - len(human),
        "open_cases": sum(1 for c in cases if c.get("status") in OPEN),
        "reduction": round(reduction, 4) if reduction is not None else None,
        "target": TARGET,
        "meets_target": reduction is not None and reduction >= TARGET,
        "method": "documents a reviewer must open vs. a fully manual cross-check of every reconcilable document",
        "caveat": "Counts documents, not reviewer minutes; a timed user study would be stronger evidence.",
    }
