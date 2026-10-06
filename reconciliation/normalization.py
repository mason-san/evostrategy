"""Conservative, source-preserving normalization of semantically mapped fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from reconciliation.semantic_mapping import (
    DocumentType,
    MappedDocument,
    MappedField,
    SemanticRole,
    SemanticType,
)


class NormalizationStatus(StrEnum):
    """Outcome of normalizing a source value."""

    SUCCESS = "success"
    MISSING = "missing"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


class NormalizationMethod(StrEnum):
    """Deterministic parser used for a normalized value."""

    AMOUNT = "currency_numeric"
    DATE = "iso_date"
    ENTITY = "entity_comparison"
    IDENTIFIER = "identifier_comparison"
    QUANTITY = "numeric"
    UNIT_PRICE = "currency_numeric"
    CURRENCY = "currency_code"
    TEXT = "text_comparison"
    NONE = "none"


@dataclass(frozen=True)
class NormalizationResult:
    """Normalized value plus an auditable status and method."""

    normalized_value: Any
    normalization_method: NormalizationMethod
    normalization_status: NormalizationStatus
    currency: str | None = None


class NormalizedField:
    """A normalized view that retains all semantic and raw provenance."""

    def __init__(
        self,
        *,
        field_id: str,
        source_document_id: str,
        raw_label: str,
        raw_value: Any,
        semantic_type: SemanticType | None,
        semantic_role: SemanticRole | None,
        normalized_value: Any,
        normalization_method: NormalizationMethod,
        normalization_status: NormalizationStatus,
        currency: str | None = None,
    ) -> None:
        self.field_id = field_id
        self.source_document_id = source_document_id
        self.raw_label = raw_label
        self.raw_value = raw_value
        self.semantic_type = semantic_type
        self.semantic_role = semantic_role
        self.normalized_value = normalized_value
        self.normalization_method = normalization_method
        self.normalization_status = normalization_status
        self.currency = currency

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible normalized audit record."""
        return {
            "field_id": self.field_id,
            "source_document_id": self.source_document_id,
            "raw_label": self.raw_label,
            "raw_value": self.raw_value,
            "semantic_type": (
                self.semantic_type.value if self.semantic_type is not None else None
            ),
            "semantic_role": (
                self.semantic_role.value if self.semantic_role is not None else None
            ),
            "normalized_value": self.normalized_value,
            "normalization_method": self.normalization_method.value,
            "normalization_status": self.normalization_status.value,
            "currency": self.currency,
        }


class NormalizedDocument:
    """Normalized view of every mapped field in a document."""

    def __init__(
        self,
        *,
        document_id: str,
        document_type: DocumentType,
        fields: list[NormalizedField],
    ) -> None:
        self.document_id = document_id
        self.document_type = document_type
        self.fields = fields

    def model_dump(self) -> dict[str, Any]:
        """Return the normalized document without removing mapped fields."""
        return {
            "document_id": self.document_id,
            "document_type": (
                self.document_type.value
                if hasattr(self.document_type, "value")
                else self.document_type
            ),
            "fields": [field.model_dump() for field in self.fields],
        }


_MISSING = {"", "-", "n/a", "na", "none", "null", "unknown"}
_CURRENCY_CODES = {
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "inr": "INR",
    "indian rupee": "INR",
    "indian rupees": "INR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "gbp": "GBP",
    "pound": "GBP",
    "pounds": "GBP",
}
_CURRENCY_SYMBOLS = {"₹": "INR", "€": "EUR", "£": "GBP"}
_CURRENCY_CODE_PATTERN = re.compile(r"\b(usd|inr|eur|gbp)\b", re.IGNORECASE)
_NUMBER_PATTERN = re.compile(r"[-+]?\d[\d\s,.]*")


def _missing(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().casefold() in _MISSING
    )


def _currency_from_text(value: str, context_currency: str | None) -> str | None:
    """Extract only currencies that are explicit or supplied as context."""
    if context_currency:
        normalized = normalize_currency(context_currency)
        if normalized:
            return normalized
    for symbol, code in _CURRENCY_SYMBOLS.items():
        if symbol in value:
            return code
    match = _CURRENCY_CODE_PATTERN.search(value)
    return normalize_currency(match.group(1)) if match else None


def normalize_currency(value: Any) -> str | None:
    """Normalize a known code/name or an unambiguous currency symbol."""
    if _missing(value):
        return None
    text = str(value).strip().casefold()
    if text in _CURRENCY_SYMBOLS:
        return _CURRENCY_SYMBOLS[text]
    return _CURRENCY_CODES.get(text) or (
        text.upper() if re.fullmatch(r"[a-z]{3}", text) else None
    )


def _numeric_text(value: Any) -> tuple[float | None, bool]:
    """Parse a number while rejecting malformed or ambiguous punctuation."""
    if isinstance(value, bool):
        return None, False
    if isinstance(value, (int, float)):
        return float(value), True
    text = str(value).strip()
    match = _NUMBER_PATTERN.search(text)
    if not match or not match.group(0).strip(" +-.,"):
        return None, False
    token = match.group(0).replace(" ", "")
    if token.count(",") and token.count("."):
        decimal_separator = "," if token.rfind(",") > token.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        if token.count(decimal_separator) > 1:
            return None, False
        token = token.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in token:
        parts = token.split(",")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3):
            token = "".join(parts)
        else:
            token = token.replace(",", ".")
    elif token.count(".") > 1:
        parts = token.split(".")
        if not all(len(part) == 3 for part in parts[1:]):
            return None, False
        token = "".join(parts)
    try:
        return float(token), True
    except ValueError:
        return None, False


def normalize_amount(
    value: Any, *, context_currency: str | None = None
) -> NormalizationResult:
    """Normalize a monetary value without inventing currency information."""
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    number, valid = _numeric_text(value)
    if not valid:
        return NormalizationResult(None, NormalizationMethod.AMOUNT, NormalizationStatus.INVALID)
    return NormalizationResult(
        number,
        NormalizationMethod.AMOUNT,
        NormalizationStatus.SUCCESS,
        _currency_from_text(str(value), context_currency),
    )


def normalize_date(value: Any) -> NormalizationResult:
    """Normalize safe common dates and reject ambiguous day/month formats."""
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    if isinstance(value, datetime):
        return NormalizationResult(value.date().isoformat(), NormalizationMethod.DATE, NormalizationStatus.SUCCESS)
    if isinstance(value, date):
        return NormalizationResult(value.isoformat(), NormalizationMethod.DATE, NormalizationStatus.SUCCESS)
    text = str(value).strip()
    formats = ("%Y-%m-%d", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y")
    for date_format in formats:
        try:
            return NormalizationResult(
                datetime.strptime(text, date_format).date().isoformat(),
                NormalizationMethod.DATE,
                NormalizationStatus.SUCCESS,
            )
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if match:
        first, second, year = (int(part) for part in match.groups())
        if first <= 12 and second <= 12:
            return NormalizationResult(None, NormalizationMethod.DATE, NormalizationStatus.INVALID)
        day, month = (first, second) if first > 12 else (second, first)
        try:
            return NormalizationResult(
                date(year, month, day).isoformat(),
                NormalizationMethod.DATE,
                NormalizationStatus.SUCCESS,
            )
        except ValueError:
            pass
    return NormalizationResult(None, NormalizationMethod.DATE, NormalizationStatus.INVALID)


def normalize_entity(value: Any) -> NormalizationResult:
    """Create a conservative comparison form, not an entity match."""
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    normalized = re.sub(r"[^\w\s]", " ", str(value).casefold(), flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    normalized = re.sub(r"\b(incorporated|corporation)\b", "corp", normalized)
    return NormalizationResult(normalized, NormalizationMethod.ENTITY, NormalizationStatus.SUCCESS)


def normalize_identifier(value: Any) -> NormalizationResult:
    """Trim and case-fold an identifier while retaining meaningful punctuation."""
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    normalized = re.sub(r"\s+", " ", str(value).strip()).upper()
    return NormalizationResult(normalized, NormalizationMethod.IDENTIFIER, NormalizationStatus.SUCCESS)


def _simple_numeric(value: Any, method: NormalizationMethod) -> NormalizationResult:
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    number, valid = _numeric_text(value)
    return NormalizationResult(
        number,
        method,
        NormalizationStatus.SUCCESS if valid else NormalizationStatus.INVALID,
    )


def normalize_text(value: Any) -> NormalizationResult:
    """Normalize whitespace and case for comparison without semantic rewriting."""
    if _missing(value):
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.MISSING)
    return NormalizationResult(
        re.sub(r"\s+", " ", str(value).strip()).casefold(),
        NormalizationMethod.TEXT,
        NormalizationStatus.SUCCESS,
    )


def normalize_value(
    value: Any,
    semantic_type: SemanticType | None,
    *,
    context_currency: str | None = None,
) -> NormalizationResult:
    """Dispatch one value to its semantic-type-specific normalizer."""
    if semantic_type is None:
        return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.UNSUPPORTED)
    if semantic_type == SemanticType.AMOUNT:
        return normalize_amount(value, context_currency=context_currency)
    if semantic_type == SemanticType.UNIT_PRICE:
        return normalize_amount(value, context_currency=context_currency)
    if semantic_type == SemanticType.DATE:
        return normalize_date(value)
    if semantic_type == SemanticType.ENTITY:
        return normalize_entity(value)
    if semantic_type == SemanticType.IDENTIFIER:
        return normalize_identifier(value)
    if semantic_type == SemanticType.QUANTITY:
        return _simple_numeric(value, NormalizationMethod.QUANTITY)
    if semantic_type == SemanticType.CURRENCY:
        result = normalize_currency(value)
        status = NormalizationStatus.SUCCESS if result else (
            NormalizationStatus.MISSING if _missing(value) else NormalizationStatus.INVALID
        )
        return NormalizationResult(result, NormalizationMethod.CURRENCY, status)
    if semantic_type in {SemanticType.TEXT, SemanticType.ADDRESS}:
        return normalize_text(value)
    return NormalizationResult(None, NormalizationMethod.NONE, NormalizationStatus.UNSUPPORTED)


def normalize_field(
    field: MappedField, *, context_currency: str | None = None
) -> NormalizedField:
    """Normalize one mapped field while preserving its source representation."""
    result = normalize_value(
        field.raw_value,
        field.semantic_type,
        context_currency=context_currency,
    )
    return NormalizedField(
        field_id=field.field_id,
        source_document_id=field.source_document_id,
        raw_label=field.raw_label,
        raw_value=field.raw_value,
        semantic_type=field.semantic_type,
        semantic_role=field.semantic_role,
        normalized_value=result.normalized_value,
        normalization_method=result.normalization_method,
        normalization_status=result.normalization_status,
        currency=result.currency,
    )


def normalize_document(document: MappedDocument) -> NormalizedDocument:
    """Normalize all mapped fields without mutating the mapped document."""
    currency = next(
        (
            str(field.raw_value)
            for field in document.fields
            if field.semantic_type == SemanticType.CURRENCY and not _missing(field.raw_value)
        ),
        None,
    )
    return NormalizedDocument(
        document_id=document.document_id,
        document_type=document.document_type,
        fields=[
            normalize_field(field, context_currency=currency)
            for field in document.fields
        ],
    )
