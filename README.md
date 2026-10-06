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
  -> Stage 1  OCR + source-faithful field extraction, with confidence
  -> Stage 2  semantic mapping -> normalization -> document linking -> reconciliation cases
  -> Stage 3  human review in the workspace: ACCEPT / REJECT / CORRECT, audited
  -> GATE     only reconciled or reviewed transactions continue
  -> Stage 4  verified analytics, budgets, forecasting (regression + ARIMA), what-if
```

Everything runs locally: SQLite + files, no cloud storage. An LLM is optional
(Gemini, or a local Ollama model); without one, an offline rule parser is used.

## Quick start

Prerequisites: Python 3.10+, Node 20+, and the Tesseract binary
(`brew install tesseract` / `sudo apt install tesseract-ocr`).

```bash
python3 -m venv venv && source venv/bin/activate
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

### With Docker (single workstation)

```bash
docker compose up --build              # http://localhost:8000
docker compose --profile ollama up --build   # + local LLM, no internet needed after model pull
```

Data persists in the `evostrategy-data` volume.

## Command line

```bash
python pipeline.py demo                       # build demo data and run it end to end
python pipeline.py run path/to/folder file.pdf  # ingest + reconcile
python pipeline.py reconcile                  # re-run Stage 2 over stored documents
python pipeline.py status                     # last run summary
python pipeline.py reset                      # wipe the local registry
python scripts/evaluate_extraction.py         # Stage 1 accuracy vs ground truth
pytest                                        # test suite
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `gemini`, `ollama`, `rules`, or `auto` (Gemini if a key is set, else rules) |
| `GEMINI_API_KEY` | — | Enables Gemini extraction and semantic-mapping fallback |
| `OLLAMA_MODEL` / `OLLAMA_URL` | — / `http://127.0.0.1:11434` | Local LLM extraction |
| `EVOSTRATEGY_DATA_DIR` | `data/processed` | Where the registry, page images and uploads live |
| `VITE_API_URL` | same origin in prod, `:8000` in dev | Frontend → API base URL |

Thresholds live in `utils/config.py`: amount tolerance 2%, date tolerance 7 days,
low-confidence threshold 0.85, forecast interval 85%.

## Stage by stage

### Stage 1 — Ingestion (`ingestion/`)

- `service.py` — `ingest_file(path)` for every supported type. PDFs are rendered
  at 3× (`pdf/`), OCR'd with Tesseract (`ocr/`, which also returns mean word
  confidence), and parsed by `extraction/dispatcher.py`.
- `extraction/llm_parser.py` (Gemini), `dispatcher.py` (Ollama + fallback),
  `rule_parser.py` (offline). Labels and values are kept exactly as printed.
- `tabular/tabular_reader.py` — each CSV/XLSX row becomes one source document.
- Field confidence = parser confidence × OCR confidence. Documents under 0.85 are
  escalated for review in Stage 2.
- Accuracy on `evaluation_dataset/`: **57/57 fields (100%)** with the offline
  parser, target ≥ 92%.

### Stage 2 — Reconciliation (`reconciliation/`)

- `orchestrator.py` — `reconcile_documents(sources)` runs the whole stage:
  `semantic_mapping` → `normalization` → `document_linking` (invoice ↔ PO /
  payment / ledger) + duplicate detection → field comparison → cases →
  transactions (groups of linked documents).
- Case types: `document_pair`, `duplicate_entry`, `missing_document`
  (invoice not in ledger, payment without invoice), `low_confidence_extraction`,
  `ambiguous_link`. Statuses: MATCHED, AUTO_RESOLVED, ESCALATED, MISSING.
- `storage/registry.py` persists documents, links, transactions, cases and the
  append-only review log. Reviewed statuses survive reruns.

### Stage 3 — Verification workspace (`evostrategy_frontend/`, `evostrategy_backend/`)

- Onboarding (welcome → upload → live processing → ready) and the workspace:
  Overview, Review queue, Documents, Audit log, Analytics, Forecast, What-if.
- Review queue shows both source documents side by side (original page image +
  extracted fields, with the compared fields highlighted). REJECT and CORRECT
  require a reason; every decision records reviewer, time and value.

### The gate (`analytics/verified.py`)

A transaction reaches analytics only if it is RECONCILED, SINGLE_SOURCE,
ACCEPTED or CORRECTED. PENDING_REVIEW and QUARANTINED (rejected) records are
excluded, and every analytics view states how many records it is built from.

### Stage 4 — Analytics & forecasting (`analytics/`)

- `aggregates.py` — monthly revenue/expense/profit, category and supplier
  breakdowns, budget consumption (default budget = prior year + 5%).
- `forecasting.py` — linear regression and AIC-selected (seasonal) ARIMA with
  85% intervals, averaged into an ensemble; a 6-month holdout backtest reports
  MAPE against the ≤ 15% target. Demo data: revenue ensemble MAPE ≈ 4.9%.
- `whatif.py` — volume, pricing (with elasticity), headcount, vendor
  consolidation and other cost levers applied to the baseline forecast; stored
  data is never modified.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/ingestion/jobs` | Upload files (multipart `files`) and start a job |
| GET | `/api/ingestion/jobs/{id}` | Job progress, log, failures, summary |
| POST | `/api/demo` | Reset and load the demo dataset |
| GET | `/api/summary` | Workspace summary (counts, rates, open cases) |
| GET | `/api/documents`, `/api/documents/{id}`, `/api/documents/{id}/pages/{n}` | Records and page images |
| GET | `/api/cases?status=open\|reviewed\|STATUS`, `/api/cases/{id}/detail` | Review queue and evidence |
| POST | `/api/cases/{id}/review` | `{action, reviewer, reason, field, corrected_value}` |
| GET | `/api/audit` | Reviewer decisions, newest first |
| GET | `/api/analytics/overview` | Verified analytics |
| GET | `/api/forecast?metric=revenue&horizon=6` | Forecast + backtest |
| POST | `/api/whatif` | Scenario simulation |

Interactive docs at `/docs` while the API is running.

## Demo dataset

`python scripts/make_demo_data.py` writes `data/demo/`: the 19 evaluation
invoices, 6 generated payment advices and a 33-month general ledger (CSV) with
planted discrepancies (4.5% posting error, 1% rounding, 3-day posting delay,
unposted invoices, duplicate order IDs, short payments, an orphan payment).

## Known limitations

- Single OCR engine (Tesseract); PaddleOCR dual-engine consensus and OpenCV
  preprocessing from the plan are not implemented yet.
- The offline rule parser does not extract line-item tables (the LLM path does).
- Reviewer identity is a name field, not authenticated login.
- Budgets default to prior year + 5% until configured per category.
- The Streamlit prototype in `dashboard/` is superseded by the React workspace.
