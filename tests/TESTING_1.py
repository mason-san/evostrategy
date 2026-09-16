"""TESTING_1: first deterministic tests for the ingestion module.

These tests cover PDF validation, PDF-to-image conversion, and multi-page OCR.
They intentionally do not call Gemini, so they can run without GEMINI_API_KEY.
"""

import shutil
import tempfile
import unittest
import re
from pathlib import Path
from unittest.mock import patch

import fitz

from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.pdf import pdf_to_image
from ingestion.pdf.pdf_to_image import pdf_to_images


class IngestionTesting1(unittest.TestCase):
    """Verify the first observable ingestion-stage behaviors."""

    def setUp(self) -> None:
        """Create an isolated workspace and a two-page fixture PDF."""
        self.workspace = Path(tempfile.mkdtemp(prefix="evostrategy-testing-1-"))
        self.pdf_path = self.workspace / "sample.pdf"
        document = fitz.open()
        for text in ("TESTING_1_PAGE_ONE", "TESTING_1_PAGE_TWO"):
            page = document.new_page()
            page.insert_text((72, 72), text, fontsize=24)
        document.save(self.pdf_path)
        document.close()

    def tearDown(self) -> None:
        """Remove temporary test artifacts."""
        shutil.rmtree(self.workspace)

    def test_missing_pdf_raises_file_not_found(self) -> None:
        """A missing input must fail explicitly instead of producing output."""
        with self.assertRaises(FileNotFoundError):
            pdf_to_images(self.workspace / "does-not-exist.pdf")

    def test_pdf_is_rendered_in_page_order(self) -> None:
        """Every PDF page becomes a predictably named PNG in page order."""
        output_dir = self.workspace / "images"
        with patch.object(pdf_to_image, "IMAGE_DIR", output_dir):
            image_paths = pdf_to_images(self.pdf_path)

        self.assertEqual(
            [path.name for path in image_paths],
            ["sample_page_1.png", "sample_page_2.png"],
        )
        self.assertTrue(all(path.is_file() for path in image_paths))

    def test_ocr_combines_pages_in_order(self) -> None:
        """OCR output contains both page anchors in the original page order."""
        if shutil.which("tesseract") is None:
            self.skipTest("Tesseract is required for the OCR integration test")

        output_dir = self.workspace / "images"
        with patch.object(pdf_to_image, "IMAGE_DIR", output_dir):
            image_paths = pdf_to_images(self.pdf_path)

        text = extract_text_from_images(image_paths)
        normalized_text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
        first_page = normalized_text.find("testing 1 page one")
        second_page = normalized_text.find("testing 1 page two")

        self.assertNotEqual(first_page, -1, "First page anchor was not found by OCR")
        self.assertNotEqual(second_page, -1, "Second page anchor was not found by OCR")
        self.assertLess(first_page, second_page)

if __name__ == "__main__":
    unittest.main()
