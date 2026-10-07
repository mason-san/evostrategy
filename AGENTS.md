# AGENTS.md

## Project overview

EvoStrategy is a four-stage, locally deployed system: document ingestion/OCR →
cross-document reconciliation → human verification → verified analytics,
forecasting, cash runway and what-if. See README.md (overview, commands, API),
docs/DFD.md (data flow), docs/EVALUATION.md (measured results) and
docs/USER_MANUAL.md (reviewer guide).

## Setup and run

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt                    # needs the Tesseract binary on PATH
cd evostrategy_frontend && npm ci && npm run build && cd ..
uvicorn evostrategy_backend.main:app --port 8000   # API + UI on http://127.0.0.1:8000
python pipeline.py demo                            # or load the demo from the UI
pytest                                             # 89 tests, storage isolated in a temp dir
```

Optional: `GEMINI_API_KEY` or `LLM_PROVIDER=ollama` for LLM extraction (default
offline rule parser); `OCR_SECOND_ENGINE=paddle` for PaddleOCR agreement checks.

## Code map

| Path | Purpose |
|---|---|
| `pipeline.py` | CLI: `demo`, `run <paths>`, `reconcile`, `status`, `reset` |
| `ingestion/service.py` | `ingest_file()` for PDF / images / DOCX / CSV / XLSX |
| `ingestion/pdf/`, `ingestion/ocr/` | 300 DPI rendering; Tesseract with word confidences; OpenCV clean-up (`preprocess.py`); optional PaddleOCR (`paddle_engine.py`) |
| `ingestion/extraction/` | `dispatcher.py` chooses Gemini / Ollama / offline `rule_parser.py`; per-field confidence |
| `reconciliation/orchestrator.py` | `reconcile_documents()`: mapping, normalization, linking, duplicates, comparisons, cases, transactions |
| `reconciliation/entity_resolution.py` | Jaro-Winkler ≥ 0.90 + word-coverage guard |
| `storage/registry.py` | SQLite: documents, links, transactions, cases, hash-chained review log, settings, forecast snapshots |
| `analytics/verified.py` | The reconciliation gate — the only input to Stage 4 |
| `analytics/` | `aggregates.py`, `finance.py` (quarterly, runway), `forecasting.py`, `whatif.py`, `efficiency.py` |
| `evostrategy_backend/` | FastAPI (`main.py`), read models (`workspace.py`), ingestion jobs |
| `evostrategy_frontend/` | React + Vite workspace (`Workspace.tsx`, `Finance.tsx`) |
| `scripts/` | demo data, evaluations (`evaluate_all.py`), confidence calibration |
| `dashboard/` | earlier Streamlit prototype, superseded by the React workspace |

## Rules that must hold

- Stage 1 never renames or normalizes labels/values; meaning is assigned in Stage 2.
- Analytics, forecasts, runway and what-if read only `analytics.verified.verified_transactions()`.
- Reviewer decisions are never overwritten by reruns; the review log is append-only and hash-chained.
- Schema changes are additive (CREATE IF NOT EXISTS / ADD COLUMN); `reset` backs the old registry up.
- Tests must never touch a real data directory (`tests/conftest.py` forces a temp dir).
- Report metrics honestly: say which dataset (demo/synthetic vs real) a number comes from.

## Team branches

`main` / `mazin-ocr` (Stage 1 baseline), `Adham-Reconcilation`, `Dashboard`,
`prateek-analytic&forecasting`, and `integration/stage4-backend-workspace`
(the integrated system). Do not merge into `main` without the team's agreement.
