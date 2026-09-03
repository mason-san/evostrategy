# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based document processing pipeline (Stage 1) that extracts structured data from PDF documents using OCR and LLM-based generic field extraction. Labels and values are preserved exactly as they appear in the source document without assuming document type or forcing fixed business field schemas.

**Core flow**: PDF → images (PyMuPDF) → OCR text (Tesseract) → generic structured extractions (`parse_document_llm`) → Pydantic validation (`DocumentExtraction`) → JSON output

## Prerequisites

- Python 3.10+ (uses `list[Path]` type hints)
- System-level **Tesseract OCR** binary:
  - macOS: `brew install tesseract`
  - Ubuntu/Debian: `sudo apt install tesseract-ocr`
- For LLM parser: `GEMINI_API_KEY` environment variable (get free key from https://aistudio.google.com/apikey)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

For LLM parser support:
```bash
export GEMINI_API_KEY="your-key-here"
```

## Running the Pipeline

```bash
# Process a single document (currently hardcoded to invoice_012.pdf in pipeline.py)
python pipeline.py
```

## Architecture

### Pipeline Components

1. **PDF Rasterization** (`ingestion/pdf/pdf_to_image.py`)
   - Uses PyMuPDF to render PDF pages as PNG images at 3× resolution
   - Output: `data/processed/images/`

2. **OCR Text Extraction** (`ingestion/ocr/tesseract_engine.py`)
   - Runs Tesseract on rendered images via `pytesseract` wrapper
   - Concatenates multi-page text into single string

3. **Parsing** (`ingestion/extraction/llm_parser.py`)
   - **`llm_parser.py`**: Gemini-based generic document extraction with structured JSON output (requires `GEMINI_API_KEY`)
   - Implements signature: `parse_document_llm(text: str) -> dict`

4. **Validation** (`ingestion/schemas/invoice_schema.py`)
   - Pydantic `DocumentExtraction` model with `ConfigDict(extra="allow")`
   - Accepts arbitrary key-value pairs without assuming fixed business schemas

5. **Output** (`utils/save_json.py`)
   - Saves `DocumentExtraction` objects as JSON to `data/processed/extracted/`

## Data Directories

- `data/raw/invoices/`: Input PDF files
- `data/processed/images/`: Rendered PNG images (gitignored)
- `data/processed/extracted/`: Output JSON files (gitignored)

## Team Workflow

- **Active development branch**: `mazin-ocr` (OCR & ingestion)
- Other team branches: `Adham-Reconcilation`, `Dashboard`, `prateek-analytic&forecasting`
- Feature branches targeting OCR/ingestion should branch from and merge into `mazin-ocr`

## File Responsibilities Reference

| File | Purpose |
|------|---------|
| `pipeline.py` | Main entrypoint, orchestrates full processing flow |
| `ingestion/pdf/pdf_to_image.py` | PDF → PNG conversion |
| `ingestion/ocr/tesseract_engine.py` | Image → OCR text |
| `ingestion/extraction/llm_parser.py` | Gemini-based generic document parser |
| `ingestion/schemas/invoice_schema.py` | Generic `DocumentExtraction` Pydantic model |
| `utils/save_json.py` | JSON serialization |
