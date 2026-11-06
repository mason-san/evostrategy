"""Embed chunks from the local registry with Ollama and print a preview."""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.chunking import chunk_registered_documents
from rag.embeddings import embed_chunks


def main() -> None:
    """Generate embeddings and print one safe vector preview."""
    chunks = chunk_registered_documents()
    embedded = embed_chunks(chunks)
    print(f"Embedded {len(embedded)} chunks.")
    if embedded:
        sample = embedded[0]
        vector = sample["embedding"]
        print(json.dumps({
            "chunk_id": sample["chunk_id"],
            "dimensions": len(vector),
            "preview": vector[:5],
        }, indent=2))
        print('-' * 50)
        print("THE VECTOR of 768 dimensions:")
        print(vector)
        print('-' * 50)


if __name__ == "__main__":
    main()
