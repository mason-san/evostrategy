# EvoStrategy — Evaluation Report

Generated 2026-10-06 21:02 UTC by `python scripts/evaluate_all.py`. Numbers are measured, not estimated; each section says what data it used and its limits.

| Hypothesis | Target | Result | Status |
|---|---|---|---|
| H1 OCR & extraction — clean PDFs, OpenCV clean-up auto | ≥ 92% fields | 57/57 = 100.0% | ✅ meets |
| H1 OCR & extraction — simulated poor scans, OpenCV clean-up off | ≥ 92% fields | 0/57 = 0.0% | ❌ below |
| H1 OCR & extraction — simulated poor scans, OpenCV clean-up auto | ≥ 92% fields | 35/57 = 61.4% | ❌ below |
| H2 Reconciliation — demo (planted discrepancies, real OCR) | P ≥ 0.90, R ≥ 0.88 | P 1.000 / R 1.000 | ✅ meets |
| H2 Reconciliation — randomised benchmark (20 seeds x 40 orders) | P ≥ 0.90, R ≥ 0.88 | P 1.000 / R 1.000 | ✅ meets |
| H2 Reconciliation — randomised benchmark — HARD (OCR-damaged ids, ledger rows without ids) (20 seeds x 40 orders) | P ≥ 0.90, R ≥ 0.88 | P 0.963 / R 0.980 | ✅ meets |
| H3 Forecast — revenue | MAPE ≤ 15% | 6-mo holdout 4.87%, rolling 10.57% | ✅ meets |
| H3 Forecast — expense | MAPE ≤ 15% | 6-mo holdout 0.84%, rolling 2.1% | ✅ meets |
| H3 Forecast — profit | MAPE ≤ 15% | 6-mo holdout 12.8%, rolling 36.93% | ❌ below |
| H4 Review effort — demo dataset | ≥ 60% less | 56.8% | ❌ below |
| H4 Review effort — benchmark, ~5% of orders with a problem | ≥ 60% less | 83.2% | ✅ meets |
| H4 Review effort — benchmark, ~10% of orders with a problem | ≥ 60% less | 77.3% | ✅ meets |
| H4 Review effort — benchmark, ~20% of orders with a problem | ≥ 60% less | 74.4% | ✅ meets |
| H4 Review effort — benchmark, ~35% of orders with a problem | ≥ 60% less | 55.1% | ❌ below |

## H1 — OCR & extraction

Fields checked: Order ID, invoice date and total on the 19 evaluation invoices (all one SuperStore template), offline rule parser, Tesseract 5.

- **clean PDFs, OpenCV clean-up auto**: 57/57 = 100.0%
- **simulated poor scans, OpenCV clean-up off**: 0/57 = 0.0%
- **simulated poor scans, OpenCV clean-up auto**: 35/57 = 61.4%

Limits: one invoice layout and three fields, so 100% on clean PDFs says little about other layouts. The simulated poor scans (tilt, blur, noise, faded grey paper) show the OpenCV clean-up matters, and that light-grey labels on bad scans are still the weak point. Confidence threshold calibration: `scripts/calibrate_confidence.py`.

## H2 — Reconciliation precision / recall

Unit: one *issue* (e.g. “invoice X is not in the ledger”). Ground truth is defined independently of the engine — planted scenarios in `scripts/make_demo_data.py`, or randomly generated datasets.

- **demo (planted discrepancies, real OCR)**: 10 genuine issues, 12 flagged, 10 correct → precision 1.000, recall 1.000
  - plus 2 low-confidence OCR flags (strict precision 0.833 if those count as false alarms)
- **randomised benchmark (20 seeds x 40 orders)**: 426 genuine issues, 426 flagged, 426 correct → precision 1.000, recall 1.000
- **randomised benchmark — HARD (OCR-damaged ids, ledger rows without ids) (20 seeds x 40 orders)**: 401 genuine issues, 408 flagged, 393 correct → precision 0.963, recall 0.980
  - false-positive examples: not_in_ledger:inv-3-021, not_in_ledger:inv-5-036, not_in_ledger:inv-6-022, not_in_ledger:inv-6-025, not_in_ledger:inv-7-026

Limits: the benchmark has no OCR noise in amounts and no vendor-name aliases; the HARD variant adds OCR-damaged identifiers and ledger postings without references. Most remaining errors are unreferenced postings whose amount or date is also wrong — reported as “not in ledger” instead of “mismatch” (still sent to a reviewer, but under the wrong label).

## H3 — Forecast accuracy

Verified monthly series, 33 months (2011-01 to 2013-09). **This history is the generated demo ledger** (`scripts/make_demo_data.py`: trend + seasonality + noise), so these numbers show the method works, not how it performs on a real company.

| Series | Model | 6-month holdout MAPE | Rolling 3-month MAPE (4 origins) |
|---|---|---|---|
| revenue | linear_regression | 10.35% | 14.1% |
| revenue | arima | 9.78% | 9.27% |
| revenue | ensemble | 4.87% | 10.57% |
| expense | linear_regression | 0.7% | 2.4% |
| expense | arima | 1.89% | 1.88% |
| expense | ensemble | 0.84% | 2.1% |
| profit | linear_regression | 24.76% | 52.62% |
| profit | arima | 27.48% | 26.68% |
| profit | ensemble | 12.8% | 36.93% |

Profit is revenue minus expenses, so small profit months make percentage errors explode; forecasting it as revenue-forecast minus expense-forecast was tried and was no better. The plan's risk table anticipated missing the MAPE target on short or volatile history.

## H4 — Human review efficiency

Method: documents a reviewer must open vs. a fully manual cross-check of every reconcilable document. Counts documents, not reviewer minutes; a timed user study would be stronger evidence.

- Demo dataset: 37 reconcilable documents, 16 need a human → 56.8% less effort. The demo was built to exercise every failure path (10 problems among 19 invoices), far more than a real ledger.
- Benchmark at different problem rates (5 random datasets × 60 orders each):
  - ~5% of orders with a problem → 83.2% less effort
  - ~10% of orders with a problem → 77.3% less effort
  - ~20% of orders with a problem → 74.4% less effort
  - ~35% of orders with a problem → 55.1% less effort

Reading: the saving depends on how messy the books are. It passes 60% when 5–20% of orders have a problem and falls below it when a third of all records are wrong.
