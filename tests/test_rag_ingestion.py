"""Live integration tests for registry-to-Ollama-to-pgvector ingestion."""

from __future__ import annotations

import copy

import pytest

from rag import ingestion, storage
from rag.chunking import chunk_document
from storage import registry
from utils.config import PROJECT_ROOT

REAL_REGISTRY_DB = PROJECT_ROOT / "data" / "processed" / "reconciliation.db"


@pytest.fixture(scope="module")
def live_document():
    try:
        documents = registry.get_documents(REAL_REGISTRY_DB)
        storage.init_schema()
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5):
            pass
    except Exception as error:
        pytest.skip(f"live RAG services unavailable: {error}")
    if not documents:
        pytest.skip("no extracted registry documents available")
    document = copy.deepcopy(documents[0])
    document["document_id"] = "integration-rag-test-document"
    storage.delete_chunks_by_document(document["document_id"])
    yield document
    storage.delete_chunks_by_document(document["document_id"])


def test_ingestion_stores_real_chunks_and_is_repeatable(live_document) -> None:
    first = ingestion.ingest_documents([live_document])
    assert first["documents_successful"] == 1
    assert first["total_chunks_generated"] > 0
    assert first["chunks_inserted"] == first["total_chunks_generated"]
    assert first["chunks_skipped_unchanged"] == 0
    assert all(
        chunk["document_type"] == "invoice"
        for chunk in storage.get_chunks_by_document(live_document["document_id"])
    )

    second = ingestion.ingest_documents([live_document])
    assert second["documents_successful"] == 1
    assert second["chunks_inserted"] == 0
    assert second["chunks_updated"] == 0
    assert second["chunks_skipped_unchanged"] == second["total_chunks_generated"]
    assert len(storage.get_chunks_by_document(live_document["document_id"])) == first["total_chunks_generated"]


def test_modified_document_removes_stale_chunks(live_document) -> None:
    ingestion.ingest_documents([live_document])
    modified = copy.deepcopy(live_document)
    modified["fields"] = modified.get("fields", [])[:1]
    report = ingestion.ingest_documents([modified])
    assert report["documents_successful"] == 1
    assert report["chunks_deleted_stale"] > 0
    stored = storage.get_chunks_by_document(modified["document_id"])
    assert {chunk["chunk_id"] for chunk in stored} == {
        chunk["chunk_id"] for chunk in chunk_document(modified)
    }


def test_failed_document_does_not_stop_valid_document(live_document) -> None:
    report = ingestion.ingest_documents([{}, live_document])
    assert report["documents_failed"] == 1
    assert report["failed_documents"][0]["document_id"] == "<missing>"
    assert report["documents_successful"] == 1
