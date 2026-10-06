"""Auditable semantic mapping for generic extracted document fields.

This module is deliberately downstream of Stage 1.  It creates semantic
metadata next to source fields; it never mutates or replaces them.
"""

from __future__ import annotations

import re
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any, Protocol

from ingestion.schemas.contracts import ExtractedField, SourceDocument


class DocumentType(StrEnum):
    """Document types used only to disambiguate semantic roles."""

    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    PAYMENT = "PAYMENT"
    LEDGER = "LEDGER"
    UNKNOWN = "UNKNOWN"


class SemanticType(StrEnum):
    """Controlled semantic field types."""

    ENTITY = "ENTITY"
    IDENTIFIER = "IDENTIFIER"
    DATE = "DATE"
    AMOUNT = "AMOUNT"
    QUANTITY = "QUANTITY"
    UNIT_PRICE = "UNIT_PRICE"
    CURRENCY = "CURRENCY"
    ADDRESS = "ADDRESS"
    TEXT = "TEXT"


class SemanticRole(StrEnum):
    """Controlled semantic roles supported by the mapper."""

    VENDOR = "VENDOR"
    CUSTOMER = "CUSTOMER"
    DOCUMENT_ID = "DOCUMENT_ID"
    INVOICE_ID = "INVOICE_ID"
    ORDER_ID = "ORDER_ID"
    PAYMENT_ID = "PAYMENT_ID"
    DOCUMENT_DATE = "DOCUMENT_DATE"
    TRANSACTION_TOTAL = "TRANSACTION_TOTAL"
    ORDER_TOTAL = "ORDER_TOTAL"
    AMOUNT_PAID = "AMOUNT_PAID"
    BALANCE_DUE = "BALANCE_DUE"
    SUBTOTAL = "SUBTOTAL"
    TAX = "TAX"
    DISCOUNT = "DISCOUNT"
    SHIPPING = "SHIPPING"
    CURRENCY = "CURRENCY"


class MappingMethod(StrEnum):
    """How a semantic role was selected."""

    RULE = "rule"
    SIMILARITY = "similarity"
    LLM = "llm"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class SemanticCandidate:
    """A controlled role and its similarity score."""

    role: SemanticRole
    semantic_type: SemanticType
    score: float


class SemanticLLMProvider(Protocol):
    """Optional ambiguity resolver isolated from the mapping algorithm."""

    def resolve(
        self,
        *,
        raw_label: str,
        raw_value: Any,
        document_type: DocumentType,
        nearby_fields: list[dict[str, Any]],
        candidates: tuple[SemanticRole, ...],
    ) -> SemanticRole | None:
        """Return one supplied candidate, or ``None`` when uncertain."""


class GeminiSemanticProvider:
    """Optional Gemini resolver constrained to mapper-supplied candidates."""

    def resolve(
        self,
        *,
        raw_label: str,
        raw_value: Any,
        document_type: DocumentType,
        nearby_fields: list[dict[str, Any]],
        candidates: tuple[SemanticRole, ...],
    ) -> SemanticRole | None:
        """Ask Gemini for one allowed role, returning ``None`` when unavailable."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key or not candidates:
            return None

        from google import genai
        from google.genai import types

        prompt = {
            "document_type": document_type.value,
            "raw_label": raw_label,
            "raw_value": raw_value,
            "nearby_fields": nearby_fields,
            "allowed_roles": [candidate.value for candidate in candidates],
        }
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=json.dumps(prompt, default=str),
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Choose the best semantic role from allowed_roles only. "
                    "Return JSON exactly as {\"role\": \"ROLE\"} or "
                    "{\"role\": null} when uncertain. Never invent a role."
                ),
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        try:
            selected = json.loads(response.text).get("role")
        except (AttributeError, json.JSONDecodeError):
            return None
        try:
            role = SemanticRole(selected) if selected else None
        except ValueError:
            return None
        return role if role in candidates else None


class SimilarityProvider(Protocol):
    """Provider abstraction for deterministic or embedding-based ranking."""

    def rank(
        self, label: str, document_type: DocumentType
    ) -> list[SemanticCandidate]:
        """Return controlled semantic candidates in descending confidence."""


class MappedField:
    """Semantic metadata for one source field, retaining its raw content."""

    def __init__(
        self,
        *,
        field_id: str,
        source_document_id: str,
        raw_label: str,
        raw_value: Any,
        semantic_type: SemanticType | None,
        semantic_role: SemanticRole | None,
        mapping_method: MappingMethod,
        mapping_confidence: float,
    ) -> None:
        self.field_id = field_id
        self.source_document_id = source_document_id
        self.raw_label = raw_label
        self.raw_value = raw_value
        self.semantic_type = semantic_type
        self.semantic_role = semantic_role
        self.mapping_method = mapping_method
        self.mapping_confidence = mapping_confidence

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible audit record."""
        return {
            "field_id": self.field_id,
            "source_document_id": self.source_document_id,
            "raw_label": self.raw_label,
            "raw_value": self.raw_value,
            "semantic_type": self.semantic_type.value if self.semantic_type else None,
            "semantic_role": self.semantic_role.value if self.semantic_role else None,
            "mapping_method": self.mapping_method.value,
            "mapping_confidence": self.mapping_confidence,
        }


class MappedDocument:
    """Mapped view of a source document with all source fields represented."""

    def __init__(
        self,
        *,
        document_id: str,
        document_type: DocumentType,
        fields: list[MappedField],
    ) -> None:
        self.document_id = document_id
        self.document_type = document_type
        self.fields = fields

    def model_dump(self) -> dict[str, Any]:
        """Return the mapped document without discarding source information."""
        return {
            "document_id": self.document_id,
            "document_type": self.document_type.value,
            "fields": [field.model_dump() for field in self.fields],
        }


@dataclass(frozen=True)
class MappingConfig:
    """Confidence policy for deterministic, similarity, and fallback mapping."""

    similarity_accept: float = 0.78
    similarity_ambiguity_gap: float = 0.08
    llm_accept: float = 0.70


_STOP_WORDS = {"a", "an", "the", "of", "for", "to", "in", "on"}

# Small rules are reserved for labels whose meaning is genuinely obvious.
_RULES: dict[str, tuple[SemanticRole, SemanticType]] = {
    "vendor": (SemanticRole.VENDOR, SemanticType.ENTITY),
    "supplier": (SemanticRole.VENDOR, SemanticType.ENTITY),
    "customer": (SemanticRole.CUSTOMER, SemanticType.ENTITY),
    "invoice number": (SemanticRole.INVOICE_ID, SemanticType.IDENTIFIER),
    "invoice no": (SemanticRole.INVOICE_ID, SemanticType.IDENTIFIER),
    "order id": (SemanticRole.ORDER_ID, SemanticType.IDENTIFIER),
    "payment id": (SemanticRole.PAYMENT_ID, SemanticType.IDENTIFIER),
    "date": (SemanticRole.DOCUMENT_DATE, SemanticType.DATE),
    "invoice date": (SemanticRole.DOCUMENT_DATE, SemanticType.DATE),
    "currency": (SemanticRole.CURRENCY, SemanticType.CURRENCY),
    "subtotal": (SemanticRole.SUBTOTAL, SemanticType.AMOUNT),
    "tax": (SemanticRole.TAX, SemanticType.AMOUNT),
    "discount": (SemanticRole.DISCOUNT, SemanticType.AMOUNT),
    "shipping": (SemanticRole.SHIPPING, SemanticType.AMOUNT),
}

_ROLE_DESCRIPTIONS: dict[SemanticRole, tuple[SemanticType, tuple[str, ...]]] = {
    SemanticRole.VENDOR: (SemanticType.ENTITY, ("vendor supplier seller company",)),
    SemanticRole.CUSTOMER: (SemanticType.ENTITY, ("customer buyer billed to",)),
    SemanticRole.DOCUMENT_ID: (SemanticType.IDENTIFIER, ("document reference number",)),
    SemanticRole.INVOICE_ID: (SemanticType.IDENTIFIER, ("invoice number identifier",)),
    SemanticRole.ORDER_ID: (SemanticType.IDENTIFIER, ("purchase order order number",)),
    SemanticRole.PAYMENT_ID: (SemanticType.IDENTIFIER, ("payment transaction reference",)),
    SemanticRole.DOCUMENT_DATE: (SemanticType.DATE, ("document invoice transaction date",)),
    SemanticRole.TRANSACTION_TOTAL: (
        SemanticType.AMOUNT,
        ("invoice grand total net payable amount due", "grand total", "net payable", "amount due"),
    ),
    SemanticRole.ORDER_TOTAL: (SemanticType.AMOUNT, ("purchase order total value",)),
    SemanticRole.AMOUNT_PAID: (
        SemanticType.AMOUNT,
        ("payment amount paid received", "amount paid"),
    ),
    SemanticRole.BALANCE_DUE: (SemanticType.AMOUNT, ("outstanding balance amount due",)),
    SemanticRole.SUBTOTAL: (SemanticType.AMOUNT, ("subtotal before tax",)),
    SemanticRole.TAX: (SemanticType.AMOUNT, ("tax vat amount",)),
    SemanticRole.DISCOUNT: (SemanticType.AMOUNT, ("discount deduction amount",)),
    SemanticRole.SHIPPING: (SemanticType.AMOUNT, ("shipping freight delivery charge",)),
}


def normalize_label(label: str | None) -> str:
    """Normalize a label for matching without changing the source label."""
    if not label:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", label.casefold())).strip()


def _tokens(text: str) -> set[str]:
    return {token for token in normalize_label(text).split() if token not in _STOP_WORDS}


def _similarity(label: str, description: str) -> float:
    left, right = _tokens(label), _tokens(description)
    if not left or not right:
        return 0.0
    overlap = len(left & right) / len(left | right)
    sequence = SequenceMatcher(None, normalize_label(label), normalize_label(description)).ratio()
    return round(max(overlap, sequence * 0.75), 3)


def _document_type(document: SourceDocument) -> DocumentType:
    explicit = normalize_label(document.document_type)
    for candidate in DocumentType:
        if explicit == normalize_label(candidate.value):
            return candidate
    labels = " ".join(normalize_label(field.label) for field in document.fields)
    if "purchase order" in labels or "po number" in labels:
        return DocumentType.PURCHASE_ORDER
    if "payment" in labels or "amount paid" in labels:
        return DocumentType.PAYMENT
    if "invoice" in labels or "balance due" in labels:
        return DocumentType.INVOICE
    if "ledger" in labels:
        return DocumentType.LEDGER
    return DocumentType.UNKNOWN


def _contextualize(candidates: Iterable[SemanticCandidate], document_type: DocumentType) -> list[SemanticCandidate]:
    adjusted: list[SemanticCandidate] = []
    for candidate in candidates:
        score = candidate.score
        if candidate.role == SemanticRole.TRANSACTION_TOTAL and document_type == DocumentType.INVOICE:
            score += 0.12
        if candidate.role == SemanticRole.ORDER_TOTAL and document_type == DocumentType.PURCHASE_ORDER:
            score += 0.12
        if candidate.role == SemanticRole.AMOUNT_PAID and document_type == DocumentType.PAYMENT:
            score += 0.12
        adjusted.append(SemanticCandidate(candidate.role, candidate.semantic_type, min(score, 1.0)))
    return sorted(adjusted, key=lambda item: item.score, reverse=True)


def _similarity_candidates(label: str, document_type: DocumentType) -> list[SemanticCandidate]:
    if normalize_label(label) == "amount":
        contextual_roles = {
            DocumentType.INVOICE: SemanticRole.TRANSACTION_TOTAL,
            DocumentType.PURCHASE_ORDER: SemanticRole.ORDER_TOTAL,
            DocumentType.PAYMENT: SemanticRole.AMOUNT_PAID,
        }
        preferred = contextual_roles.get(document_type)
        if preferred:
            semantic_type = _ROLE_DESCRIPTIONS[preferred][0]
            candidates = [
                SemanticCandidate(
                    role,
                    _ROLE_DESCRIPTIONS[role][0],
                    0.80 if role == preferred else 0.58,
                )
                for role in (
                    SemanticRole.TRANSACTION_TOTAL,
                    SemanticRole.ORDER_TOTAL,
                    SemanticRole.AMOUNT_PAID,
                    SemanticRole.BALANCE_DUE,
                )
            ]
            return _contextualize(candidates, document_type)
    candidates = [
        SemanticCandidate(role, semantic_type, _similarity(label, description))
        for role, (semantic_type, descriptions) in _ROLE_DESCRIPTIONS.items()
        for description in descriptions
    ]
    return _contextualize(candidates, document_type)


class LexicalSimilarityProvider:
    """Small dependency-free similarity provider for the current prototype."""

    def rank(
        self, label: str, document_type: DocumentType
    ) -> list[SemanticCandidate]:
        """Rank only roles from the controlled vocabulary."""
        return _similarity_candidates(label, document_type)


def _nearby_fields(document: SourceDocument, field: ExtractedField) -> list[dict[str, Any]]:
    """Provide compact neighboring context to an optional fallback provider."""
    index = next((position for position, item in enumerate(document.fields) if item.field_id == field.field_id), -1)
    if index < 0:
        return []
    return [
        {"label": item.label, "value": item.value}
        for item in document.fields[max(0, index - 2) : index + 3]
        if item.field_id != field.field_id
    ]


def map_field(
    field: ExtractedField,
    *,
    document_type: DocumentType = DocumentType.UNKNOWN,
    nearby_fields: list[dict[str, Any]] | None = None,
    similarity_provider: SimilarityProvider | None = None,
    llm_provider: SemanticLLMProvider | None = None,
    config: MappingConfig = MappingConfig(),
) -> MappedField:
    """Map one field while preserving its exact label and value."""
    raw_label = field.label or ""
    normalized = normalize_label(raw_label)
    rule = _RULES.get(normalized)
    if rule:
        role, semantic_type = rule
        return MappedField(
            field_id=field.field_id,
            source_document_id=field.source_document_id,
            raw_label=raw_label,
            raw_value=field.value,
            semantic_type=semantic_type,
            semantic_role=role,
            mapping_method=MappingMethod.RULE,
            mapping_confidence=1.0,
        )

    provider = similarity_provider or LexicalSimilarityProvider()
    candidates = provider.rank(raw_label, document_type)
    best = candidates[0] if candidates else None
    second = candidates[1] if len(candidates) > 1 else None
    if best and best.score >= config.similarity_accept and (
        second is None or best.score - second.score >= config.similarity_ambiguity_gap
    ):
        return MappedField(
            field_id=field.field_id,
            source_document_id=field.source_document_id,
            raw_label=raw_label,
            raw_value=field.value,
            semantic_type=best.semantic_type,
            semantic_role=best.role,
            mapping_method=MappingMethod.SIMILARITY,
            mapping_confidence=round(best.score, 3),
        )

    if llm_provider and best:
        chosen = llm_provider.resolve(
            raw_label=raw_label,
            raw_value=field.value,
            document_type=document_type,
            nearby_fields=nearby_fields or [],
            candidates=tuple(candidate.role for candidate in candidates[:4]),
        )
        allowed = {candidate.role: candidate for candidate in candidates}
        selected = allowed.get(chosen)
        if selected:
            return MappedField(
                field_id=field.field_id,
                source_document_id=field.source_document_id,
                raw_label=raw_label,
                raw_value=field.value,
                semantic_type=selected.semantic_type,
                semantic_role=selected.role,
                mapping_method=MappingMethod.LLM,
                mapping_confidence=config.llm_accept,
            )

    return MappedField(
        field_id=field.field_id,
        source_document_id=field.source_document_id,
        raw_label=raw_label,
        raw_value=field.value,
        semantic_type=None,
        semantic_role=None,
        mapping_method=MappingMethod.UNRESOLVED,
        mapping_confidence=round(best.score if best else 0.0, 3),
    )


def map_document(
    document: SourceDocument,
    *,
    similarity_provider: SimilarityProvider | None = None,
    llm_provider: SemanticLLMProvider | None = None,
    config: MappingConfig = MappingConfig(),
) -> MappedDocument:
    """Map every extracted field and retain unresolved fields for review."""
    document_type = _document_type(document)
    return MappedDocument(
        document_id=document.document_id,
        document_type=document_type,
        fields=[
            map_field(
                field,
                document_type=document_type,
                nearby_fields=_nearby_fields(document, field),
                similarity_provider=similarity_provider,
                llm_provider=llm_provider,
                config=config,
            )
            for field in document.fields
        ],
    )
