# What changed in phase 3 (October 2026) — in plain words

This round completed the parts of the Implementation Plan that were still open
on the `integration/stage4-backend-workspace` branch. Nothing that already
worked was rewritten; every change is covered by tests (89 pass).

## Stage 1 — reading documents (Mazin's area)

- **300 DPI rendering**, as the plan specifies (was about 216 DPI).
- **OpenCV clean-up for bad scans.** If a page reads poorly, the system cleans a
  copy (removes speckle, turns grey paper black-and-white, straightens tilted
  text) and keeps whichever reading is better. Clean PDFs are not touched.
  On simulated poor scans this took accuracy from 0% to 61%.
- **Real per-field confidence.** Each field now gets the OCR confidence of its
  own words, not one number for the whole page.
- **Optional PaddleOCR** second opinion (`OCR_SECOND_ENGINE=paddle`). Off by
  default because PaddlePaddle is a very large install; not tested here.
- The offline parser now reads labels whose colon OCR dropped ("Date Dec 08 2012").

## Stage 2 — reconciliation (Adham's area)

- **Jaro-Winkler ≥ 0.90** for company names (the plan's method), with a guard so
  "ABC Corp" and "ABC Corp India" are sent to a reviewer instead of auto-matched.
- **OCR-damaged order numbers still link** (lost hyphens, O/0, I/1 mix-ups).
- **Ledger postings without a reference** link only when exactly one invoice fits
  by amount and date; otherwise both are reported, never guessed.
- **Fewer duplicate questions.** When two invoices share an order number, the
  reviewer is asked once, not once per symptom.
- **Precision/recall are now measured** (`scripts/evaluate_reconciliation.py`)
  on the demo and on random benchmarks, including a hard version with OCR damage.

## Stage 3 — verification (Ayushi's area)

- **Tamper-evident audit log.** Each decision is fingerprinted with SHA-256 and
  chained to the previous one; editing or deleting a past decision outside the
  app is detected and shown on the Audit log screen.
- **Low-confidence review is decided on the fields that matter** (amount, date,
  reference). The threshold for those (0.60) was chosen by measuring outcomes
  (`scripts/calibrate_confidence.py`); 0.85 sent 31% of correct values to review.
- **New screens:** Cash runway, Settings, Evaluation.

## Stage 4 — analytics and forecasting (Prateek's area)

- **Quarterly** view, **vendor** spend, **configurable annual budgets**.
- **Cash runway**: linear-regression projection of the cash balance with an 85%
  range (needs the current balance, entered once in Settings).
- **Stricter forecast check**: besides the 6-month holdout, a rolling test from
  4 cut-off points. Revenue passes (10.6%); profit does not (36.9%) — reported.
- **Forecast snapshots**: every distinct forecast is stored with a fingerprint of
  the exact verified data it came from.
- **What-if** now shows the effect on the period's budget and on cash/runway.
- Revenue and expense forecasts can no longer go below zero (a bug the new
  end-to-end test found).

## Deployment

- Docker Compose now has the plan's **three tiers**: presentation (nginx),
  processing (API + pipeline) and data (volume), reachable from this machine only.
- **GitHub Actions** runs the tests, builds the images and smoke-tests the
  running stack on every push. (Docker could not be run where this work was done,
  so the first CI run is the first real Docker test — check its result.)

## Safety fixes

- `pipeline.py reset` and "load sample data" now **move the old database to
  `backups/`** instead of deleting it.
- The test suite used to reset whatever data folder `EVOSTRATEGY_DATA_DIR`
  pointed at. It now always uses a temporary folder.

## Honest results

See [EVALUATION.md](EVALUATION.md). In short: reconciliation meets its targets;
OCR meets its target on clean PDFs but not on poor scans; revenue and expense
forecasts meet the target, profit does not; review effort meets the 60% target
when 5–20% of records have problems, but not on the deliberately error-heavy
demo (57%). Forecasts are measured on the synthetic demo ledger, not real books.
