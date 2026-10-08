"""Deterministic, confidence-aware resolution of normalized entity values.

Scoring follows the implementation plan: Jaro-Winkler similarity (rapidfuzz)
with a resolved threshold of 0.90. Jaro-Winkler rewards shared prefixes, so on
its own it would treat "ABC Corp" and "ABC Corp India" as the same company. A
token-coverage guard therefore keeps those pairs AMBIGUOUS for a reviewer:
every word of each name must have a close (Jaro-Winkler >= 0.90) partner in
the other name before a fuzzy pair is RESOLVED.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from reconciliation.normalization import normalize_entity

try:  # rapidfuzz is the planned dependency; difflib keeps tests runnable without it
    from rapidfuzz.distance import JaroWinkler as _JaroWinkler

    def jaro_winkler(left: str, right: str) -> float:
        return float(_JaroWinkler.similarity(left, right))
except ImportError:  # pragma: no cover - exercised only when rapidfuzz is absent
    from difflib import SequenceMatcher

    def jaro_winkler(left: str, right: str) -> float:
        return SequenceMatcher(None, left, right).ratio()

TOKEN_MATCH_THRESHOLD = 0.90


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

    The 0.90 resolved threshold is the plan's Jaro-Winkler cut-off. Scores
    from 0.70 up to it, or high scores whose words do not all line up, stay
    explicitly ambiguous instead of being silently accepted.
    """

    resolved_threshold: float = 0.90
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


def token_coverage(left: str, right: str) -> float:
    """Share of words (in both names) that have a close partner in the other name."""
    left_tokens, right_tokens = left.split(), right.split()
    if not left_tokens or not right_tokens:
        return 0.0

    def covered(tokens: list[str], others: list[str]) -> int:
        return sum(any(jaro_winkler(t, o) >= TOKEN_MATCH_THRESHOLD for o in others) for t in tokens)

    return (covered(left_tokens, right_tokens) + covered(right_tokens, left_tokens)) / (
        len(left_tokens) + len(right_tokens)
    )


def _similarity(left: str, right: str) -> float:
    """Jaro-Winkler similarity of the two names (token order ignored)."""
    direct = jaro_winkler(left, right)
    reordered = jaro_winkler(" ".join(sorted(left.split())), " ".join(sorted(right.split())))
    return round(max(direct, reordered), 3)


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
    coverage = token_coverage(left, right)
    if score >= config.resolved_threshold and coverage == 1.0:
        status = ResolutionStatus.RESOLVED
    elif score >= config.ambiguous_threshold and coverage > 0.5:
        status = ResolutionStatus.AMBIGUOUS
    else:
        status = ResolutionStatus.UNRESOLVED
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
