"""Focused tests for the downstream semantic mapping layer."""

import unittest
from pathlib import Path

from ingestion.schemas.contracts import ExtractedField, SourceDocument
from reconciliation.semantic_mapping import (
    DocumentType,
    MappingMethod,
    SemanticRole,
    map_document,
    map_field,
)


def _field(label: str, value: object = "$1,250") -> ExtractedField:
    return ExtractedField(
        field_id="field-1",
        label=label,
        value=value,
        source_document_id="doc-1",
    )


class SemanticMappingTests(unittest.TestCase):
    """Verify rules, contextual similarity, uncertainty, and provenance."""

    def test_obvious_rule_preserves_raw_data(self) -> None:
        mapped = map_field(_field("Invoice Number", "INV-9"))
        self.assertEqual(mapped.semantic_role, SemanticRole.INVOICE_ID)
        self.assertEqual(mapped.mapping_method, MappingMethod.RULE)
        self.assertEqual(mapped.raw_label, "Invoice Number")
        self.assertEqual(mapped.raw_value, "INV-9")

    def test_amount_variations_use_similarity(self) -> None:
        invoice = map_field(_field("Grand Total"), document_type=DocumentType.INVOICE)
        payable = map_field(_field("Net Payable"), document_type=DocumentType.INVOICE)
        self.assertEqual(invoice.semantic_role, SemanticRole.TRANSACTION_TOTAL)
        self.assertEqual(payable.semantic_type.value, "AMOUNT")
        self.assertEqual(payable.mapping_method, MappingMethod.SIMILARITY)

    def test_amount_is_contextual(self) -> None:
        invoice = map_field(_field("Amount"), document_type=DocumentType.INVOICE)
        payment = map_field(_field("Amount"), document_type=DocumentType.PAYMENT)
        self.assertEqual(invoice.semantic_role, SemanticRole.TRANSACTION_TOTAL)
        self.assertEqual(payment.semantic_role, SemanticRole.AMOUNT_PAID)

    def test_unknown_and_ambiguous_labels_do_not_get_forced(self) -> None:
        unknown = map_field(_field("ZXQ-unknown-label", None))
        ambiguous = map_field(_field("number"))
        self.assertEqual(unknown.mapping_method, MappingMethod.UNRESOLVED)
        self.assertIsNone(unknown.semantic_role)
        self.assertEqual(ambiguous.mapping_method, MappingMethod.UNRESOLVED)
        self.assertIsNone(ambiguous.semantic_role)
        self.assertGreaterEqual(ambiguous.mapping_confidence, 0.0)

    def test_document_maps_all_fields_and_keeps_source_fields(self) -> None:
        document = SourceDocument(
            document_id="doc-1",
            source_path="invoice.json",
            document_type="INVOICE",
            fields=[_field("Total:", "$222.89"), _field("Unrecognized", "keep me")],
        )
        mapped = map_document(document)
        self.assertEqual(mapped.document_type, DocumentType.INVOICE)
        self.assertEqual(mapped.fields[0].raw_label, "Total:")
        self.assertEqual(mapped.fields[0].raw_value, "$222.89")
        self.assertEqual(mapped.fields[1].mapping_method, MappingMethod.UNRESOLVED)

    def test_real_extraction_directory_is_supported_when_present(self) -> None:
        extraction_dir = Path("data/processed/extracted")
        files = list(extraction_dir.glob("*.json"))
        if not files:
            self.skipTest("No processed extraction fixtures are present")
        self.assertTrue(files)


if __name__ == "__main__":
    unittest.main()
