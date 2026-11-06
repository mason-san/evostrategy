"""Semantic retrieval of financial chunks using PostgreSQL pgvector."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag import embeddings, storage

DEFAULT_TOP_K = 5


@dataclass(frozen=True)
class RetrievalFilters:
    """Optional filters applied to stored chunk metadata."""

    document_id: str | None = None
    document_type: str | None = None
    vendor: str | None = None
    customer: str | None = None
    date_from: date | None = None
    date_to: date | None = None


def _validate_query_embedding(vector: list[float]) -> None:
    """Validate the query vector before sending it to PostgreSQL."""
    if len(vector) != storage.EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            f"Query embedding has {len(vector)} dimensions; expected "
            f"{storage.EMBEDDING_DIMENSIONS}"
        )


def _metadata_filter_clauses(filters: RetrievalFilters) -> tuple[list[str], list[Any]]:
    """Build SQL predicates for keys supported by the stored metadata schema."""
    clauses: list[str] = []
    params: list[Any] = []
    if filters.document_id:
        clauses.append("document_id = %s")
        params.append(filters.document_id)
    if filters.document_type:
        clauses.append("document_type = %s")
        params.append(filters.document_type.lower())
    if filters.vendor:
        clauses.append("metadata->>'vendor' = %s")
        params.append(filters.vendor)
    if filters.customer:
        clauses.append("metadata->>'customer' = %s")
        params.append(filters.customer)
    if filters.date_from:
        clauses.append("(metadata->>'date')::date >= %s")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("(metadata->>'date')::date <= %s")
        params.append(filters.date_to)
    return clauses, params


def retrieve(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    filters: RetrievalFilters | None = None,
) -> list[dict[str, Any]]:
    """Return the most semantically relevant stored chunks for a query."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    active_filters = filters or RetrievalFilters()
    query_embedding = embeddings.embed_query(query)
    _validate_query_embedding(query_embedding)
    clauses, params = _metadata_filter_clauses(active_filters)
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    vector = storage._vector_literal(query_embedding)
    sql = f"""
        SELECT chunk_id, document_id, document_type, chunk_text, metadata,
               1 - (embedding <=> %s::vector) AS similarity_score
        FROM {storage.TABLE_NAME}
        {where_sql}
        ORDER BY embedding <=> %s::vector, chunk_id
        LIMIT %s
    """
    try:
        with storage._connection() as connection:
            rows = connection.execute(sql, (vector, *params, vector, top_k)).fetchall()
    except Exception as error:
        if isinstance(error, (ValueError, RuntimeError)):
            raise
        raise RuntimeError(f"Semantic retrieval failed: {error}") from error
    return [
        {
            "chunk_id": row[0],
            "document_id": row[1],
            "document_type": row[2],
            "chunk_text": row[3],
            "metadata": row[4],
            "similarity_score": float(row[5]),
        }
        for row in rows
    ]


def prepare_context(
    results: list[Mapping[str, Any]],
    *,
    max_chars: int = 6000,
) -> str:
    """Build a bounded, identity-preserving context without summarizing."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    seen: set[str] = set()
    sections: list[str] = []
    used = 0
    for result in results:
        chunk_id = str(result.get("chunk_id") or "")
        text = result.get("chunk_text")
        if not chunk_id or chunk_id in seen or not isinstance(text, str) or not text:
            continue
        header = (
            f"[Document {result.get('document_id', 'unknown')} | "
            f"Type: {result.get('document_type') or 'unknown'} | Chunk: {chunk_id}]\n"
        )
        section = header + text
        separator = "\n\n" if sections else ""
        available = max_chars - used - len(separator)
        if available <= 0:
            break
        if len(section) > available:
            section = section[:available]
        sections.append(separator + section)
        seen.add(chunk_id)
        used += len(sections[-1])
        if len(section) < len(header + text):
            break
    return "".join(sections)


def main() -> None:
    """Run one explicit retrieval query from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--document-id")
    parser.add_argument("--document-type")
    args = parser.parse_args()
    results = retrieve(
        args.query,
        top_k=args.top_k,
        filters=RetrievalFilters(
            document_id=args.document_id,
            document_type=args.document_type,
        ),
    )
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
