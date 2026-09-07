# Reconciliation Engine Explanation

## Purpose

EvoStrategy is a document-reconciliation pipeline for invoice data. The
`reconciliation/` package contains the comparison layer: it receives two
already-extracted and already-mapped values, compares them, and returns a
structured result for logging or review.

It deliberately does not know how values were obtained. PDF conversion, OCR,
invoice parsing, and the verification dashboard are separate parts of the
repository.

> The repository directory is named `reconciliation/` (not
> `reconiliation/`).

## Where the engine fits

The intended flow is:

```text
Invoice PDF
    -> PDF-to-image conversion (`ingestion/pdf/pdf_to_image.py`)
    -> Tesseract OCR (`ingestion/ocr/tesseract_engine.py`)
    -> Invoice field parsing (`ingestion/extraction/parser.py`)
    -> Field mapping
    -> Reconciliation comparisons (`reconciliation/`)
    -> Audit log / verification dashboard
```

The reconciliation code is currently a small, pure-Python rules layer. It
does not perform file I/O, database access, OCR, or dashboard rendering.

## Technologies used

### In the reconciliation engine

- **Python**: The engine is implemented with ordinary Python modules and
  relative imports.
- **`dataclasses`**: `ReconciliationResult` provides a compact typed data
  container with generated initialization and representation behavior.
- **`enum.Enum`**: `ReconciliationStatus` restricts outcomes to the defined
  status values while also behaving like a string enum.
- **`typing`**: `Optional` and `Union` describe values that may be missing or
  may be either strings or numbers.
- **No external runtime dependency**: The reconciliation files themselves
  use only Python's standard library plus their own modules.

### In the surrounding pipeline

These technologies feed or consume the engine but are not imported by the
reconciliation modules:

- **PyMuPDF (`fitz`)**: Converts PDF pages into high-resolution PNG images.
- **Pillow (`PIL.Image`)**: Opens source images for OCR.
- **Tesseract via `pytesseract`**: Extracts text from invoice images.
- **Streamlit**: Provides the verification dashboard where review actions can
  be taken.
- **SQLite**: Used by the dashboard audit log to persist reviewer actions.
- **NumPy, OpenCV, and `asarPy`**: Listed in the root dependency file, but
  they are not used by the files currently present in `reconciliation/`.

## Files in `reconciliation/`

### `model.py`

Defines the engine's shared result contract.

#### `ReconciliationStatus`

The string enum contains four possible outcomes:

- `MATCHED`: The values are equal.
- `AUTO_RESOLVED`: The values differ, but only within the configured
  tolerance.
- `ESCALATED`: The difference is larger than the allowed tolerance, or an
  exact string comparison fails.
- `MISSING`: One or both values were not supplied.

#### `ReconciliationResult`

This dataclass stores the result of a comparison:

- `status`: The `ReconciliationStatus` outcome.
- `field`: The field name being compared.
- `left_value` and `right_value`: The original values.
- `difference`: The absolute numeric difference, when applicable.
- `difference_percent`: The rounded percentage difference, when applicable.
- `discrepancy_type`: A human-readable classification, when a discrepancy
  exists.

`as_dict()` converts the result into a JSON/log-friendly dictionary. The enum
is converted to its string value so the result can be persisted or passed to
the dashboard/audit layer.

### `config.py`

Stores numeric comparison tolerance settings separately from comparison logic.

- `DEFAULT_TOLERANCE_PERCENT` is `2.0`, meaning a numeric difference of up to
  2% can be auto-resolved.
- `TOLERANCE_OVERRIDES` is a dictionary for field-specific thresholds. It is
  currently empty, but could contain values such as a tighter GST tolerance.
- `get_tolerance(field)` returns a field override when present, otherwise the
  default.

Keeping this configuration separate means thresholds can be tuned without
rewriting the comparator.

### `discrepancy.py`

Contains the pure decision rules used after a numeric percentage difference
has been calculated.

#### `determine_status(difference_percent, tolerance)`

Returns:

1. `MATCHED` when the difference is exactly `0`.
2. `AUTO_RESOLVED` when the difference is greater than `0` but no greater than
   the tolerance.
3. `ESCALATED` when the difference exceeds the tolerance.

#### `classify_discrepancy(field, difference_percent, tolerance)`

Returns a label for a non-matching numeric comparison:

- `rounding_variance` when the difference is within tolerance.
- `major_amount_mismatch` when the difference is more than five times the
  tolerance.
- `amount_mismatch` for other over-tolerance differences.

The `field` argument is accepted for future field-specific classifications,
but the current implementation does not use it.

### `comparator.py`

Provides the public comparison functions.

#### `compare_numeric(field, left, right)`

This function:

1. Returns `MISSING` with `missing_value` if either input is `None`.
2. Calculates the absolute difference using `abs(left - right)`.
3. Calculates a percentage difference using the right-hand value as the
   baseline.
4. Avoids division by zero by using the non-zero value, or `1` when both
   values are zero.
5. Gets the field tolerance from `config.py`.
6. Uses `discrepancy.py` to determine the status and discrepancy label.
7. Returns all comparison details in a `ReconciliationResult`.

For example, comparing `100` and `101` uses a 1% difference and therefore
produces `AUTO_RESOLVED` with the default 2% tolerance. Comparing `100` and
`110` produces `ESCALATED`.

#### `compare_exact(field, left, right)`

This function is intended for identifiers and other text values:

- Missing values produce `MISSING`.
- Values match when their stripped, lowercased string forms are equal.
- Otherwise the result is `ESCALATED` with `exact_mismatch`.

This makes comparisons case-insensitive and ignores leading/trailing
whitespace, but does not perform fuzzy matching or normalization beyond that.

#### `compare_amounts(left, right)`

A convenience wrapper that calls `compare_numeric("amount", left, right)`.
It is useful for quick checks and tests when the field is specifically an
amount.

## Example result shapes

A matched numeric comparison can be represented as:

```python
{
    "status": "MATCHED",
    "field": "amount",
    "left_value": 100,
    "right_value": 100,
    "difference": 0,
    "difference_percent": 0.0,
    "discrepancy_type": None,
}
```

A missing value is represented with status `MISSING`, the available values,
and `discrepancy_type="missing_value"`.

## Important current implementation caveats

The files describe a coherent design, but the current repository still has a
few integration details to consider:

- The reconciliation directory currently has no checked-in `__init__.py`.
  It can still participate in Python's namespace-package behavior in some
  layouts, but adding an explicit package initializer may make deployment and
  imports clearer.
- `compare_numeric` and its `compare_amounts` wrapper validate both inputs
  before arithmetic. They accept `int`, `float`, or `None`; `None` remains a
  valid missing-value input, while booleans and other types raise `TypeError`
  with the invalid argument name and type. Callers should still map and
  normalize OCR/parser output before comparison.
- `compare_numeric` uses the right value as the percentage baseline except
  when it is zero. This is intentional in the current implementation, but
  callers should understand that reversing the two inputs can change the
  reported percentage.
- `classify_discrepancy` currently returns amount-oriented labels regardless
  of the field name. More field-specific labels can be added later if the
  dashboard needs them.
- The current dashboard uses mock records and does not yet call these
  comparator functions directly. The `ReconciliationResult.as_dict()` method
  is prepared for a future audit-log or dashboard integration.

## Summary

The reconciliation engine is a small, configurable decision layer. It
compares numeric or exact values, applies a 2% default tolerance to numeric
fields, classifies discrepancies, and returns a consistent result object.
Keeping comparison, policy, and data shapes in separate modules makes the
rules easier to test and change as the OCR pipeline and verification workflow
become fully integrated.
