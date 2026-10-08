"""Removing an uploaded file drops its records and re-reconciles."""

from fastapi.testclient import TestClient

from evostrategy_backend.main import app
from storage import registry


def _doc(name: str, amount: float) -> dict:
    return {"document_id": name, "source_name": f"{name}.pdf", "source_path": f"{name}.pdf",
            "extraction_method": "rules", "extraction_confidence": 0.9, "low_confidence": False,
            "fields": [], "document_types": ["INVOICE"], "amount": amount}


def test_delete_documents_by_source_removes_only_that_file() -> None:
    registry.reset_registry()
    registry.upsert_documents([_doc("a", 1.0), _doc("b", 2.0)])
    assert registry.delete_documents_by_source("a.pdf") == 1
    assert [d["document_id"] for d in registry.get_documents()] == ["b"]
    assert registry.delete_documents_by_source("a.pdf") == 0


def test_delete_source_endpoint_404_for_unknown_file() -> None:
    registry.reset_registry()
    response = TestClient(app).delete("/api/sources/missing.pdf")
    assert response.status_code == 404
