"""Measure all four implementation-plan hypotheses and write one honest report.

    H1  OCR & extraction accuracy      >= 92% field accuracy
    H2  Reconciliation                 precision >= 0.90, recall >= 0.88
    H3  Forecast accuracy              MAPE <= 15%
    H4  Human review efficiency        >= 60% less manual effort

Outputs
- evaluation_dataset/evaluation_results.json   (also served at GET /api/metrics)
- docs/EVALUATION.md                           (human-readable report)

Run:  python pipeline.py demo            # the forecast/efficiency numbers use it
      python scripts/evaluate_all.py [--quick] [--degraded]
      --quick     skip OCR (reuse the last extraction result if present)
      --degraded  also measure simulated poor scans (adds ~5 minutes)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analytics.aggregates import monthly_series  # noqa: E402
from analytics.efficiency import review_efficiency  # noqa: E402
from analytics.forecasting import MAPE_TARGET, forecast_series  # noqa: E402
from analytics.verified import verified_transactions  # noqa: E402
from reconciliation.orchestrator import reconcile_documents  # noqa: E402
from scripts import evaluate_extraction, evaluate_reconciliation  # noqa: E402
from storage import registry  # noqa: E402

RESULTS = ROOT / "evaluation_dataset" / "evaluation_results.json"
REPORT = ROOT / "docs" / "EVALUATION.md"


def _strip(report: dict) -> dict:
    return {k: v for k, v in report.items() if k != "rows"}


def extraction(quick: bool, degraded: bool) -> dict:
    previous = json.loads(RESULTS.read_text()).get("h1_extraction") if RESULTS.exists() else None
    if quick and previous:
        return previous
    results = [_strip(evaluate_extraction.evaluate())]
    if degraded:
        results.append(_strip(evaluate_extraction.evaluate(degraded=True, preprocess="off")))
        results.append(_strip(evaluate_extraction.evaluate(degraded=True, preprocess="auto")))
    elif previous:
        results += [r for r in previous.get("results", []) if "scans" in r.get("dataset", "")]
    return {"target": evaluate_extraction.TARGET, "results": results}


def forecasting() -> dict:
    series = monthly_series(verified_transactions())
    if len(series["months"]) < 3:
        return {"error": "Run `python pipeline.py demo` (or ingest data) first."}
    out = {"target_mape": MAPE_TARGET, "history_months": len(series["months"]),
           "period": [series["months"][0], series["months"][-1]], "metrics": {}}
    for metric in ("revenue", "expense", "profit"):
        result = forecast_series(series["months"], series[metric], horizon=6, non_negative=metric != "profit")
        holdout = (result.get("backtest") or {}).get("mape", {})
        rolling = (result.get("rolling_backtest") or {}).get("mape", {})
        out["metrics"][metric] = {
            "holdout_6m_mape": holdout,
            "rolling_3m_mape": rolling,
            "interval_coverage_85": (result.get("backtest") or {}).get("interval_coverage"),
            "meets_target_holdout": bool(holdout.get("ensemble") is not None and holdout["ensemble"] <= MAPE_TARGET),
            "meets_target_rolling": bool(rolling.get("ensemble") is not None and rolling["ensemble"] <= MAPE_TARGET),
        }
    return out


def efficiency() -> dict:
    demo = review_efficiency(registry.get_cases(), registry.get_transactions())
    curve = []
    for share in (0.05, 0.10, 0.20, 0.35):
        cases, transactions = [], []
        for seed in range(1, 6):
            docs, _ = evaluate_reconciliation.make_benchmark(seed, 60, problem_share=share)
            run = reconcile_documents(docs, use_llm=False)
            cases += run.cases
            transactions += run.transactions
        curve.append({"problem_share": share, **review_efficiency(cases, transactions)})
    return {"target": demo["target"], "demo": demo, "by_problem_rate": curve}


def write_markdown(results: dict) -> None:
    def yes(flag: bool) -> str:
        return "✅ meets" if flag else "❌ below"

    lines = [
        "# EvoStrategy — Evaluation Report",
        "",
        f"Generated {results['generated_at']} by `python scripts/evaluate_all.py`. "
        "Numbers are measured, not estimated; each section says what data it used and its limits.",
        "",
        "| Hypothesis | Target | Result | Status |",
        "|---|---|---|---|",
    ]
    h1 = results["h1_extraction"]["results"]
    for r in h1:
        lines.append(f"| H1 OCR & extraction — {r['dataset']} | ≥ 92% fields | {r['correct']}/{r['fields']} = {r['accuracy']:.1%} | {yes(r['meets_target'])} |")
    h2 = results["h2_reconciliation"]["results"]
    for r in h2:
        lines.append(f"| H2 Reconciliation — {r['dataset']} | P ≥ 0.90, R ≥ 0.88 | "
                     f"P {r['precision']:.3f} / R {r['recall']:.3f} | {yes(r['meets_target'])} |")
    h3 = results["h3_forecasting"]
    for metric, m in h3.get("metrics", {}).items():
        lines.append(f"| H3 Forecast — {metric} | MAPE ≤ 15% | 6-mo holdout {m['holdout_6m_mape'].get('ensemble')}%, "
                     f"rolling {m['rolling_3m_mape'].get('ensemble')}% | {yes(m['meets_target_holdout'] and m['meets_target_rolling'])} |")
    h4 = results["h4_review_efficiency"]
    lines.append(f"| H4 Review effort — demo dataset | ≥ 60% less | {h4['demo']['reduction']:.1%} | {yes(h4['demo']['meets_target'])} |")
    for point in h4["by_problem_rate"]:
        lines.append(f"| H4 Review effort — benchmark, ~{point['problem_share']:.0%} of orders with a problem | ≥ 60% less | "
                     f"{point['reduction']:.1%} | {yes(point['meets_target'])} |")
    lines += [
        "",
        "## H1 — OCR & extraction",
        "",
        "Fields checked: Order ID, invoice date and total on the 19 evaluation invoices "
        "(all one SuperStore template), offline rule parser, Tesseract 5.",
        "",
    ]
    for r in h1:
        lines.append(f"- **{r['dataset']}**: {r['correct']}/{r['fields']} = {r['accuracy']:.1%}")
    lines += [
        "",
        "Limits: one invoice layout and three fields, so 100% on clean PDFs says little about other "
        "layouts. The simulated poor scans (tilt, blur, noise, faded grey paper) show the OpenCV "
        "clean-up matters, and that light-grey labels on bad scans are still the weak point. "
        "Confidence threshold calibration: `scripts/calibrate_confidence.py`.",
        "",
        "## H2 — Reconciliation precision / recall",
        "",
        "Unit: one *issue* (e.g. “invoice X is not in the ledger”). Ground truth is defined independently "
        "of the engine — planted scenarios in `scripts/make_demo_data.py`, or randomly generated datasets.",
        "",
    ]
    for r in h2:
        lines.append(f"- **{r['dataset']}**: {r['genuine_issues']} genuine issues, {r['flagged']} flagged, "
                     f"{r['true_positives']} correct → precision {r['precision']:.3f}, recall {r['recall']:.3f}")
        if r.get("quality_flags"):
            lines.append(f"  - plus {r['quality_flags']} low-confidence OCR flags (strict precision "
                         f"{r['strict_precision']:.3f} if those count as false alarms)")
        examples = r.get("false_positive_examples") or r.get("false_positives")
        if examples:
            lines.append(f"  - false-positive examples: {', '.join(examples[:5])}")
    lines += [
        "",
        "Limits: the benchmark has no OCR noise in amounts and no vendor-name aliases; the HARD variant "
        "adds OCR-damaged identifiers and ledger postings without references. Most remaining errors are "
        "unreferenced postings whose amount or date is also wrong — reported as “not in ledger” instead "
        "of “mismatch” (still sent to a reviewer, but under the wrong label).",
        "",
        "## H3 — Forecast accuracy",
        "",
    ]
    if "error" in h3:
        lines.append(h3["error"])
    else:
        lines += [
            f"Verified monthly series, {h3['history_months']} months ({h3['period'][0]} to {h3['period'][1]}). "
            "**This history is the generated demo ledger** (`scripts/make_demo_data.py`: trend + seasonality + "
            "noise), so these numbers show the method works, not how it performs on a real company.",
            "",
            "| Series | Model | 6-month holdout MAPE | Rolling 3-month MAPE (4 origins) |",
            "|---|---|---|---|",
        ]
        for metric, m in h3["metrics"].items():
            for model in ("linear_regression", "arima", "ensemble"):
                lines.append(f"| {metric} | {model} | {m['holdout_6m_mape'].get(model)}% | {m['rolling_3m_mape'].get(model)}% |")
        lines += [
            "",
            "Profit is revenue minus expenses, so small profit months make percentage errors explode; "
            "forecasting it as revenue-forecast minus expense-forecast was tried and was no better. "
            "The plan's risk table anticipated missing the MAPE target on short or volatile history.",
        ]
    lines += [
        "",
        "## H4 — Human review efficiency",
        "",
        f"Method: {h4['demo']['method']}. {h4['demo']['caveat']}",
        "",
        f"- Demo dataset: {h4['demo']['documents_needing_reconciliation']} reconcilable documents, "
        f"{h4['demo']['documents_needing_a_human']} need a human → {h4['demo']['reduction']:.1%} less effort. "
        "The demo was built to exercise every failure path (10 problems among 19 invoices), far more than a real ledger.",
        "- Benchmark at different problem rates (5 random datasets × 60 orders each):",
    ]
    for point in h4["by_problem_rate"]:
        lines.append(f"  - ~{point['problem_share']:.0%} of orders with a problem → {point['reduction']:.1%} less effort")
    lines += [
        "",
        "Reading: the saving depends on how messy the books are. It passes 60% when 5–20% of orders have a problem "
        "and falls below it when a third of all records are wrong.",
        "",
    ]
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--degraded", action="store_true")
    parser.add_argument("--seeds", type=int, default=20)
    args = parser.parse_args()
    results = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "h1_extraction": extraction(args.quick, args.degraded),
        "h2_reconciliation": evaluate_reconciliation.evaluate(args.seeds),
        "h3_forecasting": forecasting(),
        "h4_review_efficiency": efficiency(),
    }
    RESULTS.write_text(json.dumps(results, indent=2, default=str))
    write_markdown(results)
    print(f"written {RESULTS.relative_to(ROOT)} and {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
