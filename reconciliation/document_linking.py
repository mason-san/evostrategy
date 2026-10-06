"""Deterministic linking of related business documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Iterable

from reconciliation.entity_resolution import (
    EntityType,
    ResolutionConfig,
    EntityResolutionResult,
    resolve_normalized_entities,
)
from reconciliation.normalization import NormalizedDocument, NormalizedField
from reconciliation.semantic_mapping import DocumentType, SemanticRole


class RelationshipType(StrEnum):
    """Supported document relationships."""

    INVOICE_PURCHASE_ORDER = "INVOICE_PURCHASE_ORDER"
    INVOICE_PAYMENT = "INVOICE_PAYMENT"
    INVOICE_LEDGER = "INVOICE_LEDGER"


class LinkStatus(StrEnum):
    """Outcome of evaluating a document pair."""

    LINKED = "LINKED"
    AMBIGUOUS = "AMBIGUOUS"
    UNLINKED = "UNLINKED"


@dataclass(frozen=True)
class LinkingConfig:
    """Explainable evidence weights and decision thresholds."""

    identifier_weight: float = 0.60
    entity_weight: float = 0.20
    amount_weight: float = 0.15
    date_weight: float = 0.05
    linked_threshold: float = 0.38
    ambiguous_threshold: float = 0.35
    date_window_days: int = 90
    amount_tolerance_percent: float = 2.0

    def __post_init__(self) -> None:
        if self.linked_threshold <= self.ambiguous_threshold:
            raise ValueError("linked_threshold must exceed ambiguous_threshold")
        if (
            not 0 <= self.ambiguous_threshold <= 1
            or not 0 <= self.linked_threshold <= 1
        ):
            raise ValueError("link thresholds must be between 0 and 1")
        if abs(
            self.identifier_weight
            + self.entity_weight
            + self.amount_weight
            + self.date_weight
            - 1.0
        ) > 0.001:
            raise ValueError("linking evidence weights must sum to 1")


@dataclass(frozen=True)
class LinkingEvidence:
    """Signals used to explain one pair decision."""

    identifier_match: bool = False
    identifier_field_ids: tuple[str, ...] = ()
    entity_match: bool = False
    entity_score: float | None = None
    entity_field_ids: tuple[str, ...] = ()
    date_difference_days: int | None = None
    amount_difference: float | None = None
    amount_difference_percent: float | None = None
    currencies_compatible: bool | None = None
    amount_compatible: bool | None = None
    candidate_filter_passed: bool = False

    def model_dump(self) -> dict[str, Any]:
        """Return JSON-compatible linking evidence."""
        return {
            "identifier_match": self.identifier_match,
            "identifier_field_ids": list(self.identifier_field_ids),
            "entity_match": self.entity_match,
            "entity_score": self.entity_score,
            "entity_field_ids": list(self.entity_field_ids),
            "date_difference_days": self.date_difference_days,
            "amount_difference": self.amount_difference,
            "amount_difference_percent": self.amount_difference_percent,
            "currencies_compatible": self.currencies_compatible,
            "amount_compatible": self.amount_compatible,
            "candidate_filter_passed": self.candidate_filter_passed,
        }


@dataclass(frozen=True)
class DocumentLinkResult:
    """Auditable result for one document pair."""

    left_document_id: str
    right_document_id: str
    relationship: RelationshipType
    status: LinkStatus
    linked: bool
    confidence: float
    evidence: LinkingEvidence

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible link decision."""
        return {
            "left_document_id": self.left_document_id,
            "right_document_id": self.right_document_id,
            "relationship": self.relationship.value,
            "status": self.status.value,
            "linked": self.linked,
            "confidence": self.confidence,
            "evidence": self.evidence.model_dump(),
        }


@dataclass(frozen=True)
class _DocumentFacts:
    identifiers: tuple[NormalizedField, ...] = ()
    entities: tuple[NormalizedField, ...] = ()
    amounts: tuple[NormalizedField, ...] = ()
    dates: tuple[NormalizedField, ...] = ()


_RELATIONSHIPS = {
    frozenset((DocumentType.INVOICE, DocumentType.PURCHASE_ORDER)): RelationshipType.INVOICE_PURCHASE_ORDER,
    frozenset((DocumentType.INVOICE, DocumentType.PAYMENT)): RelationshipType.INVOICE_PAYMENT,
    frozenset((DocumentType.INVOICE, DocumentType.LEDGER)): RelationshipType.INVOICE_LEDGER,
}

_IDENTIFIER_ROLES = {
    SemanticRole.DOCUMENT_ID,
    SemanticRole.INVOICE_ID,
    SemanticRole.ORDER_ID,
    SemanticRole.PAYMENT_ID,
}
_ENTITY_ROLES = {SemanticRole.VENDOR, SemanticRole.CUSTOMER}
_AMOUNT_ROLES = {
    SemanticRole.TRANSACTION_TOTAL,
    SemanticRole.ORDER_TOTAL,
    SemanticRole.AMOUNT_PAID,
    SemanticRole.BALANCE_DUE,
    SemanticRole.SUBTOTAL,
}


def _role(field: NormalizedField) -> SemanticRole | None:
    if isinstance(field.semantic_role, SemanticRole):
        return field.semantic_role
    try:
        return SemanticRole(field.semantic_role) if field.semantic_role else None
    except ValueError:
        return None


def _facts(document: NormalizedDocument) -> _DocumentFacts:
    """Extract only fields relevant to linking; ignore unrelated text."""
    fields = [field for field in document.fields if field.normalized_value is not None]
    return _DocumentFacts(
        identifiers=tuple(field for field in fields if _role(field) in _IDENTIFIER_ROLES),
        entities=tuple(field for field in fields if _role(field) in _ENTITY_ROLES),
        amounts=tuple(field for field in fields if _role(field) in _AMOUNT_ROLES),
        dates=tuple(field for field in fields if _role(field) == SemanticRole.DOCUMENT_DATE),
    )


def _relationship(left: NormalizedDocument, right: NormalizedDocument) -> RelationshipType | None:
    return _RELATIONSHIPS.get(frozenset((DocumentType(left.document_type), DocumentType(right.document_type))))


def _identifier_evidence(left: _DocumentFacts, right: _DocumentFacts) -> tuple[bool, tuple[str, ...]]:
    matches = [
        (a.field_id, b.field_id)
        for a in left.identifiers
        for b in right.identifiers
        if a.normalized_value == b.normalized_value
    ]
    return bool(matches), tuple(identifier for pair in matches for identifier in pair)


def _entity_evidence(
    left: _DocumentFacts, right: _DocumentFacts
) -> tuple[bool, float | None, tuple[str, ...]]:
    candidates: list[tuple[EntityResolutionResult, str, str]] = []
    for left_field in left.entities:
        for right_field in right.entities:
            candidates.append((
                resolve_normalized_entities(
                    left_field.normalized_value,
                    right_field.normalized_value,
                    entity_type=EntityType.VENDOR,
                ),
                left_field.field_id,
                right_field.field_id,
            ))
    if not candidates:
        return False, None, ()
    best, left_id, right_id = max(candidates, key=lambda item: item[0].score)
    return best.resolved, best.score, (left_id, right_id)


def _date_difference(left: _DocumentFacts, right: _DocumentFacts) -> int | None:
    values: list[int] = []
    for left_field in left.dates:
        for right_field in right.dates:
            try:
                values.append(
                    abs(
                        (date.fromisoformat(str(left_field.normalized_value))
                         - date.fromisoformat(str(right_field.normalized_value))).days
                    )
                )
            except ValueError:
                continue
    return min(values) if values else None


def _amount_evidence(
    left: _DocumentFacts, right: _DocumentFacts, tolerance: float
) -> tuple[float | None, float | None, bool | None, bool | None]:
    if not left.amounts or not right.amounts:
        return None, None, None, None
    candidates: list[tuple[float, float, bool]] = []
    for left_field in left.amounts:
        for right_field in right.amounts:
            currencies = {left_field.currency, right_field.currency} - {None}
            if len(currencies) > 1:
                continue
            left_amount = float(left_field.normalized_value)
            right_amount = float(right_field.normalized_value)
            difference = abs(left_amount - right_amount)
            baseline = max(abs(left_amount), abs(right_amount), 1.0)
            percent = difference / baseline * 100
            candidates.append((difference, percent, percent <= tolerance))
    if not candidates:
        return None, None, False, False
    return min(candidates, key=lambda candidate: candidate[1])[0], min(
        candidates, key=lambda candidate: candidate[1]
    )[1], True, min(candidates, key=lambda candidate: candidate[1])[2]


def evaluate_link(
    left: NormalizedDocument,
    right: NormalizedDocument,
    *,
    config: LinkingConfig = LinkingConfig(),
) -> DocumentLinkResult:
    """Evaluate one supported pair without making a reconciliation decision."""
    relationship = _relationship(left, right)
    if relationship is None:
        raise ValueError("only supported invoice relationships can be linked")
    left_facts, right_facts = _facts(left), _facts(right)
    identifier_match, identifier_ids = _identifier_evidence(left_facts, right_facts)
    entity_match, entity_score, entity_ids = _entity_evidence(left_facts, right_facts)
    date_difference = _date_difference(left_facts, right_facts)
    amount_difference, amount_percent, currencies_compatible, amount_compatible = _amount_evidence(
        left_facts, right_facts, config.amount_tolerance_percent
    )
    date_score = (
        1.0 if date_difference == 0 else
        max(0.0, 1 - date_difference / config.date_window_days)
        if date_difference is not None else 0.0
    )
    amount_score = 1.0 if amount_compatible else 0.0
    score = (
        config.identifier_weight * float(identifier_match)
        + config.entity_weight * (entity_score or 0.0)
        + config.amount_weight * amount_score
        + config.date_weight * date_score
    )
    evidence = LinkingEvidence(
        identifier_match=identifier_match,
        identifier_field_ids=identifier_ids,
        entity_match=entity_match,
        entity_score=entity_score,
        entity_field_ids=entity_ids,
        date_difference_days=date_difference,
        amount_difference=amount_difference,
        amount_difference_percent=amount_percent,
        currencies_compatible=currencies_compatible,
        amount_compatible=amount_compatible,
        candidate_filter_passed=identifier_match or entity_match or amount_compatible,
    )
    status = (
        LinkStatus.LINKED
        if score >= config.linked_threshold
        else LinkStatus.AMBIGUOUS
        if score >= config.ambiguous_threshold
        else LinkStatus.UNLINKED
    )
    return DocumentLinkResult(
        left.document_id,
        right.document_id,
        relationship,
        status,
        status == LinkStatus.LINKED,
        round(score, 3),
        evidence,
    )


def generate_candidates(
    documents: Iterable[NormalizedDocument],
    *,
    config: LinkingConfig = LinkingConfig(),
) -> list[tuple[NormalizedDocument, NormalizedDocument]]:
    """Generate supported pairs using identifier/entity/amount/date signals."""
    documents = list(documents)
    candidates: list[tuple[NormalizedDocument, NormalizedDocument]] = []
    for index, left in enumerate(documents):
        for right in documents[index + 1 :]:
            if _relationship(left, right) is None:
                continue
            result = evaluate_link(left, right, config=config)
            if result.evidence.candidate_filter_passed or result.evidence.date_difference_days is not None:
                candidates.append((left, right))
    return candidates


def link_documents(
    documents: Iterable[NormalizedDocument],
    *,
    config: LinkingConfig = LinkingConfig(),
) -> list[DocumentLinkResult]:
    """Evaluate candidate pairs and mark competing strong candidates ambiguous."""
    candidates = generate_candidates(documents, config=config)
    results = [evaluate_link(left, right, config=config) for left, right in candidates]
    linked_by_left: dict[str, int] = {}
    for result in results:
        if result.status == LinkStatus.LINKED:
            linked_by_left[result.left_document_id] = (
                linked_by_left.get(result.left_document_id, 0) + 1
            )
    for index, result in enumerate(results):
        if (
            result.status == LinkStatus.LINKED
            and linked_by_left.get(result.left_document_id, 0) > 1
        ):
            results[index] = DocumentLinkResult(
                result.left_document_id,
                result.right_document_id,
                result.relationship,
                LinkStatus.AMBIGUOUS,
                False,
                result.confidence,
                result.evidence,
            )
    return results
