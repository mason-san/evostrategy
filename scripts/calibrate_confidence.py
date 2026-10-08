"""Calibrate the low-confidence review threshold against real outcomes.

Implementation plan, week 10: "cross-validate OCR confidence scores against
reconciliation escalations to tune the 0.85 threshold".

For every key field (Order ID, Date, Total) of every evaluation invoice — clean
PDFs and simulated poor scans — this records the field's confidence and
whether the extracted value was actually correct. For each candidate threshold
it reports:

- caught      share of WRONG values that would be sent to review
- false alarm share of CORRECT values that would be sent to review

A good threshold catches most wrong values while raising few false alarms.
Fields that could not be read at all are always escalated ("Could not read")
and are listed separately.

Run:  python scripts/calibrate_confidence.py      (about 5 minutes)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.service import ingest_file  # noqa: E402
from reconciliation.normalization import normalize_amount, normalize_date, normalize_identifier  # noqa: E402
from scripts.evaluate_extraction import DATASET, _FOLD, degrade  # noqa: E402

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9)
KEYS = {"invoice_number": ("Order ID",), "invoice_date": ("Date",), "total_amount": ("Total", "Balance Due")}


def _field(document, labels):
    wanted = {label.casefold().translate(_FOLD) for label in labels}
    for field in document.fields:
        if field.label.strip(" :;|").casefold().translate(_FOLD) in wanted and field.value is not None:
            return field
    return None


def _correct(name: str, value, truth: dict) -> bool:
    if name == "invoice_number":
        return normalize_identifier(value).normalized_value == normalize_identifier(truth["invoice_number"]).normalized_value
    if name == "invoice_date":
        expected = datetime.strptime(truth["invoice_date"], "%d-%m-%Y").date().isoformat()
        return normalize_date(value).normalized_value == expected
    amount = normalize_amount(value).normalized_value
    return amount is not None and int(amount) == int(truth["total_amount"])


def collect() -> tuple[list[dict], int]:
    samples, unreadable = [], 0
    scans = Path(tempfile.mkdtemp(prefix="evostrategy-calibration-"))
    os.environ["OCR_PREPROCESS"] = "auto"
    for degraded in (False, True):
        for index, truth_path in enumerate(sorted((DATASET / "ground_truth").glob("*.json"))):
            pdf = DATASET / "invoices" / f"{truth_path.stem}.pdf"
            if not pdf.exists():
                continue
            truth = json.loads(truth_path.read_text())
            document = ingest_file(degrade(pdf, scans, index) if degraded else pdf)[0]
            for name, labels in KEYS.items():
                field = _field(document, labels)
                if field is None:
                    unreadable += 1
                    continue
                samples.append({"set": "scan" if degraded else "clean", "field": name,
                                "confidence": field.confidence or 0.0,
                                "correct": _correct(name, field.value, truth)})
    return samples, unreadable


def table(samples: list[dict]) -> list[dict]:
    wrong = [s for s in samples if not s["correct"]]
    right = [s for s in samples if s["correct"]]
    rows = []
    for threshold in THRESHOLDS:
        caught = sum(s["confidence"] < threshold for s in wrong)
        alarms = sum(s["confidence"] < threshold for s in right)
        rows.append({"threshold": threshold,
                     "caught": round(caught / len(wrong), 3) if wrong else None,
                     "false_alarm": round(alarms / len(right), 3) if right else None})
    return rows


if __name__ == "__main__":
    samples, unreadable = collect()
    wrong = [s for s in samples if not s["correct"]]
    print(f"{len(samples)} key fields read ({len(wrong)} wrong), {unreadable} unreadable (always escalated)")
    print("threshold  caught-wrong  false-alarm-on-correct")
    for row in table(samples):
        print(f"  {row['threshold']:.2f}      {row['caught']}          {row['false_alarm']}")
    out = ROOT / "evaluation_dataset" / "confidence_calibration.json"
    out.write_text(json.dumps({"samples": samples, "unreadable": unreadable, "table": table(samples)}, indent=1))
    print(f"\nwritten {out.relative_to(ROOT)}")
