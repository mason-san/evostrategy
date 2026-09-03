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
# Run the pipeline on a single document (hardcoded to invoice_012.pdf in pipeline.py)
python pipeline.py
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
