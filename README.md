# EvoStrategy

Local document reconciliation and verified revenue intelligence pipeline.

EvoStrategy reads your business documents (invoices, payments, purchase orders,
ledger postings), cross-checks them against each other, sends anything that does
not add up to a human for review, and only then builds analytics, forecasts, and
cash-runway projections from the verified numbers.

Everything runs on one machine: a SQLite registry, local file storage, optional
LLM extraction (Groq or Ollama), and an offline rule parser when no LLM is
configured. Nothing leaves your computer unless you explicitly enable a cloud
model.

```
documents (PDF, scans, CSV/XLSX, DOCX)
  -> Stage 1  OCR + field extraction, per-field confidence
  -> Stage 2  semantic mapping -> normalization -> document linking ->
              duplicate detection -> field comparison -> reconciliation cases
  -> Stage 3  human review workspace: ACCEPT / REJECT / CORRECT,
              SHA-256 hash-chained audit log
  -> GATE     only verified transactions reach analytics
  -> Stage 4  verified analytics, budgets, forecasting (regression + ARIMA),
              cash runway, what-if scenarios
```

The frontend is a React workspace served by the same FastAPI process; the API
is documented at `/docs` while running.

## Contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Docker](#docker)
- [Command line](#command-line)
- [Configuration](#configuration)
- [Stage by stage](#stage-by-stage)
- [API](#api)
- [Demo dataset](#demo-dataset)
- [Evaluation](#evaluation)
- [Known limitations](#known-limitations)

## What it does

**Stage 1 — Ingestion** (`ingestion/`)
Reads PDFs (rendered at 300 DPI and OCR'd with Tesseract), scanned images,
DOCX, and spreadsheets (one record per row). Extracts verbatim labels and
values with per-field confidence; poorly read pages get an OpenCV clean-up pass
and the better reading is kept. An optional second engine (PaddleOCR) can
disagree and lower confidence.

**Stage 2 — Reconciliation** (`reconciliation/`)
Maps fields to semantic roles, normalizes amounts/dates/entities, links related
documents (invoice ↔ PO / payment / ledger) with OCR-tolerant identifier keys
and Jaro-Winkler entity matching (>= 0.90), detects duplicates, compares
amounts (±2%), dates (±7 days) and counterparties, and produces cases
(MATCHED / AUTO_RESOLVED / ESCALATED / MISSING) grouped into transactions.

**Stage 3 — Verification workspace** (`evostrategy_frontend/`, `evostrategy_backend/`)
Review queue shows both source documents side by side with compared fields
highlighted. ACCEPT / REJECT / CORRECT each record reviewer, time, reason, and
(when correcting) the field and new value. Decisions survive re-runs and are
hash-chained so tampering outside the app is detectable.

**Stage 4 — Analytics & forecasting** (`analytics/`)
Monthly/quarterly revenue, expense, profit, category and vendor breakdowns,
budget consumption, ensemble forecasts (linear regression + AIC-selected ARIMA
with 85% intervals, holdout and rolling backtests), cash runway from a stated
balance, and what-if scenarios (volume, pricing, headcount, vendor
consolidation) that never modify stored data.

An optional AI assistant (`assistant/`, Groq) answers questions over
read-only tools against the verified data.

## Quick start

Prerequisites: Python 3.11+, Node 20+, and the Tesseract binary
(`brew install tesseract` / `sudo apt install tesseract-ocr` / Windows:
UB-Mannheim installer, then add it to PATH).

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

### Local RAG chunks

After ingestion, the first RAG step can be inspected without running OCR again:

```bash
python scripts/chunk_documents.py
python scripts/chunk_documents.py --max-chars 600 --overlap-chars 80
```

The command reads extracted `SourceDocument` payloads from the SQLite registry
and prints readable JSON chunks with deterministic IDs and source metadata.

To generate local embeddings for those chunks, configure Ollama with the
`nomic-embed-text` model and run:

```bash
ollama pull nomic-embed-text
python scripts/embed_chunks.py
```

The embedding command uses `/api/embed`, validates 768 dimensions, preserves
chunk IDs, and prints only a short vector preview.

### PostgreSQL + pgvector storage

Step 3 stores chunks and vectors in the local `rag_chunks` PostgreSQL table.
Set `RAG_DATABASE_URL` when using a non-default database, then initialize the
repeatable schema with:

```bash
docker run --name evo-pgvector \
  -e POSTGRES_DB=evostrategy -e POSTGRES_USER=evo -e POSTGRES_PASSWORD=evo_local_dev \
  -p 5433:5432 -d pgvector/pgvector:pg17
.venv/bin/python -c "from rag.storage import init_schema; init_schema()"
```

The schema includes a document lookup index and an HNSW cosine-distance index
on the 768-dimensional embedding column. Retrieval is intentionally not part
of this step.

Run ingestion explicitly after the schema is initialized:

```bash
.venv/bin/python -m rag.ingestion
.venv/bin/python -m rag.ingestion --document-id invoice_001_page_1
.venv/bin/python -m rag.retrieval "Which invoice has the highest total?"
.venv/bin/python -m rag.generation "Which invoice has the highest total?"
```

The command reads only documents already in the SQLite registry, then reports
inserted, updated, unchanged, failed, and stale-deleted chunks. It does not
run OCR or start automatically with the backend.

Generation uses the local `qwen3.5:9b` Ollama model over retrieved context:

```bash
.venv/bin/python -m rag.generation
```

For UI development with hot reload, run `npm run dev` in
`evostrategy_frontend/` (http://localhost:5173) alongside the API.

## Docker

```bash
docker compose up --build                     # http://localhost:8000
docker compose --profile ollama up --build    # + local LLM (no internet after the model pull)
```

Three tiers: `presentation` (nginx serving the UI, proxying `/api` on
127.0.0.1 only), `processing` (FastAPI + OCR + reconciliation + analytics), and
the `evostrategy-data` volume (SQLite registry, page images, uploads). The app
image also runs alone:

```bash
docker build -t evostrategy . && docker run -p 127.0.0.1:8000:8000 -v evostrategy-data:/data evostrategy
```

CI (`.github/workflows/ci.yml`) builds both images and smoke-tests them on
every push; the deploy workflow lives in `deploy/github-ci.yml`.

## Host the website with Ollama on Render

The repository includes [`render.yaml`](./render.yaml), which defines the
production shape for V1:

- `evostrategy`: the public FastAPI + React website, built from `Dockerfile`
- `evostrategy-ollama`: a private Ollama service on Render
- persistent disks for the SQLite/uploads data and the Ollama model files

The browser never connects to Ollama. The hosted backend connects to the
private Ollama service, so the same model works from any laptop or device
without installing Ollama locally.

### Render setup checklist

1. Push this repository to GitHub and make sure `render.yaml` is on the
   deployment branch.
2. In Render, choose **New → Blueprint**, select the GitHub repository, and
   apply the Blueprint. Keep both services in the same region.
3. Use a paid plan for both services. The Ollama model needs enough RAM for
   `llama3.1:8b`; if it fails to start or is too slow, select a larger plan or
   use a smaller tool-capable model and update `OLLAMA_MODEL` in both services.
4. In the `evostrategy` service, set `CORS_ORIGINS` to the generated public
   URL, for example `https://evostrategy.onrender.com`.
5. Deploy `evostrategy-ollama` first. Wait for `/api/tags` to become healthy and
   for the model pull to finish, then deploy/redeploy `evostrategy`.
6. Open the public URL and verify `/health`, the UI, the assistant model list,
   document ingestion, and the demo workflow.
7. Later, add a custom domain in Render. Update `CORS_ORIGINS` to that exact
   `https://` origin and redeploy.

Render's current pricing should be checked in the account before creating the
services. Expect two paid compute services plus disk storage: the web service,
the Ollama service sized for the model, roughly 10 GB for app data, and roughly
20 GB for the model disk. Render's pricing page currently lists persistent
disks at about $0.25/GB/month; bandwidth and plan pricing can change. A custom
domain is charged by its registrar. Render provides managed HTTPS for the
service domain/custom domain.

Do not expose the Ollama service publicly or put its private hostname in
frontend code. If Ollama is unavailable, ingestion falls back to the rules
parser and assistant requests report the provider error; this is intentional
and avoids silently inventing results.

## Command line

```bash
python pipeline.py demo                         # build demo data and run it end to end
python pipeline.py run path/to/folder file.pdf  # ingest + reconcile
python pipeline.py reconcile                    # re-run Stage 2 over stored documents
python pipeline.py status                       # last run summary
python pipeline.py reset                        # fresh registry (old one moved to backups/)
python scripts/chunk_documents.py              # render registered extractions as RAG chunks
python scripts/embed_chunks.py                 # embed registered chunks with Ollama
python -m rag.ingestion                        # ingest chunks + embeddings into PostgreSQL

python scripts/evaluate_all.py [--degraded]     # all four hypotheses -> docs/EVALUATION.md
python scripts/evaluate_extraction.py [--degraded]   # H1 OCR accuracy (clean / poor scans)
python scripts/evaluate_reconciliation.py       # H2 precision / recall
python scripts/calibrate_confidence.py          # tune the low-confidence review threshold
pytest                                          # tests run isolated in a temp dir
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `groq`, `ollama`, `rules`, or `auto` (Groq if a key is set, otherwise Ollama if `OLLAMA_MODEL` is set) |
| `GROQ_API_KEY` | — | Enables Groq extraction, semantic-mapping fallback, and the assistant |
| `ASSISTANT_MODEL` | `llama-3.3-70b-versatile` | Default Groq assistant model (also selectable in the UI) |
| `OLLAMA_MODEL` / `OLLAMA_URL` | — / `http://127.0.0.1:11434` | Local Ollama model and server; set `LLM_PROVIDER=ollama` to use it |
| `OCR_PREPROCESS` | `auto` | OpenCV clean-up: `auto` (only pages that read poorly), `always`, `off` |
| `OCR_SECOND_ENGINE` | — | `paddle` to add PaddleOCR agreement checks (`pip install paddleocr paddlepaddle`) |
| `EVOSTRATEGY_DATA_DIR` | `data/processed` | Where the registry, page images, uploads and backups live |
| `VITE_API_URL` | same origin in prod, `:8000` in dev | Frontend → API base URL |
| `CORS_ORIGINS` | localhost dev origins | Allowed CORS origins for the API |

Thresholds live in `utils/config.py`: amount tolerance 2%, date tolerance 7 days,
document confidence 0.85, key-field confidence 0.60 (calibrated), forecast
interval 85%. In-app settings (budgets, cash balance, headcount) are stored in
the registry.

## Stage by stage

### Stage 1 — Ingestion (`ingestion/`)

- `service.py` — `ingest_file(path)` for every supported type. PDFs are rendered
  at 300 DPI and OCR'd with Tesseract, returning per-word confidence. Pages that
  read poorly are re-read after OpenCV clean-up and the better reading is kept.
- `extraction/llm_parser.py` (Groq), `dispatcher.py` (Ollama + fallback),
  `rule_parser.py` (offline; reads known labels whose colon OCR lost). Labels and
  values are kept exactly as printed.
- Field confidence = parser confidence × the OCR confidence of that field's own
  words × a penalty when the optional second engine disagrees.
- `tabular/tabular_reader.py` — each CSV/XLSX row becomes one source document.

### Stage 2 — Reconciliation (`reconciliation/`)

- `orchestrator.py` — `reconcile_documents(sources)` runs the whole stage:
  semantic mapping → normalization → document linking + duplicate detection →
  field comparison → cases → transactions (groups of linked documents).
- Entity matching: Jaro-Winkler ≥ 0.90 (rapidfuzz) with a word-coverage guard.
  Identifiers match through an OCR-tolerant key. Ledger postings without a
  reference link only on a unique amount + date match.
- Case types: `document_pair`, `duplicate_entry`, `missing_document`,
  `low_confidence_extraction`, `ambiguous_link`. Statuses: MATCHED,
  AUTO_RESOLVED, ESCALATED, MISSING. A ledger mismatch that is only a symptom of
  a duplicate invoice is folded into the duplicate case.
- `storage/registry.py` persists documents, links, transactions, cases,
  settings, forecast snapshots and the review log. Reviewed statuses survive
  reruns; schema changes are additive only.

### Stage 3 — Verification workspace

- Onboarding and the workspace: Overview, Review queue, Documents, Audit log,
  Analytics, Forecast, Cash runway, What-if, Evaluation, Settings.
- Review queue shows both source documents side by side. REJECT and CORRECT
  require a reason; every decision records reviewer, time and value.
- The audit log is SHA-256 hash-chained, so editing or deleting a past decision
  outside the app is detected and shown.

### The gate (`analytics/verified.py`)

A transaction reaches analytics only if it is RECONCILED, SINGLE_SOURCE,
ACCEPTED or CORRECTED. PENDING_REVIEW and QUARANTINED records are excluded, and
every view states how many records it is built from, the period, and whether
the data is the generated demo company.

### Stage 4 — Analytics & forecasting (`analytics/`)

- `aggregates.py` — monthly revenue/expense/profit, category and vendor
  breakdowns, budget consumption (configured annual budget, else prior year +
  5%).
- `finance.py` — quarterly series; cash runway: month-end cash rebuilt from a
  stated balance and verified cash flow, projected by linear regression with an
  85% interval; data-source labelling.
- `forecasting.py` — linear regression and AIC-selected (seasonal) ARIMA with
  85% intervals, averaged into an ensemble; 6-month holdout and rolling-origin
  backtests report MAPE against the ≤ 15% target. Revenue/expense never go
  below zero.
- `whatif.py` — volume, pricing (with elasticity), headcount, vendor
  consolidation and other cost levers applied to the baseline forecast, with the
  effect on P&L, the period's budget and cash/runway; stored data is never
  modified.
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
| GET / POST / PATCH / DELETE | `/api/chats[/{id}]` | Assistant conversations (saved history) |
| GET / POST | `/api/assistant/status`, `/api/assistant/chat` | Questions over verified data |
| POST | `/api/reconcile`, `/api/reset` | Admin: re-run reconciliation, fresh registry |

Interactive docs at `/docs` while the API is running.

## Demo dataset

`python scripts/make_demo_data.py` writes `data/demo/`: 19 evaluation invoices,
6 generated payment advices and a 33-month general ledger with planted
discrepancies (posting error, rounding, posting delay, unposted invoices,
duplicate order IDs, short payments, an orphan payment). The ledger and payments
are synthetic; screens built from them say so.

## Evaluation (see [docs/EVALUATION.md](docs/EVALUATION.md))

Four hypotheses are measured end to end:

| Hypothesis | Target |
|---|---|
| H1 OCR & extraction | ≥ 92% field accuracy |
| H2 Reconciliation | precision ≥ 0.90, recall ≥ 0.88 |
| H3 Forecast | MAPE ≤ 15% |
| H4 Review effort | ≥ 60% less manual review |

Forecast numbers come from the synthetic demo ledger, not a real company. Refresh
the report with `python scripts/evaluate_all.py`.

## Known limitations

- Stage 1 accuracy is measured on one invoice template; poor scans with light
  grey labels remain weak. PaddleOCR is optional and untested here.
- The offline rule parser does not extract line-item tables (the LLM path does).
- Reviewer identity is a name field, not authenticated login; storage is not
  encrypted.
- spaCy NER is not used: names are compared with Jaro-Winkler + word coverage.
- Review efficiency is counted in documents, not timed with real reviewers.
