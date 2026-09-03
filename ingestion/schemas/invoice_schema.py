"""
Generic document extraction schema for Stage 1.

Stage 1 extracts labels and values as they appear in the document.
No semantic interpretation or business field mapping happens here.
"""

from pydantic import BaseModel, ConfigDict


class DocumentExtraction(BaseModel):
    """
    Generic container for document extraction results.

    Accepts arbitrary key-value pairs extracted from any document type.
    Labels and values are preserved exactly as they appear in the source document.
    """
    model_config = ConfigDict(extra="allow")

    # No predefined fields - all data comes through extra="allow"
    # This supports invoices, purchase orders, payment memos, ledgers, etc.
