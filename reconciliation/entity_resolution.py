"""Deterministic, confidence-aware resolution of normalized entity values."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any

from reconciliation.normalization import normalize_entity


class EntityType(StrEnum):
    """Entity categories supported by the resolver."""

    VENDOR = "VENDOR"
    CUSTOMER = "CUSTOMER"


class ResolutionStatus(StrEnum):
    """Decision state for one entity pair."""

    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"


class ResolutionMethod(StrEnum):
    """Deterministic method that produced a resolution result."""

    EXACT_NORMALIZED = "exact_normalized"
    FUZZY = "fuzzy"
    NONE = "none"


@dataclass(frozen=True)
class ResolutionConfig:
    """Configurable thresholds for deterministic entity resolution.

    A 0.85 resolved threshold requires both strong character similarity and
    meaningful token overlap. Scores from 0.70 through that threshold remain
    explicitly ambiguous instead of being silently accepted.
    """

    resolved_threshold: float = 0.85
    ambiguous_threshold: float = 0.70

    def __post_init__(self) -> None:
        if not 0 <= self.ambiguous_threshold <= self.resolved_threshold <= 1:
            raise ValueError(
                "thresholds must satisfy 0 <= ambiguous_threshold "
                "<= resolved_threshold <= 1"
            )


@dataclass(frozen=True)
class EntityResolutionResult:
    """Auditable result for one pair of entity values."""

    entity_type: EntityType
    resolved: bool
    score: float
    method: ResolutionMethod
    status: ResolutionStatus
    left_value: Any
    right_value: Any
    normalized_left: str | None
    normalized_right: str | None

    def model_dump(self) -> dict[str, Any]:
        """Return a JSON-compatible evidence record."""
        return {
            "entity_type": self.entity_type.value,
            "resolved": self.resolved,
            "score": self.score,
            "method": self.method.value,
            "status": self.status.value,
            "left_value": self.left_value,
            "right_value": self.right_value,
            "normalized_left": self.normalized_left,
            "normalized_right": self.normalized_right,
        }


def _is_missing(value: Any) -> bool:
    """Identify missing entity values without treating two missing values as equal."""
    return value is None or (
        isinstance(value, str)
        and value.strip().casefold() in {"", "-", "n/a", "na", "none", "null", "unknown"}
    )


def _token_similarity(left: str, right: str) -> float:
    """Compare token sets so shared suffixes cannot dominate the score."""
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _similarity(left: str, right: str) -> float:
    """Combine character and token similarity for business names."""
    character_score = SequenceMatcher(None, left, right).ratio()
    token_score = _token_similarity(left, right)
    token_order_score = SequenceMatcher(
        None, " ".join(sorted(left.split())), " ".join(sorted(right.split()))
    ).ratio()
    # Token overlap prevents names sharing only a generic suffix from matching.
    return round(
        0.45 * character_score + 0.35 * token_order_score + 0.20 * token_score,
        3,
    )


def _coerce_entity_type(entity_type: EntityType | str) -> EntityType:
    if isinstance(entity_type, EntityType):
        return entity_type
    try:
        return EntityType(str(entity_type).upper())
    except ValueError as error:
        raise ValueError(f"unsupported entity type: {entity_type!r}") from error


def resolve_normalized_entities(
    left_value: Any,
    right_value: Any,
    *,
    entity_type: EntityType | str = EntityType.VENDOR,
    config: ResolutionConfig = ResolutionConfig(),
) -> EntityResolutionResult:
    """Resolve two already-normalized entity values.

    This is the primary API for downstream callers. It performs no additional
    normalization and never treats missing values as a real match.
    """
    resolved_type = _coerce_entity_type(entity_type)
    left = None if _is_missing(left_value) else str(left_value)
    right = None if _is_missing(right_value) else str(right_value)
    if left is None or right is None:
        return EntityResolutionResult(
            resolved_type,
            False,
            0.0,
            ResolutionMethod.NONE,
            ResolutionStatus.UNRESOLVED,
            left_value,
            right_value,
            left,
            right,
        )
    if left == right:
        return EntityResolutionResult(
            resolved_type,
            True,
            1.0,
            ResolutionMethod.EXACT_NORMALIZED,
            ResolutionStatus.RESOLVED,
            left_value,
            right_value,
            left,
            right,
        )

    score = _similarity(left, right)
    status = (
        ResolutionStatus.RESOLVED
        if score >= config.resolved_threshold
        else ResolutionStatus.AMBIGUOUS
        if score >= config.ambiguous_threshold
        else ResolutionStatus.UNRESOLVED
    )
    return EntityResolutionResult(
        resolved_type,
        status == ResolutionStatus.RESOLVED,
        score,
        ResolutionMethod.FUZZY,
        status,
        left_value,
        right_value,
        left,
        right,
    )


def resolve_entities(
    left_value: Any,
    right_value: Any,
    *,
    entity_type: EntityType | str = EntityType.VENDOR,
    config: ResolutionConfig = ResolutionConfig(),
) -> EntityResolutionResult:
    """Normalize two raw entity values, then resolve only their forms.

    Raw values are passed through unchanged into the result. This convenience
    function does not perform entity matching beyond the pairwise comparison.
    """
    normalized_left = normalize_entity(left_value).normalized_value
    normalized_right = normalize_entity(right_value).normalized_value
    result = resolve_normalized_entities(
        normalized_left,
        normalized_right,
        entity_type=entity_type,
        config=config,
    )
    return EntityResolutionResult(
        entity_type=result.entity_type,
        resolved=result.resolved,
        score=result.score,
        method=result.method,
        status=result.status,
        left_value=left_value,
        right_value=right_value,
        normalized_left=normalized_left,
        normalized_right=normalized_right,
    )
