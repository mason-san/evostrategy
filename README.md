# EvoStrategy

Document Reconciliation Pipeline and Verified Revenue Intelligence System

## Team

- Mazin Moosa — OCR & Ingestion
- Adham — Reconciliation Engine
- Ayushi Rastogi — Verification Dashboard
- Prateek M Hulamani — Analytics & Forecasting

## Stage 1 — OCR & Document Ingestion Module

This module takes raw document PDFs (invoices, purchase orders, payment memos, ledgers, etc.), converts them into images, extracts text via OCR, performs generic structured field extraction using Google Gemini LLM, validates the data into a generic `DocumentExtraction` schema, and saves it as JSON for Stage 2 processing.

### Architecture Guidelines

Stage 1 operates under generic document extraction:
- Does NOT assume every document is an invoice.
- Does NOT rename or map fields into standardized business concepts (e.g. "Order ID" remains "Order ID").
- Preserves raw labels and values exactly as they appear in the source document.
- Produces a generic extraction contract (`DocumentExtraction`) with `extra="allow"`.

### What each script does

- `pipeline.py`
  - Orchestrates the end-to-end ingestion flow (`process_document`).
  - Renders PDF to images, extracts OCR text, calls `parse_document_llm`, creates `DocumentExtraction`, and saves JSON.
- `ingestion/pdf/pdf_to_image.py`
  - Opens PDF with PyMuPDF and renders page images at 3× resolution.
- `ingestion/ocr/tesseract_engine.py`
  - Uses `pytesseract` to extract OCR text from images.
- `ingestion/extraction/llm_parser.py`
  - Extracts structured document fields from OCR text using Google Gemini (`parse_document_llm`).
- `ingestion/schemas/invoice_schema.py`
  - Defines generic `DocumentExtraction` container model (`extra="allow"`).
- `utils/save_json.py`
  - Serializes `DocumentExtraction` to JSON (`save_document`).

### How to run Stage 1 pipeline

1. Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY="your-api-key"
```

2. Run the ingestion pipeline from the repository root:

```bash
python pipeline.py
```

3. Expected output:

- Rendered page images in `data/processed/images`
- Extracted generic document JSON files in `data/processed/extracted`