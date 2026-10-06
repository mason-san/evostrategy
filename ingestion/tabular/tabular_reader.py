"""Source-faithful ingestion for spreadsheets (CSV / XLSX).

Each data row becomes one extraction whose labels are the column headers and
whose values are the cell contents exactly as written. No OCR is involved, so
field confidence is 1.0. Business meaning is assigned downstream.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()[:10] if hasattr(value, "hour") else value.isoformat()
    text = str(value).strip()
    return text or None


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Return the sheet rows as ``{header: value}`` dictionaries."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [
                {str(key).strip(): _cell(value) for key, value in row.items() if key}
                for row in csv.DictReader(handle)
            ]
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        headers = [str(cell).strip() if cell is not None else "" for cell in next(rows, [])]
        records = []
        for row in rows:
            if all(cell is None for cell in row):
                continue
            records.append(
                {header: _cell(value) for header, value in zip(headers, row) if header}
            )
        return records
    raise ValueError(f"Unsupported spreadsheet format: {suffix}")


def extract_rows(path: Path) -> list[dict[str, Any]]:
    """Return one Stage 1 extraction (``fields``/``tables``) per sheet row."""
    extractions = []
    for row in read_rows(path):
        fields = [
            {
                "field_id": f"field-{index + 1}",
                "label": header,
                "value": value,
                "confidence": 1.0,
            }
            for index, (header, value) in enumerate(row.items())
        ]
        extractions.append({"fields": fields, "tables": []})
    return extractions
