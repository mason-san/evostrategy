"""Local retrieval-augmented generation helpers."""

from rag.chunking import chunk_document, chunk_registered_documents
from rag.embeddings import embed_chunks, embed_query, embed_text, embed_texts
from rag.storage import (
    chunk_exists,
    delete_chunks,
    delete_chunks_by_document,
    get_chunk,
    get_chunks_by_document,
    init_schema,
    insert_chunk,
    insert_chunks,
    update_chunk,
)

__all__ = [
    "chunk_document",
    "chunk_registered_documents",
    "embed_chunks",
    "embed_query",
    "embed_text",
    "embed_texts",
    "chunk_exists",
    "delete_chunks",
    "delete_chunks_by_document",
    "get_chunk",
    "get_chunks_by_document",
    "init_schema",
    "insert_chunk",
    "insert_chunks",
    "update_chunk",
]
