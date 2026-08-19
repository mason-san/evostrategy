# The module is responsible for evaluating the performance of the pipeline (the different types of parser)

import json
from pathlib import Path
from typing import Callable

from pydantic import ValidationError
from ingestion.schemas.invoice_schema import Invoice
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.ocr.tesseract_engine import extract_text_from_images

DATASET_DIR = Path(__file__).resolve().parent.parent / "evaluation_dataset"
INVOICES_DIR = DATASET_DIR / "invoices"
GROUND_TRUTH_DIR = DATASET_DIR / "ground_truth"


def load_ground_truth(pdf_path: Path) -> Invoice:
    """
    Load the ground truth invoice data from a json file.

    Args:
        pdf_path (Path): The path to the invoice PDF file.

    Returns:
        Invoice: An Invoice object containing the ground truth invoice information.
    """
    invoice_name = pdf_path.stem
    invoice_file = GROUND_TRUTH_DIR / f"{invoice_name}.json"

    with open(invoice_file, "r") as f:
        invoice_data = json.load(f)

    return Invoice(**invoice_data)


def compare_invoice(
    expected_invoice: Invoice,
    predicted_invoice: Invoice
) -> dict:
    """
    Compare the expected and predicted invoice data field-by-field.

    Returns:
        dict: Field names mapped to True/False indicating whether values match.
    """
    return {
        key: getattr(expected_invoice, key) == getattr(predicted_invoice, key)
        for key in expected_invoice.model_dump()
    }


def evaluate_invoice(
    pdf_path: Path,
    parser_fn: Callable[[str], dict],
) -> dict:
    """
    Evaluate a single invoice against ground truth using the given parser.

    Args:
        pdf_path: Path to the invoice PDF.
        parser_fn: A parser function with signature (text: str) -> dict.

    Returns:
        dict: Field names mapped to True/False.
    """
    expected = load_ground_truth(pdf_path)

    try:
        images = pdf_to_images(pdf_path)
        text = extract_text_from_images(images)
        predicted_data = parser_fn(text)
        predicted = Invoice(**predicted_data)
    except (ValidationError, Exception):
        return {key: False for key in expected.model_dump()}

    return compare_invoice(expected, predicted)


def evaluate_multiple_invoices(
    invoice_dir: Path,
    parser_fn: Callable[[str], dict],
) -> dict:
    """
    Evaluate all PDFs in a directory and return accuracy statistics.

    Args:
        invoice_dir: Directory containing invoice PDFs.
        parser_fn: A parser function with signature (text: str) -> dict.

    Returns:
        dict: Per-field and overall accuracy percentages, plus document count.
    """
    fields = ["invoice_number", "invoice_date", "total_amount"]
    stats = {f: 0 for f in fields}
    doc_count = 0

    for pdf_path in sorted(invoice_dir.glob("*.pdf")):
        comparison = evaluate_invoice(pdf_path, parser_fn)
        for key in fields:
            if comparison.get(key):
                stats[key] += 1
        doc_count += 1

    if doc_count == 0:
        return {f"{f}_accuracy": 0.0 for f in fields} | {
            "overall_accuracy": 0.0,
            "documents_evaluated": 0,
        }

    total_correct = sum(stats.values())
    total_possible = len(fields) * doc_count

    return {
        f"{f}_accuracy": round((stats[f] / doc_count) * 100, 2)
        for f in fields
    } | {
        "overall_accuracy": round((total_correct / total_possible) * 100, 2),
        "documents_evaluated": doc_count,
    }


if __name__ == "__main__":
    from ingestion.extraction.regex_parser import parse_invoice_regex

    results = evaluate_multiple_invoices(INVOICES_DIR, parse_invoice_regex)
    print(results)
