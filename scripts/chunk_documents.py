"""Print searchable chunks generated from the local document registry."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag.chunking import chunks_as_json, chunk_registered_documents


def main() -> None:
    """Parse options and print registry-backed chunks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--overlap-chars", type=int, default=150)
    args = parser.parse_args()
    print(chunks_as_json(chunk_registered_documents(
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )))


if __name__ == "__main__":
    main()
