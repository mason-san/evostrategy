"""Versioned contracts shared by ingestion and downstream stages."""

from collections.abc import Mapping
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractedField(BaseModel):
    """A source-faithful extracted field with provenance."""

    field_id: str
    label: str
    value: Any = None
    source_document_id: str
    page: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)


class ExtractedTable(BaseModel):
    """A source-faithful extracted table with provenance."""

    table_id: str
    headers: list[str]
    rows: list[dict[str, Any]]
    source_document_id: str
    page: Optional[int] = None


class SourceDocument(BaseModel):
    """The durable Stage 1 output consumed by downstream processing."""

    model_config = ConfigDict(extra="allow")

    contract_version: str = "1.0"
    document_id: str
    source_path: str
    document_type: Optional[str] = None
    fields: list[ExtractedField] = Field(default_factory=list)
    tables: list[ExtractedTable] = Field(default_factory=list)
    ocr_text: Optional[str] = None
    pipeline_version: str = "stage-1"


class CanonicalTransaction(BaseModel):
    """Comparison-ready values while retaining source field references and values."""

    transaction_id: str
    document_id: str
    vendor: Optional[str] = None
    identifier: Optional[str] = None
    date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    raw_field_ids: dict[str, str] = Field(default_factory=dict)
    raw_values: dict[str, Any] = Field(default_factory=dict)
    mapping_confidence: float = Field(default=0.0, ge=0, le=1)


def source_document_from_extraction(
    document_id: str, source_path: str, extraction: BaseModel
) -> SourceDocument:
    """Adapt the generic Stage 1 response to the shared downstream contract."""
    raw_fields = getattr(extraction, "fields", [])
    raw_tables = getattr(extraction, "tables", [])
    fields = []
    for index, item in enumerate(raw_fields):
        data = _mapping_from_item(item, "field")
        fields.append(
            ExtractedField(
                field_id=str(data.get("field_id", f"field-{index}")),
                label=str(data.get("label", "")),
                value=data.get("value"),
                source_document_id=document_id,
                page=data.get("page"),
                confidence=data.get("confidence"),
            )
        )

    tables = []
    for index, item in enumerate(raw_tables):
        data = _mapping_from_item(item, "table")
        tables.append(
            ExtractedTable(
                table_id=str(data.get("table_id", f"table-{index}")),
                headers=[str(header) for header in data.get("headers", [])],
                rows=data.get("rows", []),
                source_document_id=document_id,
                page=data.get("page"),
            )
        )
    return SourceDocument(
        document_id=document_id,
        source_path=source_path,
        fields=fields,
        tables=tables,
    )


def _mapping_from_item(item: Any, item_type: str) -> Mapping[str, Any]:
    """Return an extraction item as a mapping, rejecting malformed input."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    if isinstance(item, Mapping):
        return item
    raise TypeError(f"{item_type} extraction items must be mappings or Pydantic models")
