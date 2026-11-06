"""Grounded local-LLM answer generation over retrieved financial chunks."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag import retrieval

DEFAULT_GENERATION_MODEL = "qwen3.5:9b"
DEFAULT_CONTEXT_CHARS = 6000
SYSTEM_PROMPT = """You answer questions using only the retrieved financial document context.
Treat the context as the source of truth. Never invent invoice numbers, dates,
amounts, vendors, taxes, payment terms, or other financial details. If the
context is insufficient, say so explicitly. Distinguish stated facts from
calculations or inferences. For calculations or comparisons, show the
calculation and identify the source documents. Disclose conflicting values
instead of silently choosing one. Do not claim a document contains information
that was not retrieved. Keep the answer clear, structured, and relevant.
Include a short Source section naming only the document IDs present in context."""


def _model() -> str:
    """Return the configurable local generation model."""
    return os.environ.get("RAG_GENERATION_MODEL", DEFAULT_GENERATION_MODEL).strip() or DEFAULT_GENERATION_MODEL


def _ollama_url() -> str:
    """Return the configured Ollama base URL."""
    return os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def _generate(context: str, question: str, model: str, timeout: float) -> str:
    """Ask the local Ollama chat API for a grounded answer."""
    payload = json.dumps({
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Retrieved context:\n{context}\n\nQuestion: {question}"},
        ],
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    request = urllib.request.Request(
        f"{_ollama_url()}/api/chat",
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
                f"Ollama generation model not found: {model!r}. "
                f"Pull it with `ollama pull {model}`."
            ) from error
        raise RuntimeError(f"Ollama generation request failed ({error.code}): {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Could not connect to Ollama at {_ollama_url()}: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise RuntimeError(f"Could not connect to Ollama at {_ollama_url()}: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("Ollama returned invalid JSON for answer generation") from error

    answer = body.get("message", {}).get("content") if isinstance(body, Mapping) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Ollama returned no answer content")
    return answer.strip()


def answer_question(
    question: str,
    *,
    top_k: int = 5,
    max_context_chars: int = DEFAULT_CONTEXT_CHARS,
    timeout: float = 180,
    filters: retrieval.RetrievalFilters | None = None,
) -> dict[str, Any]:
    """Retrieve context and generate a separately attributable local answer."""
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    try:
        chunks = retrieval.retrieve(question, top_k=top_k, filters=filters)
    except RuntimeError as error:
        return {
            "question": question,
            "answer": str(error),
            "sources": [],
            "retrieved_chunks": [],
            "model": _model(),
            "generation_status": "retrieval_error",
        }
    sources = []
    seen_sources: set[str] = set()
    for chunk in chunks:
        document_id = str(chunk.get("document_id") or "")
        if document_id and document_id not in seen_sources:
            metadata = chunk.get("metadata") or {}
            sources.append({
                "document_id": document_id,
                "document_type": chunk.get("document_type"),
                "source": metadata.get("source") or metadata.get("source_path") or metadata.get("source_name"),
            })
            seen_sources.add(document_id)
    base = {
        "question": question,
        "sources": sources,
        "retrieved_chunks": chunks,
        "model": _model(),
    }
    if not chunks:
        return {
            **base,
            "answer": "I could not find relevant retrieved financial documents to answer this question.",
            "generation_status": "no_retrieved_context",
        }
    context = retrieval.prepare_context(chunks, max_chars=max_context_chars)
    try:
        answer = _generate(context, question, base["model"], timeout)
    except RuntimeError as error:
        return {**base, "answer": str(error), "generation_status": "generation_error"}
    return {**base, "answer": answer, "generation_status": "completed"}


def main() -> None:
    """Answer one question or read multiple questions interactively."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-context-chars", type=int, default=DEFAULT_CONTEXT_CHARS)
    args = parser.parse_args()
    questions: Sequence[str] = [args.question] if args.question else iter(
        input("Question (blank to exit): ").strip()
        for _ in iter(int, 1)
    )
    for question in questions:
        if not question:
            break
        result = answer_question(
            question,
            top_k=args.top_k,
            max_context_chars=args.max_context_chars,
        )
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
