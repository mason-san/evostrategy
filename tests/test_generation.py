"""Tests for grounded local answer generation."""

import json
import urllib.error

import pytest

from rag import generation


def _chunk():
    return {
        "chunk_id": "c1",
        "document_id": "invoice_001_page_1",
        "document_type": "invoice",
        "chunk_text": "Total: $50.10",
        "metadata": {"source_name": "invoice_001_page_1.png"},
        "similarity_score": 0.9,
    }


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


def test_answer_uses_retrieval_context_and_sources(monkeypatch) -> None:
    calls = {}
    monkeypatch.setattr(generation.retrieval, "retrieve", lambda question, **kwargs: [_chunk()])
    monkeypatch.setattr(generation.retrieval, "prepare_context", lambda chunks, **kwargs: calls.setdefault("context", chunks[0]["chunk_text"]) or "")
    def fake_urlopen(request, timeout):
        calls["payload"] = json.loads(request.data)
        return _Response({"message": {"content": "The total is $50.10.\n\nSource: invoice_001_page_1"}})
    monkeypatch.setattr(generation.urllib.request, "urlopen", fake_urlopen)
    result = generation.answer_question("What is the total?")
    assert result["generation_status"] == "completed"
    assert result["sources"][0]["document_id"] == "invoice_001_page_1"
    assert "Total" in calls["context"]
    assert "What is the total?" in calls["payload"]["messages"][1]["content"]


def test_empty_retrieval_does_not_call_llm(monkeypatch) -> None:
    monkeypatch.setattr(generation.retrieval, "retrieve", lambda *args, **kwargs: [])
    monkeypatch.setattr(generation, "_generate", lambda *args, **kwargs: pytest.fail("LLM should not be called"))
    result = generation.answer_question("Unknown document")
    assert result["generation_status"] == "no_retrieved_context"
    assert result["sources"] == []


def test_generation_model_error_is_structured(monkeypatch) -> None:
    monkeypatch.setattr(generation.retrieval, "retrieve", lambda *args, **kwargs: [_chunk()])
    monkeypatch.setattr(generation.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(
        urllib.error.HTTPError("http://ollama/api/chat", 404, "missing", {}, None)
    ))
    result = generation.answer_question("What is the total?")
    assert result["generation_status"] == "generation_error"
    assert "model not found" in result["answer"]


def test_retrieval_error_is_structured(monkeypatch) -> None:
    monkeypatch.setattr(
        generation.retrieval,
        "retrieve",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    result = generation.answer_question("What is the total?")
    assert result["generation_status"] == "retrieval_error"
    assert "database unavailable" in result["answer"]


def test_invalid_question_is_rejected() -> None:
    with pytest.raises(ValueError):
        generation.answer_question("")
