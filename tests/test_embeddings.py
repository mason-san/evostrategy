"""Tests for the local Ollama embedding component."""

import json
import urllib.error

import pytest

from rag import embeddings


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.payload


def _fake_urlopen(request, timeout):
    payload = json.loads(request.data)
    return _Response({"embeddings": [[float(index)] * 768 for index, _ in enumerate(payload["input"])]})


@pytest.fixture(autouse=True)
def clear_cache():
    embeddings.clear_embedding_cache()


def test_single_batch_query_and_chunk_embeddings(monkeypatch) -> None:
    monkeypatch.setattr(embeddings.urllib.request, "urlopen", _fake_urlopen)
    assert len(embeddings.embed_text("invoice")) == 768
    vectors = embeddings.embed_texts(["invoice", "payment"])
    assert len(vectors) == 2 and all(len(vector) == 768 for vector in vectors)
    assert len(embeddings.embed_query("what is total?")) == 768
    result = embeddings.embed_chunks([{"chunk_id": "c1", "chunk_text": "invoice"}])[0]
    assert result["chunk_id"] == "c1"
    assert len(result["embedding"]) == 768


def test_cache_avoids_repeated_requests(monkeypatch) -> None:
    calls = []

    def counted_urlopen(request, timeout):
        calls.append(request)
        return _fake_urlopen(request, timeout)

    monkeypatch.setattr(embeddings.urllib.request, "urlopen", counted_urlopen)
    embeddings.embed_texts(["same", "same"])
    embeddings.embed_text("same")
    assert len(calls) == 1
    assert len(json.loads(calls[0].data)["input"]) == 1


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_input_is_rejected(value) -> None:
    with pytest.raises(ValueError):
        embeddings.embed_text(value)
    with pytest.raises(ValueError):
        embeddings.embed_texts([value])


def test_invalid_dimension_and_model_error_are_explicit(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings.urllib.request, "urlopen",
        lambda request, timeout: _Response({"embeddings": [[1.0, 2.0]]}),
    )
    with pytest.raises(RuntimeError, match="expected 768"):
        embeddings.embed_text("bad vector")

    def missing_model(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    embeddings.clear_embedding_cache()
    monkeypatch.setattr(embeddings.urllib.request, "urlopen", missing_model)
    with pytest.raises(RuntimeError, match="model not found"):
        embeddings.embed_text("missing model")
