"""Map generic extraction fields to comparison-ready transaction values."""

import re
from typing import Any

from ingestion.schemas.contracts import CanonicalTransaction, SourceDocument

_ALIASES = {
    "vendor": {"vendor", "supplier", "seller", "from", "company"},
    "identifier": {
        "invoice",
        "invoice number",
        "invoice no",
        "order id",
        "reference",
        "id",
    },
    "date": {"date", "invoice date", "transaction date"},
    "amount": {"total", "total amount", "amount", "balance due", "net total"},
    "currency": {"currency", "currency code"},
}


def _label_key(label: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", label.lower()).strip()


_NORMALIZED_ALIASES = {
    concept: {_label_key(alias) for alias in aliases}
    for concept, aliases in _ALIASES.items()
}


def _value_for(document: SourceDocument, concept: str) -> tuple[Any, str | None]:
    for field in document.fields:
        if (
            _label_key(field.label) in _NORMALIZED_ALIASES[concept]
            and field.value is not None
        ):
            return field.value, field.field_id
    return None, None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(value))
    return float(match.group(0).replace(",", "")) if match else None


def map_document(document: SourceDocument) -> CanonicalTransaction:
    """Create a canonical view without changing the source extraction."""
    values: dict[str, Any] = {}
    field_ids: dict[str, str] = {}
    raw_values: dict[str, Any] = {}
    for concept in _NORMALIZED_ALIASES:
        value, field_id = _value_for(document, concept)
        values[concept] = _number(value) if concept == "amount" else value
        if field_id:
            field_ids[concept] = field_id
            raw_values[concept] = value
    return CanonicalTransaction(
        transaction_id=document.document_id,
        document_id=document.document_id,
        raw_field_ids=field_ids,
        raw_values=raw_values,
        mapping_confidence=len(field_ids) / len(_NORMALIZED_ALIASES),
        **values,
    )


def link_documents(
    left: CanonicalTransaction, right: CanonicalTransaction
) -> tuple[bool, float]:
    """Link two records using identifiers, vendor, date, and amount evidence."""
    if left.identifier and right.identifier and left.identifier.lower() == right.identifier.lower():
        return True, 1.0
    score = 0.0
    if left.vendor and right.vendor and left.vendor.lower() == right.vendor.lower():
        score += 0.45
    if left.date and right.date and left.date == right.date:
        score += 0.3
    if left.amount is not None and right.amount is not None:
        score += 0.25 if abs(left.amount - right.amount) <= max(left.amount, right.amount, 1) * 0.02 else 0
    return score >= 0.7, round(score, 2)
