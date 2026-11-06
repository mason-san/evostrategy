"""PostgreSQL and pgvector storage for local RAG chunks."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from typing import Any, Iterator

DEFAULT_DATABASE_URL = (
    "postgresql://evo:evo_local_dev@localhost:5433/evostrategy"
)
EMBEDDING_DIMENSIONS = 768
TABLE_NAME = "rag_chunks"


def database_url() -> str:
    """Return the configured PostgreSQL connection URL."""
    return os.environ.get("RAG_DATABASE_URL", DEFAULT_DATABASE_URL)


def _psycopg():
    """Import psycopg only when PostgreSQL storage is used."""
    try:
        import psycopg
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL storage requires psycopg; install with `pip install psycopg[binary]`"
        ) from error
    return psycopg


@contextmanager
def _connection() -> Iterator[Any]:
    """Open a PostgreSQL connection and translate connection failures clearly."""
    psycopg = _psycopg()
    try:
        with psycopg.connect(database_url()) as connection:
            yield connection
    except psycopg.Error as error:
        raise RuntimeError(f"Could not connect to PostgreSQL at {database_url()}: {error}") from error


def _validate_chunk(chunk: Mapping[str, Any]) -> tuple[str, str, str | None, str, Mapping[str, Any], list[float]]:
    """Validate a Step 1/2 chunk before it reaches PostgreSQL."""
    chunk_id = chunk.get("chunk_id")
    document_id = chunk.get("document_id")
    text = chunk.get("chunk_text")
    embedding = chunk.get("embedding")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("chunk_id must be a non-empty string")
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id must be a non-empty string")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("chunk_text must be a non-empty string")
    if not isinstance(embedding, Sequence) or isinstance(embedding, (str, bytes, bytearray)):
        raise ValueError("embedding must be a numeric sequence")
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"embedding has {len(embedding)} dimensions; expected {EMBEDDING_DIMENSIONS}"
        )
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in embedding):
        raise ValueError("embedding must contain only numeric values")
    metadata = chunk.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a JSON object")
    return (
        chunk_id,
        document_id,
        chunk.get("document_type"),
        text,
        metadata,
        [float(value) for value in embedding],
    )


def _vector_literal(embedding: Sequence[float]) -> str:
    """Format a validated vector for pgvector's text input."""
    return "[" + ",".join(str(value) for value in embedding) + "]"


def init_schema() -> None:
    """Enable pgvector and create the RAG chunk table and indexes safely."""
    with _connection() as connection:
        try:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_type TEXT,
                    chunk_text TEXT NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    embedding vector({EMBEDDING_DIMENSIONS}) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_document_id_idx "
                f"ON {TABLE_NAME} (document_id)"
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_embedding_hnsw_idx "
                f"ON {TABLE_NAME} USING hnsw (embedding vector_cosine_ops)"
            )
        except Exception as error:
            raise RuntimeError(f"Could not initialize PostgreSQL RAG schema: {error}") from error


def insert_chunk(chunk: Mapping[str, Any]) -> bool:
    """Insert one chunk, returning False when its deterministic ID already exists."""
    values = _validate_chunk(chunk)
    with _connection() as connection:
        cursor = connection.execute(
            f"""
            INSERT INTO {TABLE_NAME}
                (chunk_id, document_id, document_type, chunk_text, metadata, embedding)
            VALUES (%s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (chunk_id) DO NOTHING
            """,
            (*values[:4], _json(values[4]), _vector_literal(values[5])),
        )
        return cursor.rowcount == 1


def insert_chunks(chunks: Sequence[Mapping[str, Any]]) -> int:
    """Insert multiple chunks atomically, returning the number of new rows."""
    validated = [_validate_chunk(chunk) for chunk in chunks]
    if not validated:
        return 0
    with _connection() as connection:
        inserted = 0
        for values in validated:
            cursor = connection.execute(
                f"""
                INSERT INTO {TABLE_NAME}
                    (chunk_id, document_id, document_type, chunk_text, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (chunk_id) DO NOTHING
                """,
                (*values[:4], _json(values[4]), _vector_literal(values[5])),
            )
            inserted += cursor.rowcount
        return inserted


def update_chunk(chunk: Mapping[str, Any]) -> None:
    """Replace an existing chunk's content, metadata, embedding, and update time."""
    values = _validate_chunk(chunk)
    with _connection() as connection:
        cursor = connection.execute(
            f"""
            UPDATE {TABLE_NAME}
            SET document_id=%s, document_type=%s, chunk_text=%s, metadata=%s,
                embedding=%s::vector, updated_at=CURRENT_TIMESTAMP
            WHERE chunk_id=%s
            """,
            (values[1], values[2], values[3], _json(values[4]), _vector_literal(values[5]), values[0]),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"Chunk does not exist: {values[0]}")


def delete_chunks_by_document(document_id: str) -> int:
    """Delete all chunks belonging to one source document."""
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id must be a non-empty string")
    with _connection() as connection:
        cursor = connection.execute(
            f"DELETE FROM {TABLE_NAME} WHERE document_id=%s", (document_id,)
        )
        return cursor.rowcount


def get_chunks_by_document(document_id: str) -> list[dict[str, Any]]:
    """Return stored chunks for one document, including embeddings."""
    if not isinstance(document_id, str) or not document_id:
        raise ValueError("document_id must be a non-empty string")
    with _connection() as connection:
        rows = connection.execute(
            f"""
            SELECT chunk_id, document_id, document_type, chunk_text, metadata,
                   embedding::text, created_at, updated_at
            FROM {TABLE_NAME} WHERE document_id=%s ORDER BY chunk_id
            """,
            (document_id,),
        ).fetchall()
    return [_chunk_from_row(row) for row in rows]


def delete_chunks(chunk_ids: Sequence[str]) -> int:
    """Delete specific stale chunk IDs and return the number removed."""
    ids = list(chunk_ids)
    if any(not isinstance(chunk_id, str) or not chunk_id for chunk_id in ids):
        raise ValueError("chunk_ids must contain non-empty strings")
    if not ids:
        return 0
    with _connection() as connection:
        cursor = connection.execute(
            f"DELETE FROM {TABLE_NAME} WHERE chunk_id = ANY(%s)", (ids,)
        )
        return cursor.rowcount


def chunk_exists(chunk_id: str) -> bool:
    """Return whether a chunk ID is already stored."""
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("chunk_id must be a non-empty string")
    with _connection() as connection:
        row = connection.execute(
            f"SELECT 1 FROM {TABLE_NAME} WHERE chunk_id=%s", (chunk_id,)
        ).fetchone()
        return row is not None


def get_chunk(chunk_id: str) -> dict[str, Any] | None:
    """Return one stored chunk, including its vector as numeric values."""
    if not isinstance(chunk_id, str) or not chunk_id:
        raise ValueError("chunk_id must be a non-empty string")
    with _connection() as connection:
        row = connection.execute(
            f"""
            SELECT chunk_id, document_id, document_type, chunk_text, metadata,
                   embedding::text, created_at, updated_at
            FROM {TABLE_NAME} WHERE chunk_id=%s
            """,
            (chunk_id,),
        ).fetchone()
    return _chunk_from_row(row) if row is not None else None


def _chunk_from_row(row: Any) -> dict[str, Any]:
    """Convert a PostgreSQL chunk row into the Step 2-compatible mapping."""
    embedding = [float(value) for value in row[5].strip("[]").split(",")]
    return {
        "chunk_id": row[0],
        "document_id": row[1],
        "document_type": row[2],
        "chunk_text": row[3],
        "metadata": row[4],
        "embedding": embedding,
        "created_at": row[6],
        "updated_at": row[7],
    }


def _json(value: Mapping[str, Any]) -> Any:
    """Wrap metadata for psycopg's JSONB adaptation."""
    from psycopg.types.json import Json

    return Json(dict(value))
