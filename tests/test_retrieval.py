"""Tests for pgvector semantic retrieval and context preparation."""

from datetime import date

import pytest

from rag import retrieval


def test_query_embedding_dimension_and_results_order(monkeypatch) -> None:
    monkeypatch.setattr(retrieval.embeddings, "embed_query", lambda query: [0.0] * 768)
    rows = []

    class Cursor:
        def execute(self, sql, params):
            rows.extend([
                ("c1", "d1", "invoice", "Total 120", {"source": "a"}, 0.9),
                ("c2", "d2", "invoice", "Total 100", {"source": "b"}, 0.7),
            ])
            return self

        def fetchall(self):
            return rows

    class Connection:
        def __enter__(self):
            return Cursor()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(retrieval.storage, "_connection", lambda: Connection())
    result = retrieval.retrieve("highest invoice", top_k=2)
    assert len(result) == 2
    assert result[0]["similarity_score"] > result[1]["similarity_score"]
    assert result[0]["chunk_id"] == "c1"


def test_filters_and_empty_results(monkeypatch) -> None:
    monkeypatch.setattr(retrieval.embeddings, "embed_query", lambda query: [0.0] * 768)
    captured = {}

    class Cursor:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return self

        def fetchall(self):
            return []

    class Connection:
        def __enter__(self):
            return Cursor()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(retrieval.storage, "_connection", lambda: Connection())
    assert retrieval.retrieve(
        "vendor invoice",
        filters= retrieval.RetrievalFilters(
            document_id="d1",
            document_type="INVOICE",
            vendor="ABC",
            date_from=date(2026, 1, 1),
        ),
    ) == []
    assert "metadata->>'vendor'" in captured["sql"]
    assert "d1" in captured["params"]


def test_context_is_bounded_and_deduplicated() -> None:
    results = [
        {"chunk_id": "c1", "document_id": "d1", "document_type": "invoice", "chunk_text": "A" * 100},
        {"chunk_id": "c1", "document_id": "d1", "document_type": "invoice", "chunk_text": "duplicate"},
        {"chunk_id": "c2", "document_id": "d2", "document_type": "invoice", "chunk_text": "B" * 100},
    ]
    context = retrieval.prepare_context(results, max_chars=180)
    assert len(context) <= 180
    assert context.count("Chunk: c1") == 1
    assert "Document d1" in context


def test_invalid_query_and_embedding_are_rejected(monkeypatch) -> None:
    with pytest.raises(ValueError):
        retrieval.retrieve("")
    monkeypatch.setattr(retrieval.embeddings, "embed_query", lambda query: [0.0])
    with pytest.raises(RuntimeError, match="expected 768"):
        retrieval.retrieve("invoice")
