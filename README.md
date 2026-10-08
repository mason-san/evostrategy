# EvoStrategy

Document Reconciliation Pipeline and Verified Revenue Intelligence System

## Team

- Mazin Moosa — OCR & Ingestion
- Adham — Reconciliation Engine
- Ayushi Rastogi — Verification Dashboard
- Prateek M Hulamani — Analytics & Forecasting

## What it does

```text
documents (PDF, scans, CSV/XLSX, DOCX)
  -> Stage 1  OCR + source-faithful field extraction, with per-field confidence
  -> Stage 2  semantic mapping -> normalization -> document linking -> reconciliation cases
  -> Stage 3  human review in the workspace: ACCEPT / REJECT / CORRECT, hash-chained audit
  -> GATE     only reconciled or reviewed transactions continue
  -> Stage 4  verified analytics, budgets, forecasting (regression + ARIMA), cash runway, what-if
```

Everything runs locally: SQLite + files, no cloud storage. An LLM is optional
(Gemini, or a local Ollama model); without one, an offline rule parser is used.

Documentation: [user guide for reviewers](docs/USER_MANUAL.md) ·
[data-flow diagrams](docs/DFD.md) · [evaluation report](docs/EVALUATION.md)

## Quick start

Prerequisites: Python 3.11+, Node 20+, and the Tesseract binary
(`brew install tesseract` / `sudo apt install tesseract-ocr` /
Windows: the UB-Mannheim installer, then add it to PATH).

```bash
python -m venv venv
source venv/bin/activate              # Windows: venv\Scripts\activate
pip install -r requirements.txt

# frontend (once, or after UI changes)
cd evostrategy_frontend && npm ci && npm run build && cd ..

# run the whole app (API + UI) on http://127.0.0.1:8000
uvicorn evostrategy_backend.main:app --port 8000
```

Open http://127.0.0.1:8000, click **Get started**, and either upload documents
or choose **Use a sample company's invoices, payments and ledger**.

For UI development with hot reload, run `npm run dev` in
`evostrategy_frontend/` (http://localhost:5173) alongside the API.

### With Docker (single workstation, three tiers)

```bash
docker compose up --build                     # http://localhost:8000
docker compose --profile ollama up --build    # + local LLM, no internet needed after the model pull
```

| Tier | Service | What it runs |
|---|---|---|
| Presentation | `presentation` | nginx serving the workspace, proxying `/api` |
| Processing | `processing` | FastAPI + OCR + reconciliation + analytics (no published port) |
| Data | `evostrategy-data` volume | SQLite registry, page images, uploads |

The UI is published on `127.0.0.1` only (this machine). The single image also
runs alone: `docker build -t evostrategy . && docker run -p 127.0.0.1:8000:8000 -v evostrategy-data:/data evostrategy`.
GitHub Actions (`.github/workflows/ci.yml`) builds both and smoke-tests them on every push.

## Command line

```bash
python pipeline.py demo                         # build demo data and run it end to end
python pipeline.py run path/to/folder file.pdf  # ingest + reconcile
python pipeline.py reconcile                    # re-run Stage 2 over stored documents
python pipeline.py status                       # last run summary
python pipeline.py reset                        # fresh registry (old one moved to backups/)

python scripts/evaluate_all.py [--degraded]     # all four hypotheses -> docs/EVALUATION.md
python scripts/evaluate_extraction.py [--degraded]   # H1 OCR accuracy (clean / poor scans)
python scripts/evaluate_reconciliation.py       # H2 precision / recall
python scripts/calibrate_confidence.py          # tune the low-confidence review threshold
pytest                                          # 89 tests (storage isolated in a temp dir)
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `gemini`, `ollama`, `rules`, or `auto` (Gemini if a key is set, else rules) |
| `GEMINI_API_KEY` | — | Enables Gemini extraction and semantic-mapping fallback |
| `ANTHROPIC_API_KEY` | — | Enables the Home-screen assistant (Claude + read-only tools over verified data, `assistant/`); put it in `.env` |
| `ASSISTANT_MODEL` | `claude-opus-5-5` | Default assistant model (also selectable in the UI) |
| `OLLAMA_MODEL` / `OLLAMA_URL` | — / `http://127.0.0.1:11434` | Local LLM extraction |
| `OCR_PREPROCESS` | `auto` | OpenCV clean-up: `auto` (only pages that read poorly), `always`, `off` |
| `OCR_SECOND_ENGINE` | — | `paddle` to add PaddleOCR agreement checks (needs `pip install paddleocr paddlepaddle`) |
| `EVOSTRATEGY_DATA_DIR` | `data/processed` | Where the registry, page images, uploads and backups live |
| `VITE_API_URL` | same origin in prod, `:8000` in dev | Frontend → API base URL |

Thresholds live in `utils/config.py`: amount tolerance 2%, date tolerance 7 days,
document confidence 0.85, key-field confidence 0.60 (calibrated), forecast interval 85%.
In-app settings (budgets, cash balance, headcount) are stored in the registry.

## Stage by stage

### Stage 1 — Ingestion (`ingestion/`)

- `service.py` — `ingest_file(path)` for every supported type. PDFs are rendered
  at 300 DPI (`pdf/`) and OCR'd with Tesseract (`ocr/tesseract_engine.py`), which
  returns per-word confidence. Pages that read poorly are re-read after OpenCV
  clean-up (`ocr/preprocess.py`: denoise, Otsu binarisation, projection-profile
  deskew) and the better reading is kept.
- `extraction/llm_parser.py` (Gemini), `dispatcher.py` (Ollama + fallback),
  `rule_parser.py` (offline; also reads known labels whose colon OCR lost).
  Labels and values are kept exactly as printed.
- Field confidence = parser confidence × the OCR confidence of *that field's own
  words* × a penalty when the optional second engine (`ocr/paddle_engine.py`) disagrees.
- `tabular/tabular_reader.py` — each CSV/XLSX row becomes one source document.

### Stage 2 — Reconciliation (`reconciliation/`)

- `orchestrator.py` — `reconcile_documents(sources)` runs the whole stage:
  `semantic_mapping` → `normalization` → `document_linking` (invoice ↔ PO /
  payment / ledger) + duplicate detection → field comparison → cases →
  transactions (groups of linked documents).
- Entity matching: Jaro-Winkler ≥ 0.90 (rapidfuzz) with a word-coverage guard
  (`entity_resolution.py`). Identifiers match through an OCR-tolerant key
  (`identifier_match_key`: separators, O/0, I/1). Ledger postings without a
  reference link only on a unique amount + date match.
- Case types: `document_pair`, `duplicate_entry`, `missing_document`,
  `low_confidence_extraction` (an amount, date or reference read below 0.60),
  `ambiguous_link`. Discrepancy types include numerical mismatch, missing
  document, entity alias and duplicate entry. Statuses: MATCHED, AUTO_RESOLVED,
  ESCALATED, MISSING. A ledger mismatch that is only a symptom of a duplicate
  invoice is folded into the duplicate case, so the reviewer is asked once.
- `storage/registry.py` persists documents, links, transactions, cases,
  settings, forecast snapshots and the review log. Reviewed statuses survive
  reruns; schema changes are additive only.

### Stage 3 — Verification workspace (`evostrategy_frontend/`, `evostrategy_backend/`)

- Onboarding (welcome → upload → live processing → ready) and the workspace:
  Overview, Review queue, Documents, Audit log, Analytics, Forecast, Cash runway,
  What-if, Evaluation, Settings.
- Review queue shows both source documents side by side (original page image +
  extracted fields, compared fields highlighted). REJECT and CORRECT require a
  reason; every decision records reviewer, time and value.
- The audit log is SHA-256 hash-chained (`verify_audit_chain`), so editing or
  deleting a past decision outside the app is detected and shown.

### The gate (`analytics/verified.py`)

A transaction reaches analytics only if it is RECONCILED, SINGLE_SOURCE,
ACCEPTED or CORRECTED. PENDING_REVIEW and QUARANTINED (rejected) records are
excluded, and every view states how many records it is built from, the period,
and whether the data is the generated demo company.

### Stage 4 — Analytics & forecasting (`analytics/`)

- `aggregates.py` — monthly revenue/expense/profit, category and vendor
  breakdowns, budget consumption (configured annual budget, else prior year + 5%).
- `finance.py` — quarterly series; cash runway: month-end cash rebuilt from a
  stated balance and verified cash flow, projected by linear regression with an
  85% interval; data-source labelling.
- `forecasting.py` — linear regression and AIC-selected (seasonal) ARIMA with
  85% intervals, averaged into an ensemble; 6-month holdout and rolling-origin
  backtests report MAPE against the ≤ 15% target. Revenue/expense never go below zero.
- `whatif.py` — volume, pricing (with elasticity), headcount, vendor
  consolidation and other cost levers applied to the baseline forecast, with the
  effect on P&L, the period's budget and cash/runway; stored data is never modified.
- `efficiency.py` — documents needing a human vs a fully manual cross-check.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingestion/jobs` | Upload files (multipart `files`) and start a job |
| GET | `/api/ingestion/jobs/{id}` | Job progress, log, failures, summary |
| POST | `/api/demo` | Fresh workspace with the demo dataset (previous one backed up) |
| GET | `/api/summary` | Workspace summary (counts, rates, open cases) |
| GET | `/api/documents`, `/api/documents/{id}`, `/api/documents/{id}/pages/{n}` | Records and page images |
| GET | `/api/cases?status=open\|reviewed\|STATUS`, `/api/cases/{id}/detail` | Review queue and evidence |
| POST | `/api/cases/{id}/review` | `{action, reviewer, reason, field, corrected_value}` |
| GET | `/api/audit`, `/api/audit/verify` | Reviewer decisions; hash-chain tamper check |
| GET | `/api/analytics/overview` | Verified analytics (monthly, quarterly, budgets, vendors) |
| GET | `/api/forecast?metric=revenue&horizon=6`, `/api/forecast/snapshots` | Forecast + backtests; stored forecasts |
| GET | `/api/runway` | Cash runway projection |
| POST | `/api/whatif` | Scenario simulation |
| GET / PUT | `/api/settings` | Budgets, cash balance, headcount |
| GET | `/api/metrics` | Latest evaluation report + live review efficiency |

Interactive docs at `/docs` while the API is running.

## Demo dataset

`python scripts/make_demo_data.py` writes `data/demo/`: the 19 evaluation
invoices, 6 generated payment advices and a 33-month general ledger (CSV) with
planted discrepancies (4.5% posting error, 1% rounding, 3-day posting delay,
unposted invoices, duplicate order IDs, short payments, an orphan payment).
The ledger and payments are **synthetic**; screens built from them say so.

## Evaluation (see [docs/EVALUATION.md](docs/EVALUATION.md))

| Hypothesis | Target | Measured |
|---|---|---|
| OCR & extraction | ≥ 92% | 100% clean PDFs (one layout); 61% simulated poor scans (0% without OpenCV) |
| Reconciliation | P ≥ 0.90, R ≥ 0.88 | demo 1.00/1.00; random 1.00/1.00; random with OCR damage 0.96/0.98 |
| Forecast | MAPE ≤ 15% | revenue 4.9% (holdout) / 10.6% (rolling); expense < 3%; **profit 12.8% / 36.9% — misses** |
| Review effort | ≥ 60% less | 57% on the error-heavy demo; 74–83% when 5–20% of orders have a problem |

Forecast numbers come from the synthetic demo ledger, not a real company.

## Known limitations

- Stage 1 accuracy is measured on one invoice template; poor scans with light
  grey labels remain weak. PaddleOCR is optional and was not tested here.
- The offline rule parser does not extract line-item tables (the LLM path does).
- Reviewer identity is a name field, not authenticated login; storage is not encrypted.
- spaCy NER is not used: names are compared with Jaro-Winkler + word coverage.
- Review efficiency is counted in documents, not timed with real reviewers.
- The Streamlit prototype in `dashboard/` is superseded by the React workspace.
