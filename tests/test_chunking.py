"""Tests for registry-backed financial document chunking."""

import json
from pathlib import Path

from rag.chunking import chunk_document, chunk_registered_documents
from storage import registry


def _document(**overrides):
    document = {
        "document_id": "invoice_001",
        "source_path": "/tmp/invoice_001.pdf",
        "source_name": "invoice_001.pdf",
        "document_type": "invoice",
        "fields": [
            {"field_id": "f1", "label": "Invoice Number", "value": "INV-001"},
            {"field_id": "f2", "label": "Vendor", "value": "ABC Technologies"},
            {"field_id": "f3", "label": "Currency", "value": "USD"},
            {"field_id": "f4", "label": "Subtotal", "value": 100},
            {"field_id": "f5", "label": "Tax", "value": 20},
            {"field_id": "f6", "label": "Total", "value": 120},
            {"field_id": "f7", "label": "Payment Terms", "value": {"days": 30, "method": "bank transfer"}},
        ],
        "tables": [{"headers": ["description", "amount"], "rows": [
            {"description": "Consulting", "amount": 100},
        ]}],
    }
    document.update(overrides)
    return document


def test_chunk_preserves_financial_fields_and_source_metadata() -> None:
    chunk = chunk_document(_document())[0]
    assert "Invoice number: INV-001" in chunk["chunk_text"]
    assert "Vendor: ABC Technologies" in chunk["chunk_text"]
    assert "Subtotal: 100" in chunk["chunk_text"]
    assert "Tax: 20" in chunk["chunk_text"]
    assert "Total: 120" in chunk["chunk_text"]
    assert "Line item 1: Description: Consulting; Amount: 100" in chunk["chunk_text"]
    assert chunk["metadata"]["source"] == "/tmp/invoice_001.pdf"


def test_missing_nested_values_are_safe() -> None:
    chunks = chunk_document(_document(fields=[
        {"field_id": "f1", "label": "Vendor", "value": None},
        {"field_id": "f2", "label": "Notes", "value": {"review": None, "tags": []}},
        None,
    ], tables=[{"headers": ["description"], "rows": [None, {"description": None}]}]))
    assert len(chunks) == 1
    assert "Document ID: invoice_001" in chunks[0]["chunk_text"]


def test_repeated_processing_has_identical_ids(tmp_path: Path) -> None:
    document = _document()
    registry.upsert_documents([document], tmp_path / "registry.db")
    first = chunk_registered_documents(tmp_path / "registry.db")
    second = chunk_registered_documents(tmp_path / "registry.db")
    assert [chunk["chunk_id"] for chunk in first] == [chunk["chunk_id"] for chunk in second]


def test_repository_invoice_json_is_readable() -> None:
    path = Path(__file__).parents[1] / "evaluation_dataset" / "ground_truth" / "invoice_001.json"
    document = json.loads(path.read_text())
    document.update({"document_id": path.stem, "document_type": "invoice", "source_path": str(path)})
    chunk = chunk_document(document)[0]
    assert "Invoice number: CA-2012-AB10015140-40974" in chunk["chunk_text"]
    assert "Invoice date: 06-03-2012" in chunk["chunk_text"]
    assert "Total amount: 50" in chunk["chunk_text"]


def test_missing_document_type_is_inferred_from_extracted_evidence() -> None:
    fields = [field for field in _document()["fields"] if field["label"] != "Payment Terms"]
    chunk = chunk_document(_document(document_type=None, fields=fields))[0]
    assert chunk["document_type"] == "invoice"
    assert chunk["metadata"]["document_type"] == "invoice"
    assert "Document type: invoice." in chunk["chunk_text"]


def test_large_documents_use_overlap_and_keep_ids() -> None:
    document = _document(fields=[
        {"field_id": str(index), "label": f"Note {index}", "value": "financial detail " * 4}
        for index in range(20)
    ])
    chunks = chunk_document(document, max_chars=250, overlap_chars=50)
    assert len(chunks) > 1
    assert all(chunk["document_id"] == "invoice_001" for chunk in chunks)
    assert any(set(chunks[index]["chunk_text"].splitlines()[1:]) & set(chunks[index + 1]["chunk_text"].splitlines())
               for index in range(len(chunks) - 1))
