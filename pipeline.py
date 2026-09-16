# Total pipeline for document processing from PDF to structured data.
from pathlib import Path
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.extraction.llm_parser import parse_document_llm
from ingestion.schemas.invoice_schema import DocumentExtraction
from ingestion.schemas.contracts import (
    CanonicalTransaction,
    source_document_from_extraction,
)
from normalization.mapper import map_document
from reconciliation.engine import reconcile_transactions
from utils.save_json import save_document


def process_document(pdf_path: str) -> DocumentExtraction:
    """
    Process a document PDF and extract structured data.

    Stage 1 extraction: preserves labels and values as they appear in the document.
    No semantic interpretation or business field mapping.

    Args:
        pdf_path(str): The path to the document PDF file.

    Returns:
        DocumentExtraction: A generic extraction object containing document data.
    """
    # Converting the string file path to a Path object.
    input_pdf_path = Path(pdf_path).expanduser().resolve()

    # Converting the pdf into images.
    images = pdf_to_images(input_pdf_path)

    # Extracting text from the images using OCR.
    text = extract_text_from_images(images)

    # Parsing the extracted text to get structured document data.
    extracted_data = parse_document_llm(text)

    print("The Extracted Document Data is: ", extracted_data)

    # Validation and creation of the DocumentExtraction object using the parsed data.
    document = DocumentExtraction(**extracted_data)

    # Save the document
    save_document(document, input_pdf_path)

    return document


def reconcile_extractions(
    left: DocumentExtraction,
    left_path: str,
    right: DocumentExtraction,
    right_path: str,
) -> list[dict]:
    """Map two Stage 1 results and reconcile them through the shared engine."""
    left_source = source_document_from_extraction(
        Path(left_path).stem, left_path, left
    )
    right_source = source_document_from_extraction(
        Path(right_path).stem, right_path, right
    )
    left_transaction: CanonicalTransaction = map_document(left_source)
    right_transaction: CanonicalTransaction = map_document(right_source)
    return reconcile_transactions(left_transaction, right_transaction)


if __name__ == "__main__":
    pdf_path = str(Path(__file__).resolve().parent / "evaluation_dataset/invoices/invoice_005.pdf")
    doc = process_document(pdf_path)

    print("The Extracted Document Data is: ", doc)