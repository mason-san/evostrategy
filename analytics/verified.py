"""The reconciliation gate between Stage 2/3 and Stage 4.

A transaction (a group of linked documents) reaches analytics only when every
case attached to it is settled:

- RECONCILED      all its cases matched or auto-resolved within tolerance
- SINGLE_SOURCE   one high-confidence document, nothing to contradict it
- ACCEPTED        a reviewer accepted every open discrepancy
- CORRECTED       a reviewer corrected a value (the correction is applied)

Excluded:
- PENDING_REVIEW  at least one ESCALATED / MISSING case is still open
- QUARANTINED     a reviewer rejected one of its cases
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage import registry
from utils.config import REGISTRY_DB

VERIFIED_STATUSES = {"RECONCILED", "SINGLE_SOURCE", "ACCEPTED", "CORRECTED"}
OPEN_CASE_STATUSES = {"ESCALATED", "MISSING", "AMBIGUOUS"}


def _corrections(db_path: Path) -> dict[str, dict[str, Any]]:
    """Latest corrected value per (case, field), oldest first so newest wins."""
    corrections: dict[str, dict[str, Any]] = {}
    for action in reversed(registry.get_review_actions(db_path=db_path)):
        if action["action"] == "CORRECT" and action.get("field") and action.get("corrected_value"):
            corrections.setdefault(action["case_id"], {})[action["field"]] = {
                "value": action["corrected_value"],
                "reviewer": action["reviewer"],
                "reason": action["reason"],
                "at": action["created_at"],
            }
    return corrections


def _apply(transaction: dict[str, Any], field: str, value: str) -> None:
    if field == "amount":
        try:
            transaction["amount"] = abs(float(str(value).replace(",", "").replace("$", "")))
        except ValueError:
            return
    elif field in {"date", "category", "counterparty"}:
        transaction[field] = value


def transaction_status(statuses: list[str], corrected: bool) -> str:
    if "REJECTED" in statuses:
        return "QUARANTINED"
    if any(status in OPEN_CASE_STATUSES for status in statuses):
        return "PENDING_REVIEW"
    if corrected or "CORRECTED" in statuses:
        return "CORRECTED"
    if "ACCEPTED" in statuses:
        return "ACCEPTED"
    if statuses:
        return "RECONCILED"
    return "SINGLE_SOURCE"


def load_transactions(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    """Every transaction with its verification status and applied corrections."""
    cases = {case["case_id"]: case for case in registry.get_cases(db_path)}
    corrections = _corrections(db_path)
    transactions = []
    for transaction in registry.get_transactions(db_path):
        transaction = dict(transaction)
        transaction["original_amount"] = transaction.get("amount")
        transaction["original_date"] = transaction.get("date")
        applied = []
        for case_id in transaction.get("case_ids", []):
            for field, correction in corrections.get(case_id, {}).items():
                _apply(transaction, field, correction["value"])
                applied.append({"case_id": case_id, "field": field, **correction})
        statuses = [cases[case_id]["status"] for case_id in transaction.get("case_ids", []) if case_id in cases]
        transaction["corrections"] = applied
        transaction["verification_status"] = transaction_status(statuses, bool(applied))
        transaction["verified"] = transaction["verification_status"] in VERIFIED_STATUSES
        transactions.append(transaction)
    return transactions


def verified_transactions(db_path: Path = REGISTRY_DB) -> list[dict[str, Any]]:
    """Only transactions that passed the gate and have an amount and a date."""
    return [
        transaction
        for transaction in load_transactions(db_path)
        if transaction["verified"] and transaction.get("amount") is not None and transaction.get("date")
    ]
