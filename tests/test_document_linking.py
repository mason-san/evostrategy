"""Focused tests for evidence-based document linking."""

import unittest

from reconciliation.document_linking import (
    LinkStatus,
    LinkingConfig,
    evaluate_link,
    link_documents,
)
from reconciliation.normalization import (
    NormalizationMethod,
    NormalizationStatus,
    NormalizedDocument,
    NormalizedField,
)
from reconciliation.semantic_mapping import DocumentType, SemanticRole, SemanticType


def field(
    field_id: str,
    role: SemanticRole,
    value: object,
    semantic_type: SemanticType,
    *,
    currency: str | None = "USD",
) -> NormalizedField:
    return NormalizedField(
        field_id=field_id,
        source_document_id="doc",
        raw_label=role.value,
        raw_value=value,
        semantic_type=semantic_type,
        semantic_role=role,
        normalized_value=value,
        normalization_method=NormalizationMethod.TEXT,
        normalization_status=NormalizationStatus.SUCCESS,
        currency=currency,
    )


def document(document_id: str, document_type: DocumentType, fields: list[NormalizedField]) -> NormalizedDocument:
    return NormalizedDocument(document_id=document_id, document_type=document_type, fields=fields)


class DocumentLinkingTests(unittest.TestCase):
    """Verify identifier, contextual, ambiguous, and missing evidence."""

    def test_identifier_match_links_invoice_and_payment(self) -> None:
        invoice = document("inv", DocumentType.INVOICE, [
            field("invoice-id", SemanticRole.INVOICE_ID, "INV-001", SemanticType.IDENTIFIER),
            field("vendor", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            field("total", SemanticRole.TRANSACTION_TOTAL, 100.0, SemanticType.AMOUNT),
        ])
        payment = document("pay", DocumentType.PAYMENT, [
            field("reference", SemanticRole.DOCUMENT_ID, "INV-001", SemanticType.IDENTIFIER),
            field("vendor", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            field("paid", SemanticRole.AMOUNT_PAID, 80.0, SemanticType.AMOUNT),
        ])
        result = evaluate_link(invoice, payment)
        self.assertEqual(result.status, LinkStatus.LINKED)
        self.assertTrue(result.evidence.identifier_match)

    def test_entity_amount_and_date_can_link_without_identifier(self) -> None:
        invoice = document("inv", DocumentType.INVOICE, [
            field("vendor", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            field("total", SemanticRole.TRANSACTION_TOTAL, 100.0, SemanticType.AMOUNT),
            field("date", SemanticRole.DOCUMENT_DATE, "2026-01-01", SemanticType.DATE),
        ])
        po = document("po", DocumentType.PURCHASE_ORDER, [
            field("vendor", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            field("total", SemanticRole.ORDER_TOTAL, 100.0, SemanticType.AMOUNT),
            field("date", SemanticRole.DOCUMENT_DATE, "2025-12-20", SemanticType.DATE),
        ])
        self.assertEqual(evaluate_link(invoice, po).status, LinkStatus.LINKED)

    def test_same_entity_alone_does_not_link(self) -> None:
        left = document("a", DocumentType.INVOICE, [field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY)])
        right = document("b", DocumentType.PAYMENT, [field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY)])
        self.assertEqual(evaluate_link(left, right).status, LinkStatus.UNLINKED)

    def test_partial_payment_can_still_link(self) -> None:
        invoice = document("inv", DocumentType.INVOICE, [
            field("id", SemanticRole.INVOICE_ID, "INV-1", SemanticType.IDENTIFIER),
            field("total", SemanticRole.TRANSACTION_TOTAL, 100.0, SemanticType.AMOUNT),
        ])
        payment = document("pay", DocumentType.PAYMENT, [
            field("ref", SemanticRole.DOCUMENT_ID, "INV-1", SemanticType.IDENTIFIER),
            field("paid", SemanticRole.AMOUNT_PAID, 50.0, SemanticType.AMOUNT),
        ])
        result = evaluate_link(invoice, payment)
        self.assertEqual(result.status, LinkStatus.LINKED)
        self.assertFalse(result.evidence.amount_compatible)

    def test_different_entities_and_incompatible_currency_are_not_linked(self) -> None:
        left = document("a", DocumentType.INVOICE, [
            field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            field("a", SemanticRole.TRANSACTION_TOTAL, 100.0, SemanticType.AMOUNT, currency="USD"),
        ])
        right = document("b", DocumentType.PAYMENT, [
            field("v", SemanticRole.VENDOR, "other", SemanticType.ENTITY),
            field("a", SemanticRole.AMOUNT_PAID, 100.0, SemanticType.AMOUNT, currency="EUR"),
        ])
        result = evaluate_link(left, right)
        self.assertEqual(result.status, LinkStatus.UNLINKED)
        self.assertFalse(result.evidence.currencies_compatible)

    def test_competing_candidates_are_ambiguous(self) -> None:
        invoice = document("inv", DocumentType.INVOICE, [
            field("id", SemanticRole.INVOICE_ID, "INV-1", SemanticType.IDENTIFIER),
            field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
        ])
        payments = [
            document(str(index), DocumentType.PAYMENT, [
                field("ref", SemanticRole.DOCUMENT_ID, "INV-1", SemanticType.IDENTIFIER),
                field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY),
            ])
            for index in (1, 2)
        ]
        results = link_documents([invoice, *payments])
        self.assertTrue(all(result.status == LinkStatus.AMBIGUOUS for result in results))

    def test_threshold_configuration_changes_status(self) -> None:
        left = document("a", DocumentType.INVOICE, [field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY)])
        right = document("b", DocumentType.PAYMENT, [field("v", SemanticRole.VENDOR, "acme", SemanticType.ENTITY)])
        result = evaluate_link(left, right, config=LinkingConfig(
            linked_threshold=0.15, ambiguous_threshold=0.10,
        ))
        self.assertEqual(result.status, LinkStatus.LINKED)


if __name__ == "__main__":
    unittest.main()
