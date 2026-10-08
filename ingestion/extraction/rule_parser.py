"""Deterministic, offline label/value extraction from OCR text.

Used when no LLM provider is configured (or the LLM call fails), so the
pipeline stays runnable on a fully local, no-internet workstation.

Like the LLM parser, this is EXTRACTION, not interpretation: labels and
values are kept exactly as they appear in the OCR text. It returns the same
``{"fields": [...], "tables": [...]}`` contract.
"""

from __future__ import annotations

import re
from typing import Any

# Common business-document labels. Used only to split "value Label:" runs on a
# single OCR line correctly; matched labels are still emitted verbatim.
_KNOWN_LABELS = (
    "invoice number", "invoice no", "invoice date", "invoice", "order id",
    "order number", "po number", "purchase order", "payment id", "payment date",
    "payment reference", "reference", "amount paid", "amount due", "balance due",
    "grand total", "total amount", "subtotal", "total", "discount", "shipping",
    "tax", "gst", "vat", "date", "due date", "bill to", "ship to", "ship mode",
    "vendor", "supplier", "customer", "payer", "payee", "currency", "method",
    "payment method", "notes", "terms", "account", "category", "description",
)
_KNOWN_BY_LENGTH = sorted(_KNOWN_LABELS, key=len, reverse=True)
_LABEL_WORD = re.compile(r"^[A-Z#][\w#().%/-]*$")

KNOWN_LABEL_CONFIDENCE = 0.95
HEURISTIC_LABEL_CONFIDENCE = 0.80
# A known label found at the start of a line whose colon OCR lost ("Date Dec 08 2012").
NO_COLON_LABEL_CONFIDENCE = 0.85

# OCR look-alikes inside label words (only used to *recognise* a label;
# the label is still emitted exactly as printed).
_LABEL_FOLD = str.maketrans({"1": "i", "!": "i", "|": "i", "l": "i", "0": "o"})


def _known_without_colon(line: str) -> tuple[str, str] | None:
    """Split "Order 1D - MX-2012-..." into (label, value) when the label is known."""
    words = line.split()
    for size in (3, 2, 1):
        if len(words) <= size:
            continue
        candidate = " ".join(words[:size])
        folded = candidate.casefold().translate(_LABEL_FOLD).strip(";|>.-")
        known = {label.translate(_LABEL_FOLD) for label in _KNOWN_LABELS}
        if folded in known:
            value = " ".join(words[size:]).lstrip(";|>.-: ").strip()
            if value and not value.casefold().translate(_LABEL_FOLD) in known:
                return candidate.strip(";|>.-"), value
    return None


def _tail_label(segment: str) -> tuple[str, str, bool]:
    """Split ``segment`` into (leading value text, trailing label, known?)."""
    text = segment.rstrip()
    lowered = re.sub(r"\s+", " ", text.casefold())
    for label in _KNOWN_BY_LENGTH:
        # allow suffixes such as "Discount (20%)"
        match = re.search(rf"(?:^|[\s,]){re.escape(label)}(\s*\([^)]*\))?$", lowered)
        if match:
            start = len(text) - (len(lowered) - match.start())
            label_text = text[start:].strip(" ,")
            return text[:start].strip(" ,"), label_text, True
    words = text.split()
    taken: list[str] = []
    for word in reversed(words):
        if word.endswith(",") or not _LABEL_WORD.match(word) or len(taken) == 3:
            break
        taken.insert(0, word)
    if not taken:
        return text, "", False
    label_text = " ".join(taken)
    return text[: len(text) - len(label_text)].strip(" ,"), label_text, False


def _clean_value(value: str) -> str | None:
    value = value.strip(" ,")
    return value or None


def parse_document_rules(text: str) -> dict[str, Any]:
    """Extract label/value fields from OCR text without any network calls."""
    fields: list[dict[str, Any]] = []

    def add(label: str, value: str | None, known: bool) -> None:
        if not label:
            return
        fields.append(
            {
                "field_id": f"field-{len(fields) + 1}",
                "label": label,
                "value": value,
                "confidence": KNOWN_LABEL_CONFIDENCE if known else HEURISTIC_LABEL_CONFIDENCE,
            }
        )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        hash_match = re.match(r"^#\s*(\S+)$", line)
        if hash_match:
            add("#", hash_match.group(1), True)
            continue
        if ":" not in line:
            found = _known_without_colon(line)
            if found:
                fields.append({"field_id": f"field-{len(fields) + 1}", "label": found[0],
                               "value": found[1], "confidence": NO_COLON_LABEL_CONFIDENCE})
            continue
        segments = re.split(r"\s*:\s*", line)
        _, label, known = _tail_label(segments[0])
        for segment in segments[1:-1]:
            value, next_label, next_known = _tail_label(segment)
            add(label, _clean_value(value), known)
            label, known = next_label, next_known
        add(label, _clean_value(segments[-1]), known)

    return {"fields": fields, "tables": []}
