"""Integration tests for PostgreSQL and pgvector RAG storage."""

from __future__ import annotations

import os

import pytest

from rag import storage


def _sample_chunk(chunk_id: str = "storage-test-chunk") -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": "storage-test-document",
        "document_type": "invoice",
        "chunk_text": "Invoice INV-001 total USD 120.",
        "metadata": {"source": "storage-test.pdf", "invoice_number": "INV-001"},
        "embedding": [0.125] * 768,
    }


@pytest.fixture(scope="module")
def postgres():
    if os.environ.get("RAG_DATABASE_TESTS", "1") != "1":
        pytest.skip("RAG_DATABASE_TESTS is disabled")
    try:
        storage.init_schema()
        import psycopg

        with psycopg.connect(storage.database_url()) as connection:
            extension = connection.execute(
                "SELECT 1 FROM pg_extension WHERE extname='vector'"
            ).fetchone()
        if extension is None:
            pytest.fail("pgvector extension was not enabled")
    except Exception as error:
        pytest.skip(f"PostgreSQL integration unavailable: {error}")
    storage.delete_chunks_by_document("storage-test-document")
    yield
    storage.delete_chunks_by_document("storage-test-document")


def test_insert_retrieve_and_duplicate_are_idempotent(postgres) -> None:
    chunk = _sample_chunk()
    assert storage.insert_chunk(chunk) is True
    assert storage.insert_chunk(chunk) is False
    stored = storage.get_chunk(chunk["chunk_id"])
    assert stored is not None
    assert stored["chunk_text"] == chunk["chunk_text"]
    assert len(stored["embedding"]) == 768
    assert stored["metadata"]["invoice_number"] == "INV-001"
    assert storage.chunk_exists(chunk["chunk_id"]) is True


def test_update_batch_and_document_delete(postgres) -> None:
    first = _sample_chunk("storage-test-a")
    second = _sample_chunk("storage-test-b")
    assert storage.insert_chunks([first, second]) == 2
    first["chunk_text"] = "Updated invoice total USD 125."
    first["embedding"] = [0.25] * 768
    storage.update_chunk(first)
    assert storage.get_chunk(first["chunk_id"])["chunk_text"] == first["chunk_text"]
    assert storage.delete_chunks_by_document("storage-test-document") == 3
    assert storage.chunk_exists(first["chunk_id"]) is False


def test_invalid_embedding_dimensions_are_rejected(postgres) -> None:
    chunk = _sample_chunk()
    chunk["embedding"] = [0.0] * 767
    with pytest.raises(ValueError, match="expected 768"):
        storage.insert_chunk(chunk)
