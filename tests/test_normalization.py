"""Focused tests for source-preserving value normalization."""

import unittest

from ingestion.schemas.contracts import ExtractedField
from reconciliation.normalization import (
    NormalizationStatus,
    normalize_amount,
    normalize_date,
    normalize_field,
    normalize_value,
)
from reconciliation.semantic_mapping import (
    MappedField,
    MappingMethod,
    SemanticRole,
    SemanticType,
)


def mapped(label: str, value: object, semantic_type: SemanticType) -> MappedField:
    """Create a mapped-field fixture with complete provenance."""
    return MappedField(
        field_id="field-8",
        source_document_id="doc-1",
        raw_label=label,
        raw_value=value,
        semantic_type=semantic_type,
        semantic_role=SemanticRole.TRANSACTION_TOTAL,
        mapping_method=MappingMethod.RULE,
        mapping_confidence=1.0,
    )


class NormalizationTests(unittest.TestCase):
    """Verify conservative normalization and raw-value traceability."""

    def test_amounts_and_currency(self) -> None:
        result = normalize_amount("$1,250.00")
        self.assertEqual(result.normalized_value, 1250.0)
        self.assertIsNone(result.currency)
        self.assertEqual(normalize_amount("$1,250.00", context_currency="USD").currency, "USD")
        self.assertEqual(normalize_amount("1,250.50").normalized_value, 1250.5)
        self.assertEqual(normalize_amount("EUR 500").currency, "EUR")

    def test_date_and_ambiguous_date(self) -> None:
        self.assertEqual(normalize_date("Jul 22 2012").normalized_value, "2012-07-22")
        self.assertEqual(
            normalize_date("01/02/2012").normalization_status,
            NormalizationStatus.INVALID,
        )

    def test_entity_identifier_quantity_and_missing_values(self) -> None:
        self.assertEqual(normalize_value(" ACME  Corporation ", SemanticType.ENTITY).normalized_value, "acme corp")
        self.assertEqual(normalize_value(" inv-00123 ", SemanticType.IDENTIFIER).normalized_value, "INV-00123")
        self.assertEqual(normalize_value("10 units", SemanticType.QUANTITY).normalized_value, 10.0)
        self.assertEqual(normalize_amount("N/A").normalization_status, NormalizationStatus.MISSING)

    def test_invalid_numeric_and_raw_value_preservation(self) -> None:
        self.assertEqual(normalize_amount("not money").normalization_status, NormalizationStatus.INVALID)
        field = mapped("Total:", "$222.89", SemanticType.AMOUNT)
        normalized = normalize_field(field)
        self.assertEqual(normalized.raw_label, "Total:")
        self.assertEqual(normalized.raw_value, "$222.89")
        self.assertEqual(normalized.normalized_value, 222.89)
        self.assertEqual(normalized.normalization_status, NormalizationStatus.SUCCESS)

    def test_real_extraction_contract_remains_usable(self) -> None:
        field = ExtractedField(
            field_id="f1",
            label="Amount",
            value="$10.00",
            source_document_id="doc-1",
        )
        self.assertEqual(field.value, "$10.00")


if __name__ == "__main__":
    unittest.main()
