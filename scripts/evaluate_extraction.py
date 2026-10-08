"""Measure Stage 1 field-level extraction accuracy against ground truth.

Compares invoice number (Order ID), invoice date and total amount for every
PDF in evaluation_dataset/ against evaluation_dataset/ground_truth/*.json.
Target from the implementation plan: >= 92% field accuracy.

Run:  python scripts/evaluate_extraction.py              # clean PDFs
      python scripts/evaluate_extraction.py --degraded   # simulated poor scans,
                                                         # with and without OpenCV clean-up
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.schemas.contracts import SourceDocument  # noqa: E402
from ingestion.service import ingest_file  # noqa: E402
from reconciliation.normalization import normalize_amount, normalize_date, normalize_identifier  # noqa: E402

TARGET = 0.92
DATASET = ROOT / "evaluation_dataset"


_FOLD = str.maketrans({"1": "i", "!": "i", "|": "i", "l": "i", "0": "o"})


def _value(document: SourceDocument, *labels: str):
    """Value of the first field whose label is one of ``labels``.

    OCR look-alikes in the *label* ("Order 1D") are tolerated, as the
    downstream semantic mapper does; the *value* must still be exactly right.
    """
    wanted = {label.casefold().translate(_FOLD) for label in labels}
    for field in document.fields:
        if field.label.strip(" :;|").casefold().translate(_FOLD) in wanted and field.value is not None:
            return field.value
    return None


def degrade(pdf: Path, out_dir: Path, seed: int) -> Path:
    """Render a PDF and damage it like a cheap scan: tilt, blur, noise, faded contrast."""
    import cv2
    import fitz
    import numpy as np

    rng = np.random.default_rng(seed)
    page = fitz.open(pdf)[0]
    pix = page.get_pixmap(dpi=200)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY if pix.n == 3 else cv2.COLOR_RGBA2GRAY)
    height, width = gray.shape
    angle = float(rng.uniform(1.5, 3.5)) * (1 if seed % 2 else -1)
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    gray = cv2.warpAffine(gray, matrix, (width, height), borderValue=255)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = (gray.astype(np.float32) * 0.55 + 95).clip(0, 255)          # faded, grey paper
    gray = (gray + rng.normal(0, 22, gray.shape)).clip(0, 255).astype(np.uint8)
    path = out_dir / f"{pdf.stem}.png"
    cv2.imwrite(str(path), gray)
    return path


def evaluate(degraded: bool = False, preprocess: str = "auto") -> dict:
    rows, correct, total = [], 0, 0
    os.environ["OCR_PREPROCESS"] = preprocess
    scans = Path(tempfile.mkdtemp(prefix="evostrategy-scans-")) if degraded else None
    for index, truth_path in enumerate(sorted((DATASET / "ground_truth").glob("*.json"))):
        pdf = DATASET / "invoices" / f"{truth_path.stem}.pdf"
        if not pdf.exists():
            continue
        truth = json.loads(truth_path.read_text())
        source = degrade(pdf, scans, index) if scans else pdf
        document = ingest_file(source)[0]
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
    return {"dataset": ("simulated poor scans" if degraded else "clean PDFs") + f", OpenCV clean-up {preprocess}",
            "documents": len(rows), "fields": total, "correct": correct,
            "accuracy": round(accuracy, 4), "target": TARGET, "meets_target": accuracy >= TARGET, "rows": rows}


def print_report(report: dict) -> None:
    print(f"\n{report['dataset']}")
    for row in report["rows"]:
        misses = [name for name in ("invoice_number", "invoice_date", "total_amount") if row[name] == "MISS"]
        if misses:
            print(f"  {row['document']}: MISS {', '.join(misses)}  extracted={row['extracted']} truth={row['truth']}")
    print(f"  Field accuracy: {report['correct']}/{report['fields']} = {report['accuracy']:.1%} "
          f"(target {report['target']:.0%}) -> {'MEETS' if report['meets_target'] else 'BELOW'} target")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--degraded", action="store_true", help="also test simulated poor scans")
    args = parser.parse_args()
    print_report(evaluate())
    if args.degraded:
        print_report(evaluate(degraded=True, preprocess="off"))
        print_report(evaluate(degraded=True, preprocess="auto"))
