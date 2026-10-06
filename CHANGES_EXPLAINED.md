# EvoStrategy Changes Explained

## Overview

The recent work establishes the first Phase 2 integration layer for EvoStrategy.
Stage 1 still extracts document information generically and preserves source
labels and values. The new code adds the foundation needed to map those
extractions into comparison-ready transactions, reconcile related records, and
persist reconciliation cases locally.

The current flow is:

```text
PDF -> images -> OCR -> generic extraction
    -> canonical mapping/linking
    -> reconciliation
    -> local registry
```

The dashboard and verified analytics stages are not connected yet. They remain
next-phase integration work.

## Documentation

### `PHASE_2_IMPLEMENTATION.md`

This document records the Phase 2 objective and delivery sequence. It explains
the target flow, current implementation state, non-negotiable boundaries, and
remaining work for batch ingestion, linking, reconciliation, dashboard
verification, analytics, and deployment.

### `README.md`

The README now includes the integrated architecture:

```text
source documents -> generic extraction -> canonical mapping/linking
-> reconciliation -> human verification -> verified analytics/forecasting
```

It also clarifies that Stage 1 remains source-faithful and that normalization
and reconciliation happen downstream.

## Configuration and paths

### `utils/config.py`

Added a central configuration module containing:

- Repository root
- Raw document directory
- Processed data directory
- Rendered image directory
- Extracted JSON directory
- SQLite reconciliation registry path
- Default numeric tolerance of `2.0%`

This prevents individual modules from calculating their own project-relative
paths.

### `ingestion/pdf/pdf_to_image.py`

Updated PDF rendering to use `IMAGE_DIR` from the central configuration rather
than constructing the output path locally.

### `utils/save_json.py`

Updated JSON output to use `EXTRACTION_DIR` from central configuration. Existing
filename behavior is retained:

- `invoice-001.pdf` becomes `invoice-001.json`
- Documents without a source path use an generated fallback filename

## Shared ingestion and transaction contracts

### `ingestion/schemas/contracts.py`

Added versioned downstream data models:

#### `ExtractedField`

Represents one extracted label/value pair and includes:

- Field ID
- Original label
- Original value
- Source document ID
- Optional page
- Optional extraction confidence

#### `ExtractedTable`

Represents an extracted table and includes:

- Table ID
- Original headers
- Rows
- Source document ID
- Optional page

#### `SourceDocument`

Represents the durable Stage 1 output consumed by later stages. It includes:

- Contract version
- Document ID
- Source path
- Optional document type
- Extracted fields
- Extracted tables
- OCR text
- Pipeline version

#### `CanonicalTransaction`

Represents comparison-ready values while retaining references to the raw
extracted field IDs. It currently supports:

- Transaction ID
- Document ID
- Vendor
- Identifier
- Date
- Amount
- Currency
- Raw field references
- Mapping confidence

#### `source_document_from_extraction`

This adapter converts the existing generic `DocumentExtraction` model into the
shared `SourceDocument` contract. It does not rename or normalize the source
values.

## Canonical mapping and linking

### `normalization/mapper.py`

Added the first downstream normalization layer.

#### Label mapping

Known source labels are mapped to comparison concepts such as:

- Vendor
- Identifier
- Date
- Amount

The original extracted fields remain unchanged. Only the canonical view is
used for comparison.

#### Numeric parsing

Amount values can be converted from common strings such as:

```text
$1,250.50
INR 1,250
```

The original value remains available in the source extraction.

#### Mapping confidence

Confidence is calculated from the proportion of canonical concepts successfully
mapped.

#### Document linking

Two transactions are linked using:

1. Exact identifier match
2. Vendor match
3. Date match
4. Amount agreement within the configured tolerance

The function returns both a link decision and a confidence score.

## Reconciliation package

### `reconciliation/model.py`

Defines:

- `ReconciliationStatus`
  - `MATCHED`
  - `AUTO_RESOLVED`
  - `ESCALATED`
  - `MISSING`
- `ReconciliationResult`

`ReconciliationResult.as_dict()` produces a JSON-friendly result for storage or
future dashboard use.

### `reconciliation/config.py`

Provides field-specific tolerance lookup. The default is `2.0%`, with support
for future overrides such as:

```python
TOLERANCE_OVERRIDES = {
    "tax": 0.5,
}
```

### `reconciliation/comparator.py`

Provides two pure comparison functions.

#### `compare_numeric`

Handles:

- Exact numeric matches
- In-tolerance differences
- Over-tolerance differences
- Missing numeric values
- Invalid numeric types
- Zero-value baselines
- Difference percentage calculation

#### `compare_exact`

Handles identifiers and text values by trimming surrounding whitespace and
comparing case-insensitively. It does not perform fuzzy matching.

### `reconciliation/engine.py`

Orchestrates transaction-level reconciliation:

1. Attempts to link the two canonical transactions.
2. Escalates insufficiently linked records as `entity_mismatch`.
3. Compares vendor, identifier, date, and amount.
4. Adds link confidence to each result.

### `reconciliation/__init__.py`

Marks the reconciliation directory as an explicit Python package.

## Local persistence

### `storage/registry.py`

Adds a SQLite-backed reconciliation registry.

The registry contains:

#### `reconciliation_cases`

Stores:

- Case ID
- Transaction ID
- Current status
- JSON payload
- Update timestamp

#### `review_actions`

Provides a table for future reviewer actions such as ACCEPT, REJECT, and
CORRECT.

#### `init_registry`

Creates the required database and tables.

#### `upsert_cases`

Stores cases idempotently using `case_id` as the primary key. Reprocessing the
same case updates it instead of creating duplicate rows.

### `storage/__init__.py`

Marks the storage directory as an explicit Python package.

## Pipeline integration

### `pipeline.py`

The existing `process_document` flow remains responsible for:

1. PDF-to-image conversion
2. OCR
3. Generic Gemini extraction
4. Pydantic validation
5. JSON persistence

It now resolves input paths consistently and includes
`reconcile_extractions`, which adapts two Stage 1 extraction results into
canonical transactions and sends them through the reconciliation engine.

## Tests

### `tests/TESTING_1.py`

The first ingestion test file covers:

- Missing PDF error handling
- Multi-page PDF rendering
- Predictable page image names
- Multi-page OCR ordering

It generates a temporary PDF and does not require Gemini.

### `tests/TESTING_2.py`

The second test file covers the newly added folders:

- Numeric reconciliation statuses
- Missing and invalid numeric values
- Exact comparison behavior
- Tolerance configuration
- Result serialization
- Transaction-level reconciliation
- Entity mismatch escalation
- SQLite registry creation
- Idempotent case upserts
- JSON output path behavior
- Central repository path configuration

Both test files use Python's standard-library `unittest`, so they do not
require `pytest`.

## Running the tests

Run the ingestion tests:

```bash
./venv/bin/python -m unittest tests.TESTING_1 -v
```

Run the reconciliation, storage, and utility tests:

```bash
./venv/bin/python -m unittest tests.TESTING_2 -v
```

Run all current tests:

```bash
./venv/bin/python -m unittest discover -s tests -p 'TESTING_*.py' -v
```

The tests create temporary files and databases and remove them after execution.
They do not use the production processed-data directories.

## Validation completed

The following checks have passed:

- Python compilation for the added packages
- `TESTING_1`: 3 tests passed
- `TESTING_2`: 9 tests passed
- Extraction adapter to mapping/reconciliation smoke test
- SQLite registry smoke test
- Git diff formatting check

## Remaining work

The following pieces are not yet implemented:

- Batch ingestion
- Ground-truth extraction accuracy evaluation
- Fuzzy entity resolution
- Duplicate and ambiguous-link handling
- Full reconciliation case orchestration
- Migration of the dashboard from mock records
- Reviewer action persistence and verification gate
- Verified analytics and forecasting
- End-to-end deployment packaging

## Real reconciliation dashboard

The root [`dashboard/`](/Users/mazinmoosa/Desktop/evostrategy/dashboard) package
now provides a Streamlit dashboard for testing actual extracted JSON files.
It replaces the previous mock-only dashboard path for this integration slice.

- `dashboard/service.py` loads JSON files from the configured extraction
  directory, adapts them to shared contracts, runs the real reconciliation
  engine, and persists cases.
- `dashboard/app.py` lets a user select two extracted documents, run
  reconciliation, inspect comparison results and canonical values, and record
  ACCEPT, REJECT, or CORRECT review actions.
- Review actions are stored in the SQLite registry with reviewer, reason,
  corrected value, and timestamp.

Start it with:

```bash
./venv/bin/pip install -r requirements.txt
./venv/bin/streamlit run dashboard/app.py
```

Then open `http://localhost:8501`. Run `pipeline.py` first if the extraction
directory does not contain JSON files.
