"""Measure Stage 2 reconciliation precision and recall.

Target from the implementation plan: precision >= 0.90, recall >= 0.88.

Two evaluations, both with ground truth defined independently of the engine:

1. **Demo dataset** — the discrepancies planted by ``scripts/make_demo_data.py``
   (their list is read from that script's constants, not from engine output).
   Requires the demo to have been run: ``python pipeline.py demo``.

2. **Randomised benchmark** — synthetic invoices, ledger rows and payments
   generated in memory with random amount deviations (including values just
   above and below the 2% tolerance), date shifts, unposted invoices,
   duplicate invoices and orphan payments. Every seed is a fresh dataset.
   This skips OCR on purpose: it isolates the reconciliation logic.

What counts
- Unit of evaluation: one *issue* (e.g. "invoice X is not in the ledger",
  "ledger amount for invoice X differs beyond tolerance").
- A case "flags" an issue when it is left open for review (ESCALATED/MISSING).
- precision = flagged genuine issues / all flagged issues
- recall    = flagged genuine issues / all genuine issues
- Low-confidence-extraction flags are OCR quality warnings, not discrepancy
  claims; they are reported separately and counted in the "strict" precision.

Run:  python scripts/evaluate_reconciliation.py [--seeds 20]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ingestion.schemas.contracts import ExtractedField, SourceDocument  # noqa: E402
from reconciliation.orchestrator import reconcile_documents  # noqa: E402

PRECISION_TARGET = 0.90
RECALL_TARGET = 0.88
OPEN = {"ESCALATED", "MISSING"}
QUALITY_KINDS = {"low_confidence"}


# --------------------------------------------------------------------------- scoring

def issue_key(case: dict[str, Any]) -> tuple:
    """Translate a reconciliation case into the issue it claims."""
    docs = case.get("documents") or []
    types = {d["document_id"]: d["document_type"] for d in docs}
    ids = case["document_ids"]
    of_type = lambda kind: next((i for i in ids if types.get(i) == kind), None)  # noqa: E731
    kind = case.get("case_type")
    if kind == "missing_document":
        if of_type("PAYMENT"):
            return ("orphan_payment", of_type("PAYMENT"))
        return ("not_in_ledger", ids[0])
    if kind == "duplicate_entry":
        return ("duplicate", frozenset(ids))
    if kind == "low_confidence_extraction":
        return ("low_confidence", ids[0])
    if kind == "ambiguous_link":
        return ("ambiguous_link", frozenset(ids))
    if "LEDGER" in types.values() and of_type("INVOICE"):
        return ("ledger_mismatch", of_type("INVOICE"))
    if of_type("PAYMENT") and of_type("INVOICE"):
        return ("payment_mismatch", of_type("INVOICE"))
    return ("other", frozenset(ids))


def score(cases: list[dict[str, Any]], truth: set[tuple]) -> dict[str, Any]:
    flagged = {issue_key(case) for case in cases if case["status"] in OPEN}
    quality = {key for key in flagged if key[0] in QUALITY_KINDS}
    claims = flagged - quality
    tp = claims & truth
    fp = claims - truth
    fn = truth - claims
    precision = len(tp) / len(claims) if claims else 1.0
    recall = len(tp) / len(truth) if truth else 1.0
    strict = len(tp) / len(flagged) if flagged else 1.0
    return {
        "genuine_issues": len(truth),
        "flagged": len(flagged),
        "true_positives": len(tp),
        "false_positives": sorted(map(_show, fp)),
        "false_negatives": sorted(map(_show, fn)),
        "quality_flags": len(quality),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "strict_precision": round(strict, 4),
    }


def _show(key: tuple) -> str:
    kind, ref = key
    return f"{kind}:{','.join(sorted(ref)) if isinstance(ref, frozenset) else ref}"


# --------------------------------------------------------------------------- 1. demo dataset

def demo_truth() -> set[tuple]:
    """Genuine issues planted in the demo dataset, read from the generator."""
    from scripts import make_demo_data as demo

    truth: set[tuple] = set()
    for name, (factor, delay) in demo.LEDGER_ADJUSTMENTS.items():
        if abs(factor - 1) * 100 > 2.0 or delay > 7:
            truth.add(("ledger_mismatch", name))
    truth |= {("not_in_ledger", name) for name in demo.UNPOSTED}
    by_id: dict[str, list[str]] = {}
    for name, (order_id, _, _) in demo.INVOICES.items():
        by_id.setdefault(order_id, []).append(name)
    truth |= {("duplicate", frozenset(names)) for names in by_id.values() if len(names) > 1}
    for _, invoice, _, factor in demo.PAYMENTS:
        if abs(factor - 1) * 100 > 2.0:
            truth.add(("payment_mismatch", invoice))
    truth.add(("orphan_payment", "pay-2012-0450"))
    return truth


def evaluate_demo(db_path: Path | None = None) -> dict[str, Any] | None:
    from storage import registry
    from utils.config import REGISTRY_DB

    cases = registry.get_cases(db_path or REGISTRY_DB)
    if not cases:
        return None
    return {"dataset": "demo (planted discrepancies, real OCR)", **score(cases, demo_truth())}


# --------------------------------------------------------------------------- 2. randomised benchmark

def _doc(document_id: str, fields: dict[str, Any], title: str | None = None) -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        source_path=f"benchmark/{document_id}",
        fields=[
            ExtractedField(field_id=f"field-{i + 1}", label=label, value=value,
                           source_document_id=document_id, confidence=1.0)
            for i, (label, value) in enumerate(fields.items())
        ],
        ocr_text=title,
        source_name=document_id,
        extraction_confidence=0.95,
        low_confidence=False,
    )


def _ledger_row(index: int, posted: date, order_id: str, amount: float, *, kind: str = "Revenue",
                category: str = "B2B Orders", counterparty: str = "Business customer") -> SourceDocument:
    return _doc(f"ledger-row-{index:04d}", {
        "Date": posted.isoformat(), "Document Type": "Ledger", "Entry Type": kind,
        "Category": category, "Counterparty": counterparty, "Order ID": order_id,
        "Description": f"Posting {index}", "Amount": f"{amount:.2f}", "Currency": "USD",
    })


def _ocr_noise(rng: random.Random, value: str) -> str:
    """Realistic OCR damage to an identifier: lost hyphen, O/0 or I/1 swap, stray space."""
    choice = rng.randint(0, 2)
    if choice == 0 and "-" in value:
        cut = rng.choice([i for i, ch in enumerate(value) if ch == "-"][1:] or [value.index("-")])
        return value[:cut] + value[cut + 1:]
    if choice == 1:
        return value.replace("0", "O", 1) if "0" in value else value.replace("1", "I", 1)
    middle = len(value) // 2
    return value[:middle] + " " + value[middle:]


GENUINE_WEIGHT = 12 + 7 + 10 + 8      # big_amount, big_date, unposted, duplicate
HARMLESS_WEIGHT = 10 + 8              # small (in-tolerance) amount and date differences


def make_benchmark(seed: int, orders: int = 40, hard: bool = False,
                   problem_share: float | None = None) -> tuple[list[SourceDocument], set[tuple]]:
    """One random dataset and its ground-truth issue list.

    ``hard`` adds OCR-style damage to 15% of invoice identifiers and leaves the
    Order ID off 15% of ledger postings, so linking must fall back on amount,
    date and partial identifier evidence.
    """
    rng = random.Random(seed)
    # problem_share: roughly what fraction of orders carry a genuine problem
    clean_weight = 40 if problem_share is None else max(0.0, GENUINE_WEIGHT / problem_share - GENUINE_WEIGHT - HARMLESS_WEIGHT)
    docs: list[SourceDocument] = []
    truth: set[tuple] = set()
    ledger_index = 0
    used_ids: set[str] = set()

    def new_id() -> str:
        while True:
            value = f"BM-{2012 + rng.randint(0, 1)}-{rng.choice('ABCDEFGH')}{rng.choice('ABCDEFGH')}{rng.randint(1000000, 9999999)}-{rng.randint(40000, 41999)}"
            if value not in used_ids:
                used_ids.add(value)
                return value

    for n in range(orders):
        name = f"inv-{seed}-{n:03d}"
        order_id = new_id()
        issued = date(2012, 1, 1) + timedelta(days=rng.randint(0, 600))
        total = round(rng.uniform(15, 20000), 2)
        printed_id = _ocr_noise(rng, order_id) if hard and rng.random() < 0.15 else order_id
        docs.append(_doc(name, {"#": str(10000 + n), "Date": issued.strftime("%b %d %Y"),
                                "Balance Due": f"${total:,.2f}", "Total": f"${total:,.2f}",
                                "Order ID": printed_id}, "INVOICE"))
        scenario = rng.choices(
            ["clean", "small_amount", "big_amount", "small_date", "big_date", "unposted", "duplicate"],
            weights=[clean_weight, 10, 12, 8, 7, 10, 8],
        )[0]
        if scenario == "unposted":
            truth.add(("not_in_ledger", name))
        else:
            amount, posted = total, issued
            if scenario == "small_amount":
                amount = total * (1 + rng.choice((-1, 1)) * rng.uniform(0.001, 0.019))
            elif scenario == "big_amount":
                amount = total * (1 + rng.choice((-1, 1)) * rng.uniform(0.021, 0.20))
                truth.add(("ledger_mismatch", name))
            elif scenario == "small_date":
                posted = issued + timedelta(days=rng.randint(1, 7))
            elif scenario == "big_date":
                posted = issued + timedelta(days=rng.randint(10, 40))
                truth.add(("ledger_mismatch", name))
            ledger_id = "" if hard and rng.random() < 0.15 else order_id
            docs.append(_ledger_row(ledger_index, posted, ledger_id, round(amount, 2)))
            ledger_index += 1
        if scenario == "duplicate":
            copy = f"inv-{seed}-{n:03d}b"
            copy_total = round(total * rng.uniform(1.1, 3.0), 2)
            docs.append(_doc(copy, {"#": str(20000 + n), "Date": issued.strftime("%b %d %Y"),
                                    "Balance Due": f"${copy_total:,.2f}", "Total": f"${copy_total:,.2f}",
                                    "Order ID": order_id}, "INVOICE"))
            truth.add(("duplicate", frozenset({name, copy})))
        if scenario != "duplicate" and rng.random() < 0.4:
            payment_scenario = rng.choices(["exact", "small", "big"], weights=[60, 20, 20])[0]
            factor = {"exact": 1.0, "small": 1 - rng.uniform(0.001, 0.019), "big": 1 - rng.uniform(0.021, 0.25)}[payment_scenario]
            paid = issued + timedelta(days=rng.randint(5, 60))
            payment = f"pay-{seed}-{n:03d}"
            docs.append(_doc(payment, {"Payment ID": payment.upper(), "Payment Date": paid.strftime("%b %d %Y"),
                                       "Order ID": order_id, "Amount Paid": f"${total * factor:,.2f}",
                                       "Method": "Bank transfer"}, "PAYMENT ADVICE"))
            if payment_scenario == "big":
                truth.add(("payment_mismatch", name))

    for k in range(2):
        orphan = f"pay-{seed}-orphan{k}"
        docs.append(_doc(orphan, {"Payment ID": orphan.upper(), "Payment Date": "Dec 19 2012",
                                  "Order ID": new_id(), "Amount Paid": f"${rng.uniform(50, 5000):,.2f}",
                                  "Method": "Bank transfer"}, "PAYMENT ADVICE"))
        truth.add(("orphan_payment", orphan))

    # background postings with no order id (expenses), which must not create false links
    for k in range(30):
        docs.append(_ledger_row(ledger_index, date(2012, 1, 5) + timedelta(days=30 * (k % 20)), "",
                                round(rng.uniform(500, 40000), 2), kind="Expense",
                                category=rng.choice(["Office Rent", "Marketing", "Cloud & IT Services"]),
                                counterparty=rng.choice(["Coastal Properties Ltd", "Brightline Media", "Nimbus Cloud Pvt Ltd"])))
        ledger_index += 1
    return docs, truth


def benchmark(seeds: int = 20, orders: int = 40, hard: bool = False) -> dict[str, Any]:
    runs = []
    for seed in range(1, seeds + 1):
        docs, truth = make_benchmark(seed, orders, hard)
        result = reconcile_documents(docs, use_llm=False)
        runs.append(score(result.cases, truth))
    tp = sum(r["true_positives"] for r in runs)
    claims = sum(r["true_positives"] + len(r["false_positives"]) for r in runs)
    genuine = sum(r["genuine_issues"] for r in runs)
    examples_fp = [fp for r in runs for fp in r["false_positives"]][:10]
    examples_fn = [fn for r in runs for fn in r["false_negatives"]][:10]
    return {
        "dataset": f"randomised benchmark{' — HARD (OCR-damaged ids, ledger rows without ids)' if hard else ''} ({seeds} seeds x {orders} orders)",
        "genuine_issues": genuine,
        "flagged": claims,
        "true_positives": tp,
        "precision": round(tp / claims, 4) if claims else 1.0,
        "recall": round(tp / genuine, 4) if genuine else 1.0,
        "worst_seed_precision": min(r["precision"] for r in runs),
        "worst_seed_recall": min(r["recall"] for r in runs),
        "false_positive_examples": examples_fp,
        "false_negative_examples": examples_fn,
    }


def evaluate(seeds: int = 20) -> dict[str, Any]:
    results = [r for r in (evaluate_demo(), benchmark(seeds), benchmark(seeds, hard=True)) if r]
    for r in results:
        r["meets_target"] = r["precision"] >= PRECISION_TARGET and r["recall"] >= RECALL_TARGET
    return {"targets": {"precision": PRECISION_TARGET, "recall": RECALL_TARGET}, "results": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="print the raw JSON report")
    args = parser.parse_args()
    report = evaluate(args.seeds)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        for r in report["results"]:
            print(f"\n{r['dataset']}")
            print(f"  genuine issues {r['genuine_issues']}, flagged {r['flagged']}, correct {r['true_positives']}")
            print(f"  precision {r['precision']:.3f} (target {PRECISION_TARGET})  "
                  f"recall {r['recall']:.3f} (target {RECALL_TARGET})  -> {'MEETS' if r['meets_target'] else 'BELOW'} target")
            for label in ("false_positives", "false_positive_examples"):
                if r.get(label):
                    print(f"  false positives: {r[label]}")
            for label in ("false_negatives", "false_negative_examples"):
                if r.get(label):
                    print(f"  missed: {r[label]}")
            if r.get("quality_flags"):
                print(f"  + {r['quality_flags']} low-confidence OCR flags (strict precision {r['strict_precision']:.3f})")
