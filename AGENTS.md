# AGENTS.md

## What this is

Python OCR pipeline that extracts structured invoice data (number, date, total) from PDF invoices via PyMuPDF → Tesseract → regex parsing → Pydantic validation → JSON output. Also has an evaluation system that compares pipeline output against ground-truth JSONs.

## Prerequisites

- Python 3.10+ (uses `list[Path]` type hints)
- `pip install -r requirements.txt` after venv setup
- **Tesseract OCR** must be installed on the system (`brew install tesseract` on macOS) — pytesseract shells out to the `tesseract` binary

## Running

```bash
# Run the pipeline on a single invoice (hardcoded to invoice_012.pdf)
python pipeline.py

# Run evaluation comparing both parsers against all ground-truth invoices
python evaluation/run_evaluation.py
```

## Project structure

- `pipeline.py` — main entrypoint, orchestrates the full flow
- `ingestion/pdf/` — PDF → PNG rasterization (PyMuPDF, 3× resolution)
- `ingestion/ocr/` — Tesseract OCR text extraction
- `ingestion/extraction/regex_parser.py` — regex-based parser (active in pipeline); `parser.py` — keyword-based parser (used in evaluation comparison)
- `ingestion/schemas/invoice_schema.py` — Pydantic `Invoice` model (3 fields)
- `evaluation/evaluator.py` — parser-agnostic evaluation functions; accepts any `parser_fn: (str) -> dict`
- `evaluation/run_evaluation.py` — runs both parsers, prints per-parser accuracy and comparison table
- `utils/save_json.py` — writes Invoice to JSON
- `data/processed/` — output images and extracted JSONs
- `evaluation_dataset/invoices/` — 19 eval PDFs; `evaluation_dataset/ground_truth/` — matching JSONs

## Known bugs / gotchas

- **No linting, formatting, type-checking, or test framework** exists — no commands to run
- `parser.py` is used only for evaluation comparison; `regex_parser.py` is the active pipeline parser

## Team branches

Members work on separate branches: `mazin-ocr` (OCR/ingestion), `Adham-Reconcilation`, `Dashboard`, `prateek-analytic&forecasting`. Feature branches should target `mazin-ocr` for now.
