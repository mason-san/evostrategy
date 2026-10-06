"""EvoStrategy pipeline: ingestion -> reconciliation -> (review) -> analytics.

Command line
    python pipeline.py demo                 # build demo data, reset, ingest and reconcile it
    python pipeline.py run <files/folders>  # ingest files/folders, then reconcile everything
    python pipeline.py reconcile            # re-run reconciliation over stored documents
    python pipeline.py reset                # delete the local registry
    python pipeline.py status               # print the latest run summary
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

from ingestion.schemas.contracts import CanonicalTransaction, SourceDocument, source_document_from_extraction
from ingestion.schemas.invoice_schema import DocumentExtraction
from ingestion.service import SUPPORTED_TYPES, ingest_file
from normalization.mapper import map_document
from reconciliation.engine import reconcile_transactions
from reconciliation.orchestrator import reconcile_documents
from storage import registry
from utils.config import DEMO_DATA_DIR, REGISTRY_DB
from utils.save_json import save_document

ProgressCallback = Callable[[str, int, int], None]


def collect_files(paths: Iterable[Path | str]) -> list[Path]:
    """Expand folders into supported files, in a stable order."""
    files: list[Path] = []
    for item in paths:
        path = Path(item).expanduser().resolve()
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_TYPES))
        elif path.is_file():
            files.append(path)
        else:
            raise FileNotFoundError(path)
    return files


def ingest_paths(
    paths: Iterable[Path | str],
    *,
    db_path: Path = REGISTRY_DB,
    progress: ProgressCallback | None = None,
) -> tuple[list[SourceDocument], list[dict]]:
    """Stage 1 over many files. Failures are recorded per file, never hidden."""
    files = collect_files(paths)
    documents: list[SourceDocument] = []
    failures: list[dict] = []
    for index, path in enumerate(files):
        if progress:
            progress(path.name, index, len(files))
        try:
            extracted = ingest_file(path)
        except Exception as error:  # noqa: BLE001 - reported to the caller
            failures.append({"file": path.name, "error": str(error)})
            continue
        documents.extend(extracted)
        registry.upsert_documents([doc.model_dump() for doc in extracted], db_path)
    if progress:
        progress("", len(files), len(files))
    return documents, failures


def run_reconciliation(db_path: Path = REGISTRY_DB) -> dict:
    """Stage 2 over every stored document; persists cases, links, transactions."""
    sources = [SourceDocument(**payload) for payload in registry.get_documents(db_path)]
    result = reconcile_documents(sources)
    registry.replace_run_results(
        cases=result.cases,
        links=result.links,
        transactions=result.transactions,
        summary=result.summary,
        db_path=db_path,
    )
    return result.summary


def run_demo(db_path: Path = REGISTRY_DB, progress: ProgressCallback | None = None) -> dict:
    """Rebuild the demo dataset and run it end to end on a fresh registry."""
    from scripts.make_demo_data import main as build_demo

    build_demo()
    registry.reset_registry(db_path)
    _, failures = ingest_paths([DEMO_DATA_DIR], db_path=db_path, progress=progress)
    summary = run_reconciliation(db_path)
    return {**summary, "failures": failures}


# --------------------------------------------------------------------------- legacy helpers

def process_document(pdf_path: str) -> DocumentExtraction:
    """Process one PDF through Stage 1 and save its JSON (original entry point)."""
    source = ingest_file(Path(pdf_path))[0]
    extraction = DocumentExtraction(
        fields=[field.model_dump() for field in source.fields],
        tables=[table.model_dump() for table in source.tables],
    )
    save_document(extraction, pdf_path)
    return extraction


def reconcile_extractions(
    left: DocumentExtraction,
    left_path: str,
    right: DocumentExtraction,
    right_path: str,
) -> list[dict]:
    """Map two Stage 1 results and reconcile them through the simple engine."""
    left_source = source_document_from_extraction(Path(left_path).stem, left_path, left)
    right_source = source_document_from_extraction(Path(right_path).stem, right_path, right)
    left_transaction: CanonicalTransaction = map_document(left_source)
    right_transaction: CanonicalTransaction = map_document(right_source)
    return reconcile_transactions(left_transaction, right_transaction)


# --------------------------------------------------------------------------- CLI

def _print_progress(name: str, index: int, total: int) -> None:
    if name:
        print(f"[{index + 1}/{total}] {name}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="ingest files/folders and reconcile")
    run.add_argument("paths", nargs="+")
    sub.add_parser("reconcile", help="re-run reconciliation over stored documents")
    sub.add_parser("demo", help="load the bundled demo dataset end to end")
    sub.add_parser("reset", help="delete the local registry")
    sub.add_parser("status", help="show the latest run summary")
    args = parser.parse_args(argv)

    if args.command == "run":
        _, failures = ingest_paths(args.paths, progress=_print_progress)
        summary = {**run_reconciliation(), "failures": failures}
    elif args.command == "reconcile":
        summary = run_reconciliation()
    elif args.command == "demo":
        summary = run_demo(progress=_print_progress)
    elif args.command == "reset":
        registry.reset_registry()
        summary = {"reset": str(REGISTRY_DB)}
    else:
        summary = registry.get_last_run() or {"message": "No runs yet."}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
