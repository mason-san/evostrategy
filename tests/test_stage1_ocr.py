"""Stage 1 additions: 300 DPI rendering, OpenCV clean-up, per-field confidence,
labels whose colon OCR lost, and the optional second OCR engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.extraction.dispatcher import parse_document
from ingestion.extraction.rule_parser import parse_document_rules
from ingestion.ocr import paddle_engine, preprocess
from reconciliation.semantic_mapping import normalize_label


def _labels(text: str) -> dict[str, str]:
    return {f["label"]: f["value"] for f in parse_document_rules(text)["fields"]}


def test_known_labels_without_colon_are_read_and_kept_verbatim() -> None:
    fields = _labels("Date Dec 08 2012\nOrder 1D - MX-2012-AH1003082-41251\nThanks for your business!")
    assert fields == {"Date": "Dec 08 2012", "Order 1D": "MX-2012-AH1003082-41251"}


def test_ordinary_sentences_are_not_mistaken_for_fields() -> None:
    assert _labels("Item Quantity Rate Amount\nThanks for your business!") == {}


def test_label_matching_tolerates_ocr_lookalikes_only_next_to_letters() -> None:
    assert normalize_label("Order 1D") == normalize_label("Order !D") == "order id"
    assert normalize_label("Discount (20%)") == "discount 20"
    assert normalize_label("Q1 2012") == "q1 2012"


def test_field_confidence_uses_the_words_of_that_field() -> None:
    words = [("Total:", 0.97), ("$50.10", 0.96), ("Date:", 0.9), ("Mar", 0.4), ("06", 0.5), ("2012", 0.6)]
    data, _ = parse_document("Total: $50.10\nDate: Mar 06 2012", 0.8, ocr_words=words)
    confidence = {f["label"]: f["confidence"] for f in data["fields"]}
    assert confidence["Total"] == pytest.approx(0.95 * 0.96, abs=1e-3)      # its own word
    assert confidence["Date"] == pytest.approx(0.95 * 0.5, abs=1e-3)        # mean of Mar/06/2012


def test_second_engine_disagreement_lowers_confidence() -> None:
    agree, _ = parse_document("Total: $50.10", 1.0, second_opinion_text="Total $50.10")
    differ, _ = parse_document("Total: $50.10", 1.0, second_opinion_text="Total $58.10")
    assert agree["fields"][0]["confidence"] == pytest.approx(0.95)
    assert differ["fields"][0]["confidence"] == pytest.approx(0.95 * paddle_engine.DISAGREEMENT_PENALTY)


def test_second_engine_is_off_unless_requested(monkeypatch) -> None:
    monkeypatch.delenv("OCR_SECOND_ENGINE", raising=False)
    assert paddle_engine.enabled() is False
    assert paddle_engine.status().startswith("off")


@pytest.mark.skipif(not preprocess.available(), reason="opencv not installed")
def test_deskew_recovers_a_tilted_page(tmp_path: Path) -> None:
    import cv2
    import numpy as np

    page = np.full((1200, 900), 255, np.uint8)
    for row in range(100, 1100, 60):
        cv2.putText(page, "Total amount due 1234.56 Order ID", (40, row), cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
    tilted = cv2.warpAffine(page, cv2.getRotationMatrix2D((450, 600), 3.0, 1.0), (900, 1200), borderValue=255)
    _, binary = cv2.threshold(tilted, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    assert preprocess.estimate_skew(binary) == pytest.approx(-3.0, abs=0.3)

    path = tmp_path / "page.png"
    cv2.imwrite(str(path), tilted)
    cleaned, steps = preprocess.clean_image(path)
    assert cleaned.exists() and abs(steps["deskew_degrees"]) > 2.5
    assert set(np.unique(cv2.imread(str(cleaned), 0))) <= {0, 255}        # binarised


def test_pdf_pages_render_at_300_dpi(tmp_path: Path, monkeypatch) -> None:
    import fitz

    from ingestion.pdf import pdf_to_image

    monkeypatch.setattr(pdf_to_image, "IMAGE_DIR", tmp_path)
    pdf = tmp_path / "one.pdf"
    document = fitz.open()
    document.new_page(width=612, height=792)          # US letter in points
    document.save(pdf)
    image = pdf_to_image.pdf_to_images(pdf)[0]
    width = fitz.Pixmap(str(image)).width
    assert width == 2550                               # 8.5 in x 300 DPI
