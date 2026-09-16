"""Focused tests for source-contract adaptation and canonical mapping."""

import unittest

from ingestion.schemas.contracts import (
    ExtractedField,
    SourceDocument,
    source_document_from_extraction,
)
from ingestion.schemas.invoice_schema import DocumentExtraction
from normalization.mapper import map_document


class ContractsMapperTests(unittest.TestCase):
    """Verify canonical mapping is additive and source-faithful."""

    def test_mapping_preserves_raw_values_and_adds_canonical_values(self) -> None:
        """Numeric canonicalization must not replace the source amount."""
        extraction = {
            "fields": [
                {"field_id": "f1", "label": "Supplier:", "value": "ACME"},
                {"field_id": "f2", "label": "Invoice #", "value": "INV-7"},
                {"field_id": "f3", "label": "Invoice Date:", "value": "06 Mar 2012"},
                {"field_id": "f4", "label": "Total:", "value": "$1,234.50"},
                {"field_id": "f5", "label": "Currency:", "value": "USD"},
            ],
            "tables": [],
        }
        source = source_document_from_extraction(
            "doc-1", "invoice.pdf", DocumentExtraction(**extraction)
        )

        canonical = map_document(source)

        self.assertEqual(source.fields[3].value, "$1,234.50")
        self.assertEqual(canonical.amount, 1234.50)
        self.assertEqual(canonical.raw_values["amount"], "$1,234.50")
        self.assertEqual(canonical.raw_values["currency"], "USD")
        self.assertEqual(canonical.identifier, "INV-7")
        self.assertEqual(canonical.raw_field_ids["amount"], "f4")

    def test_source_adapter_accepts_pydantic_extraction_items(self) -> None:
        """The adapter supports typed extraction items as well as JSON mappings."""
        extraction = DocumentExtraction(
            fields=[
                ExtractedField(
                    field_id="f1",
                    label="Total",
                    value="10",
                    source_document_id="doc-1",
                )
            ],
            tables=[],
        )
        source = source_document_from_extraction("doc-1", "invoice.pdf", extraction)
        self.assertIsInstance(source, SourceDocument)
        self.assertEqual(source.fields[0].value, "10")


if __name__ == "__main__":
    unittest.main()
