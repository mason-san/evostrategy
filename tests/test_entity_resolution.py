"""Focused tests for deterministic entity resolution."""

import unittest

from reconciliation.entity_resolution import (
    EntityType,
    ResolutionConfig,
    ResolutionMethod,
    ResolutionStatus,
    resolve_entities,
    resolve_normalized_entities,
)


class EntityResolutionTests(unittest.TestCase):
    """Verify exact, fuzzy, ambiguous, missing, and auditable outcomes."""

    def test_exact_normalized_match(self) -> None:
        result = resolve_entities("ACME Corporation", "acme corporation")
        self.assertTrue(result.resolved)
        self.assertEqual(result.score, 1.0)
        self.assertEqual(result.method, ResolutionMethod.EXACT_NORMALIZED)
        self.assertEqual(result.status, ResolutionStatus.RESOLVED)

    def test_formatting_variation_matches_exactly_after_normalization(self) -> None:
        result = resolve_entities("ACME Corp.", "ACME Corp")
        self.assertTrue(result.resolved)
        self.assertEqual(result.method, ResolutionMethod.EXACT_NORMALIZED)

    def test_strong_fuzzy_business_name(self) -> None:
        result = resolve_entities("Global Technology Solutions", "Global Technology Solution")
        self.assertTrue(result.resolved)
        self.assertEqual(result.method, ResolutionMethod.FUZZY)
        self.assertGreaterEqual(result.score, 0.85)

    def test_different_entities_are_unresolved(self) -> None:
        result = resolve_entities("ABC Technologies", "XYZ Technologies")
        self.assertFalse(result.resolved)
        self.assertEqual(result.status, ResolutionStatus.UNRESOLVED)

    def test_medium_similarity_is_ambiguous(self) -> None:
        result = resolve_entities("ABC Corporation", "ABC Corporation India")
        self.assertFalse(result.resolved)
        self.assertEqual(result.status, ResolutionStatus.AMBIGUOUS)

    def test_missing_values_do_not_match(self) -> None:
        for left, right in ((None, None), (None, "ACME"), ("unknown", "ACME")):
            result = resolve_entities(left, right)
            self.assertFalse(result.resolved)
            self.assertEqual(result.status, ResolutionStatus.UNRESOLVED)
            self.assertEqual(result.method, ResolutionMethod.NONE)

    def test_evidence_preserves_raw_and_normalized_values(self) -> None:
        result = resolve_entities(" ACME Corporation ", "acme corp.")
        evidence = result.model_dump()
        self.assertEqual(evidence["left_value"], " ACME Corporation ")
        self.assertEqual(evidence["right_value"], "acme corp.")
        self.assertEqual(evidence["normalized_left"], "acme corp")
        self.assertEqual(evidence["normalized_right"], "acme corp")
        self.assertIn("score", evidence)
        self.assertIn("status", evidence)

    def test_threshold_configuration_changes_decision(self) -> None:
        default = resolve_normalized_entities(
            "acme technology services", "acme technology service"
        )
        strict = resolve_normalized_entities(
            "acme technology services",
            "acme technology service",
            config=ResolutionConfig(resolved_threshold=0.99, ambiguous_threshold=0.70),
        )
        self.assertNotEqual(default.resolved, strict.resolved)

    def test_customer_type_is_supported(self) -> None:
        result = resolve_entities(
            "Customer One", "customer one", entity_type=EntityType.CUSTOMER
        )
        self.assertEqual(result.entity_type, EntityType.CUSTOMER)


if __name__ == "__main__":
    unittest.main()
