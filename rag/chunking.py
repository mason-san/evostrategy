"""Convert registered Stage 1 documents into deterministic text chunks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ingestion.schemas.contracts import SourceDocument
from reconciliation.semantic_mapping import infer_document_type
from storage import registry
from utils.config import REGISTRY_DB

DEFAULT_MAX_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 150
_IMPORTANT_LABELS = (
    "document type",
    "invoice",
    "purchase order",
    "vendor",
    "supplier",
    "customer",
    "date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "payment",
    "amount",
)


def _display_value(value: Any) -> str | None:
    """Render a JSON value without exposing JSON syntax in chunk text."""
    if value is None or value == "":
        return None
    if isinstance(value, Mapping):
        parts = [
            f"{key.replace('_', ' ').capitalize()}: {rendered}"
            for key, item in value.items()
            if (rendered := _display_value(item)) is not None
        ]
        return "; ".join(parts) or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rendered_items = [_display_value(item) for item in value]
        rendered_items = [item for item in rendered_items if item is not None]
        return ", ".join(rendered_items) or None
    return str(value)


def _label_text(label: Any) -> str:
    """Turn an extracted label into a readable label."""
    return " ".join(str(label).replace("_", " ").split()).strip().capitalize()


def _field_units(document: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Build readable field units, placing key financial fields first."""
    fields = document.get("fields") or []
    units: list[tuple[str, str]] = []
    for field in fields:
        if not isinstance(field, Mapping):
            continue
        value = _display_value(field.get("value"))
        label = _label_text(field.get("label", ""))
        if value is not None and label:
            units.append((label.lower(), f"{label}: {value}"))
    if not units and isinstance(document, Mapping):
        reserved = {"document_id", "document_type", "source", "source_name", "source_path", "fields", "tables", "ocr_text"}
        for key, raw_value in document.items():
            if key in reserved:
                continue
            value = _display_value(raw_value)
            label = _label_text(key)
            if value is not None and label:
                units.append((label.lower(), f"{label}: {value}"))

    def priority(unit: tuple[str, str]) -> tuple[int, str]:
        label = unit[0]
        rank = next((index for index, keyword in enumerate(_IMPORTANT_LABELS) if keyword in label), len(_IMPORTANT_LABELS))
        return rank, unit[1].lower()

    return sorted(units, key=priority)


def _table_units(document: Mapping[str, Any]) -> list[str]:
    """Render extracted tables as readable line-item descriptions."""
    units: list[str] = []
    for table in document.get("tables") or []:
        if not isinstance(table, Mapping):
            continue
        headers = [str(header) for header in table.get("headers") or []]
        for row_number, row in enumerate(table.get("rows") or [], start=1):
            if isinstance(row, Mapping):
                values = [
                    f"{_label_text(key)}: {rendered}"
                    for key, value in row.items()
                    if (rendered := _display_value(value)) is not None
                ]
            else:
                values = [
                    f"{_label_text(header)}: {rendered}"
                    for header, value in zip(headers, row if isinstance(row, Sequence) and not isinstance(row, str) else [])
                    if (rendered := _display_value(value)) is not None
                ]
            if values:
                units.append(f"Line item {row_number}: " + "; ".join(values))
    return units


def _document_prefix(document: Mapping[str, Any]) -> str:
    """Create the stable metadata sentence shared by every chunk."""
    document_type = _document_type(document)
    document_id = _display_value(document.get("document_id")) or "unknown"
    return f"Document type: {document_type}. Document ID: {document_id}."


def _document_type(document: Mapping[str, Any]) -> str:
    """Return explicit type or the existing semantic-mapping inference."""
    explicit = _display_value(document.get("document_type"))
    if explicit:
        return explicit.lower()
    try:
        document_id = str(document.get("document_id") or "unknown")
        fields = [
            {
                **field,
                "field_id": str(field.get("field_id") or f"field-{index}"),
                "label": str(field.get("label") or ""),
                "source_document_id": str(field.get("source_document_id") or document_id),
            }
            for index, field in enumerate(document.get("fields") or [])
            if isinstance(field, Mapping)
        ]
        inferred = infer_document_type(SourceDocument(
            document_id=document_id,
            source_path=str(document.get("source_path") or ""),
            document_type=None,
            fields=fields,
            ocr_text=document.get("ocr_text"),
        ))
        return inferred.lower()
    except (TypeError, ValueError):
        return "financial document"


def _split_units(units: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    """Split readable units while retaining a bounded overlap between chunks."""
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        separator_length = 1 if current else 0
        if current and current_length + separator_length + len(unit) > max_chars:
            chunks.append("\n".join(current))
            overlap: list[str] = []
            overlap_length = 0
            for previous in reversed(current):
                required = len(previous) + (1 if overlap else 0)
                if overlap_length + required > overlap_chars:
                    break
                overlap.insert(0, previous)
                overlap_length += required
            current = overlap
            current_length = overlap_length
        current.append(unit)
        current_length += separator_length + len(unit)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _chunk_id(document_id: str, index: int, text: str) -> str:
    """Return a stable ID for a document chunk."""
    digest = hashlib.sha256(f"{document_id}\n{index}\n{text}".encode("utf-8")).hexdigest()[:16]
    return f"{document_id}:chunk-{index:04d}-{digest}"


def chunk_document(
    document: Mapping[str, Any],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[dict[str, Any]]:
    """Convert one registered document payload into searchable text chunks."""
    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("max_chars must be positive and overlap_chars must be smaller than max_chars")
    document_id = str(document.get("document_id") or "unknown")
    units = [_document_prefix(document)]
    units.extend(text for _, text in _field_units(document))
    table_units = _table_units(document)
    if table_units:
        units.append("Line items:")
        units.extend(table_units)
    if document.get("ocr_text"):
        units.append(f"Extracted text: {_display_value(document['ocr_text'])}")
    texts = _split_units(units, max_chars, overlap_chars)
    metadata = {
        "document_id": document_id,
        "document_type": _document_type(document),
        "source": document.get("source_path") or document.get("source_name"),
        "source_path": document.get("source_path"),
        "source_name": document.get("source_name"),
    }
    return [
        {
            "chunk_id": _chunk_id(document_id, index, text),
            "document_id": document_id,
            "document_type": metadata["document_type"],
            "chunk_text": text,
            "metadata": metadata.copy(),
        }
        for index, text in enumerate(texts)
    ]


def chunk_registered_documents(
    db_path: Path = REGISTRY_DB,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[dict[str, Any]]:
    """Chunk every extracted document currently stored in the local registry."""
    return [
        chunk
        for document in registry.get_documents(db_path)
        for chunk in chunk_document(document, max_chars=max_chars, overlap_chars=overlap_chars)
    ]


def chunks_as_json(chunks: list[dict[str, Any]]) -> str:
    """Serialize chunks for the local inspection CLI."""
    return json.dumps(chunks, indent=2, ensure_ascii=False)
