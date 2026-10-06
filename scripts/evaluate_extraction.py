"""Measure Stage 1 field-level extraction accuracy against ground truth.

Compares invoice number (Order ID), invoice date and total amount for every
PDF in evaluation_dataset/ against evaluation_dataset/ground_truth/*.json.
Target from the implementation plan: >= 92% field accuracy.

Run:  python scripts/evaluate_extraction.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.schemas.contracts import SourceDocument  # noqa: E402
from ingestion.service import ingest_file  # noqa: E402
from reconciliation.normalization import normalize_amount, normalize_date, normalize_identifier  # noqa: E402

TARGET = 0.92
DATASET = ROOT / "evaluation_dataset"


def _value(document: SourceDocument, *labels: str):
    wanted = {label.casefold() for label in labels}
    for field in document.fields:
        if field.label.strip(" :").casefold() in wanted and field.value is not None:
            return field.value
    return None


def evaluate() -> dict:
    rows, correct, total = [], 0, 0
    for truth_path in sorted((DATASET / "ground_truth").glob("*.json")):
        pdf = DATASET / "invoices" / f"{truth_path.stem}.pdf"
        if not pdf.exists():
            continue
        truth = json.loads(truth_path.read_text())
        document = ingest_file(pdf)[0]
        extracted_id = normalize_identifier(_value(document, "Order ID")).normalized_value
        extracted_date = normalize_date(_value(document, "Date")).normalized_value
        extracted_total = normalize_amount(_value(document, "Total", "Balance Due")).normalized_value
        truth_date = datetime.strptime(truth["invoice_date"], "%d-%m-%Y").date().isoformat()
        checks = {
            "invoice_number": extracted_id == normalize_identifier(truth["invoice_number"]).normalized_value,
            "invoice_date": extracted_date == truth_date,
            # ground truth stores whole units (e.g. 50 for $50.10)
            "total_amount": extracted_total is not None and int(extracted_total) == int(truth["total_amount"]),
        }
        correct += sum(checks.values())
        total += len(checks)
        rows.append({
            "document": truth_path.stem,
            "method": document.model_extra.get("extraction_method"),
            **{name: "ok" if ok else "MISS" for name, ok in checks.items()},
            "extracted": [extracted_id, extracted_date, extracted_total],
            "truth": [truth["invoice_number"], truth_date, truth["total_amount"]],
        })
    accuracy = correct / total if total else 0.0
    return {"documents": len(rows), "fields": total, "correct": correct,
            "accuracy": round(accuracy, 4), "target": TARGET, "meets_target": accuracy >= TARGET, "rows": rows}


if __name__ == "__main__":
    report = evaluate()
    for row in report["rows"]:
        misses = [name for name in ("invoice_number", "invoice_date", "total_amount") if row[name] == "MISS"]
        print(f"{row['document']}: {'all fields correct' if not misses else 'MISS ' + ', '.join(misses)}"
              + (f"  extracted={row['extracted']} truth={row['truth']}" if misses else ""))
    print(f"\nField accuracy: {report['correct']}/{report['fields']} = {report['accuracy']:.1%} "
          f"(target {report['target']:.0%}) -> {'MEETS' if report['meets_target'] else 'BELOW'} target")
