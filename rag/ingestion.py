"""Ingest registered extracted documents into the local RAG database."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rag import chunking, embeddings, storage
from storage import registry
from utils.config import REGISTRY_DB

LOGGER = logging.getLogger(__name__)


@dataclass
class IngestionReport:
    """Counts and document-level failures from one ingestion run."""

    documents_discovered: int = 0
    documents_successful: int = 0
    documents_skipped: int = 0
    documents_failed: int = 0
    total_chunks_generated: int = 0
    chunks_inserted: int = 0
    chunks_updated: int = 0
    chunks_skipped_unchanged: int = 0
    chunks_failed: int = 0
    chunks_deleted_stale: int = 0
    failed_documents: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable report."""
        return asdict(self)


def _document_id(document: Mapping[str, Any]) -> str:
    """Return a document ID or raise a clear malformed-document error."""
    value = document.get("document_id")
    if not isinstance(value, str) or not value:
        raise ValueError("document_id must be a non-empty string")
    return value


def _same_chunk(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Compare stored and generated content while excluding timestamps."""
    return (
        left.get("document_id") == right.get("document_id")
        and left.get("document_type") == right.get("document_type")
        and left.get("chunk_text") == right.get("chunk_text")
        and left.get("metadata") == right.get("metadata")
        and left.get("embedding") == right.get("embedding")
    )


def _process_document(document: Mapping[str, Any], report: IngestionReport) -> bool:
    """Process one extracted document and update the run report."""
    document_id = _document_id(document)
    generated = chunking.chunk_document(document)
    report.total_chunks_generated += len(generated)
    existing = {
        chunk["chunk_id"]: chunk
        for chunk in storage.get_chunks_by_document(document_id)
    }
    to_embed: list[dict[str, Any]] = []
    ready: list[dict[str, Any]] = []
    for chunk in generated:
        previous = existing.get(chunk["chunk_id"])
        if previous is not None:
            candidate = {**chunk, "embedding": previous["embedding"]}
            if _same_chunk(previous, candidate):
                report.chunks_skipped_unchanged += 1
                continue
        to_embed.append(chunk)

    if to_embed:
        try:
            ready.extend(embeddings.embed_chunks(to_embed))
        except Exception:
            report.chunks_failed += len(to_embed)
            raise
    for chunk in ready:
        if len(chunk["embedding"]) != storage.EMBEDDING_DIMENSIONS:
            raise RuntimeError(f"Embedding dimension validation failed for {chunk['chunk_id']}")
        if chunk["chunk_id"] in existing:
            storage.update_chunk(chunk)
            report.chunks_updated += 1
        elif storage.insert_chunk(chunk):
            report.chunks_inserted += 1
        else:
            report.chunks_skipped_unchanged += 1

    current_ids = {chunk["chunk_id"] for chunk in generated}
    stale_ids = set(existing) - current_ids
    if stale_ids:
        report.chunks_deleted_stale += storage.delete_chunks(sorted(stale_ids))
    return True


def ingest_documents(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Ingest supplied extracted document payloads into PostgreSQL."""
    storage.init_schema()
    report = IngestionReport(documents_discovered=len(documents))
    for document in documents:
        try:
            if not isinstance(document, Mapping):
                raise ValueError("document payload must be a JSON object")
            _process_document(document, report)
            report.documents_successful += 1
        except Exception as error:
            document_id = str(document.get("document_id", "<missing>")) if isinstance(document, Mapping) else "<invalid>"
            report.documents_failed += 1
            report.failed_documents.append({"document_id": document_id, "error": str(error)})
            LOGGER.error("RAG ingestion failed for document %s: %s", document_id, error)
    return report.as_dict()


def discover_documents(
    db_path: Path = REGISTRY_DB,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read extracted documents from the existing SQLite registry."""
    if document_id is not None:
        document = registry.get_document(document_id, db_path)
        return [document] if document is not None else []
    return registry.get_documents(db_path)


def ingest_registered_documents(
    db_path: Path = REGISTRY_DB,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Discover registered extracted documents and ingest them."""
    documents = discover_documents(db_path, document_id)
    report = ingest_documents(documents)
    if document_id is not None and not documents:
        report["documents_skipped"] = 1
        report["skipped_document_ids"] = [document_id]
    return report


def main() -> None:
    """Run explicit registry-to-PostgreSQL RAG ingestion from the CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", help="Process only one registered document")
    parser.add_argument("--registry-db", type=Path, default=REGISTRY_DB)
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    report = ingest_registered_documents(args.registry_db, args.document_id)
    print(json.dumps(report, indent=2))
    if report["documents_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
