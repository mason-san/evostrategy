"""Generate and validate local Ollama embeddings for RAG chunks."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
EXPECTED_EMBEDDING_DIMENSIONS = 768
DEFAULT_TIMEOUT_SECONDS = 120

_embedding_cache: dict[tuple[str, str], list[float]] = {}


def _url() -> str:
    """Return the configured Ollama base URL."""
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _validate_embedding(value: Any, *, text: str, dimensions: int) -> list[float]:
    """Validate one Ollama vector and return it as ordinary floats."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise RuntimeError("Ollama returned an embedding that is not a vector")
    if len(value) != dimensions:
        raise RuntimeError(
            f"Ollama returned {len(value)} dimensions; expected {dimensions}"
        )
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
           for item in value):
        raise RuntimeError(f"Ollama returned non-numeric values for text: {text[:80]!r}")
    return [float(item) for item in value]


def _request_embeddings(
    texts: list[str],
    *,
    model: str,
    timeout: float,
) -> list[list[float]]:
    """Request a batch of embeddings from Ollama's embedding API."""
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{_url()}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code == 404:
            raise RuntimeError(
                f"Ollama embedding model not found: {model!r}. "
                f"Pull it with `ollama pull {model}`."
            ) from error
        raise RuntimeError(f"Ollama embedding request failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not connect to Ollama at {_url()}: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not connect to Ollama at {_url()}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama returned invalid JSON for the embedding request") from error

    embeddings = body.get("embeddings") if isinstance(body, Mapping) else None
    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        raise RuntimeError("Ollama returned an invalid embedding response")
    return [
        _validate_embedding(embedding, text=text, dimensions=EXPECTED_EMBEDDING_DIMENSIONS)
        for text, embedding in zip(texts, embeddings)
    ]


def embed_text(
    text: str,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[float]:
    """Embed one non-empty text using the local Ollama embedding model."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    return _embed_texts([text], model=model, timeout=timeout)[0]


def embed_texts(
    texts: Sequence[str],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[list[float]]:
    """Embed multiple non-empty texts in one Ollama batch request."""
    values = list(texts)
    if any(not isinstance(text, str) or not text.strip() for text in values):
        raise ValueError("texts must contain only non-empty strings")
    if not values:
        return []
    return _embed_texts(values, model=model, timeout=timeout)


def embed_query(
    query: str,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[float]:
    """Embed a search query with the same model used for document chunks."""
    return embed_text(query, model=model, timeout=timeout)


def embed_chunks(
    chunks: Sequence[Mapping[str, Any]],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Add validated embeddings to Step 1 chunk records while preserving IDs."""
    chunk_list = list(chunks)
    texts = []
    for chunk in chunk_list:
        text = chunk.get("chunk_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("every chunk must contain non-empty chunk_text")
        if not chunk.get("chunk_id"):
            raise ValueError("every chunk must contain chunk_id")
        texts.append(text)
    embeddings = embed_texts(texts, model=model, timeout=timeout)
    return [{**chunk, "embedding": embedding} for chunk, embedding in zip(chunk_list, embeddings)]


def _embed_texts(texts: list[str], *, model: str, timeout: float) -> list[list[float]]:
    """Resolve cached vectors and request only uncached texts."""
    keys = [(model, text) for text in texts]
    missing_keys = list(dict.fromkeys(key for key in keys if key not in _embedding_cache))
    if missing_keys:
        missing_vectors = _request_embeddings(
            [text for _, text in missing_keys], model=model, timeout=timeout
        )
        _embedding_cache.update(zip(missing_keys, missing_vectors))
    return [_embedding_cache[key].copy() for key in keys]


def clear_embedding_cache() -> None:
    """Clear the process-local embedding cache, primarily for tests."""
    _embedding_cache.clear()
