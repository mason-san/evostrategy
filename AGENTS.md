# AGENTS.md

## What this is

Python OCR pipeline (Stage 1) that extracts generic structured data from document PDFs via PyMuPDF → Tesseract → Gemini LLM document extraction → Pydantic validation (`DocumentExtraction`) → JSON output. Stage 1 preserves labels and values as they appear in the document without assuming document types or hardcoding business schemas.

## Prerequisites

- Python 3.10+ (uses `list[Path]` type hints)
- `pip install -r requirements.txt` after venv setup
- **Tesseract OCR** must be installed on the system (`brew install tesseract` on macOS) — pytesseract shells out to the `tesseract` binary
- **For LLM parser**: set `GEMINI_API_KEY` env var (free key from https://aistudio.google.com/apikey)

## Running

```bash
python pipeline.py demo          # full flow on the demo dataset
python pipeline.py run <paths>   # ingest + reconcile your own files
```

## Project structure

- `pipeline.py` — main entrypoint, orchestrates the full flow
- `ingestion/pdf/` — PDF → PNG rasterization (PyMuPDF, 3× resolution)
- `ingestion/ocr/` — Tesseract OCR text extraction
- `ingestion/extraction/llm_parser.py` — Gemini-based generic document parser (`parse_document_llm`)
- `ingestion/schemas/invoice_schema.py` — Pydantic `DocumentExtraction` model (generic container with `extra="allow"`)
- `utils/save_json.py` — writes `DocumentExtraction` to JSON (`save_document`)
- `data/processed/` — output images and extracted JSONs

## Team branches

Members work on separate branches: `mazin-ocr` (OCR/ingestion), `Adham-Reconcilation`, `Dashboard`, `prateek-analytic&forecasting`. Feature branches should target `mazin-ocr` for now.

## Integrated system (Phase 2+)

The repo now runs the full flow; see README.md for details.

- `pipeline.py` — CLI: `demo`, `run <paths>`, `reconcile`, `status`, `reset`
- `ingestion/service.py` — `ingest_file()` for PDF / images / DOCX / CSV / XLSX
- `ingestion/extraction/dispatcher.py` — Gemini, Ollama, or offline `rule_parser.py`
- `reconciliation/orchestrator.py` — `reconcile_documents()` chains mapping,
  normalization, linking, comparisons, cases and transactions
- `storage/registry.py` — SQLite: documents, links, transactions, cases, review log
- `analytics/` — `verified.py` (the reconciliation gate), `aggregates.py`,
  `forecasting.py` (regression + ARIMA + backtest), `whatif.py`
- `evostrategy_backend/` — FastAPI (`uvicorn evostrategy_backend.main:app`)
- `evostrategy_frontend/` — React workspace (`npm ci && npm run build`)
- Tests: `pytest` (tests/conftest.py isolates storage in a temp dir)

Rules that must hold: Stage 1 never renames or normalizes labels/values;
analytics only reads `analytics.verified.verified_transactions()`; reviewer
decisions are never overwritten by reruns.
