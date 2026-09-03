import json
from pathlib import Path
from typing import Optional, Union

from ingestion.schemas.invoice_schema import DocumentExtraction


def save_document(
    document: DocumentExtraction,
    pdf_path: Optional[Union[Path, str]] = None,
) -> str:
    """Save generic document extraction data as JSON.

    Args:
        document (DocumentExtraction): Extracted document object.
        pdf_path (Optional[Union[Path, str]]): Path to source PDF file for filename generation.

    Returns:
        str: Path to the saved file.
    """
    if pdf_path:
        filename = f"{Path(pdf_path).stem}.json"
    else:
        filename = f"extracted_doc_{id(document)}.json"

    output_dir = Path(__file__).resolve().parent.parent / "data" / "processed" / "extracted"
    output_dir.mkdir(parents=True, exist_ok=True)

    filepath = output_dir / filename

    document_dict = document.model_dump()

    with open(filepath, "w") as file:
        json.dump(document_dict, file, indent=2)

    return str(filepath)


# Backward compatibility alias
save_invoice = save_document