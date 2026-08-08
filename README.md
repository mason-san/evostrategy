# EvoStrategy

Document Reconciliation Pipeline and Verified Revenue Intelligence System

## Team

- Mazin Moosa — OCR & Ingestion
- Adham — Reconciliation Engine
- Ayushi Rastogi — Verification Dashboard
- Prateek M Hulamani — Analytics & Forecasting

## OCR & Ingestion Module

This module is responsible for taking raw invoice PDFs, turning them into images, extracting text from those images using OCR, parsing the relevant invoice fields, validating that data, and saving it as JSON for downstream processing (downstream consumers not included in this repository).

Expected input format

- Raw invoice files are expected to be PDF files placed under `data/raw/invoices`.
- The current parser is designed to extract lines from OCR output that begin with:
  - `Invoice Number`
  - `Invoice Date`
  - `Total Amount`
- The parser does not inspect PDF structure directly; it relies on the OCR text containing those labels and values.

Limitations / TODO

- The parser is a simple line-prefix matcher and is fragile: it may miss fields if OCR output uses different labels, casing, separators, or places values on separate lines.
- TODO: Improve parsing robustness (e.g., use regex, fuzzy matching, key-value extraction, or a small rules engine) and add unit tests with representative OCR outputs.

What each script does

- `ingestion/pipeline.py`
  - Orchestrates the end-to-end ingestion flow.
  - Converts a PDF into images, runs OCR on those images, parses the OCR text into invoice fields, validates the invoice with the `Invoice` schema, and saves the result as JSON.
- `ingestion/pdf/pdf_to_image.py`
  - Opens a PDF file with PyMuPDF and renders each page as a PNG image.
  - Saves generated images to `data/processed/images`.
- `ingestion/ocr/tesseract_engine.py`
  - Loads each rendered image with Pillow and uses `pytesseract` to extract text.
  - Concatenates text from all pages into a single string.
- `ingestion/extraction/parser.py`
  - Parses the combined OCR text line-by-line.
  - Extracts `invoice_number`, `invoice_date`, and `total_amount` from lines that start with the expected labels.
  - Normalizes the `total_amount` value by stripping `£`, `%`, `INR`, and commas before converting it to an integer.
- `ingestion/schemas/invoice_schema.py`
  - Defines the `Invoice` data model using Pydantic.
  - Enforces that the parsed invoice contains `invoice_number`, `invoice_date`, and `total_amount`.
- `utils/save_json.py`
  - Serializes the validated `Invoice` object to JSON.
  - Writes output files to `data/processed/extracted` using the invoice number as the filename.
- `__init__.py` files in `ingestion/`, `ingestion/pdf/`, `ingestion/ocr/`, and `ingestion/extraction/`
  - These are package marker files and do not contain active logic.

How to run the ingestion step end-to-end

1. Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. Place raw invoice PDFs in `data/raw/invoices`.

3. Run the ingestion pipeline from the repository root:

```bash
python3 -m ingestion.pipeline
```

- Note: `ingestion/pipeline.py` currently has a hardcoded default input of `data/raw/invoices/invoice_001.pdf` in its `__main__` block. To process a different PDF, call `process_invoice("data/raw/invoices/<filename>.pdf")` or update the path in the script.

4. Expected output:

- Rendered invoice page images in `data/processed/images`
- Extracted invoice JSON files in `data/processed/extracted`
- A printed `Invoice` object on stdout when running `ingestion/pipeline.py` directly

OCR-specific dependencies

- `PyMuPDF` (`requirements.txt`) is used to render PDF pages as images.
- `Pillow` is used to open rendered PNG images before OCR.
- `pytesseract` is used to call Tesseract OCR on the rendered images (Python wrapper only).
- A system-level Tesseract binary must be installed separately for `pytesseract` to work; it is not provided by `requirements.txt`.
  - macOS (homebrew): `brew install tesseract`
  - Debian/Ubuntu: `sudo apt update && sudo apt install -y tesseract-ocr`

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt


Then:

```bash
git add .
git commit -m "Setup project structure and environment"
git push