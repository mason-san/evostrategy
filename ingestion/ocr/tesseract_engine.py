# Convert the images into text. OCR reading directly from images

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
import pytesseract

# Pages whose mean word confidence is below this are re-read after OpenCV clean-up.
PREPROCESS_RETRY_BELOW = 0.85

# The Windows installer does not add Tesseract to PATH; use TESSERACT_CMD or the
# default install location when the binary is not on PATH.
_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if os.environ.get("TESSERACT_CMD"):
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]
elif not shutil.which("tesseract") and _WINDOWS_TESSERACT.is_file():
    pytesseract.pytesseract.tesseract_cmd = str(_WINDOWS_TESSERACT)


@dataclass
class OcrResult:
    """Everything Stage 1 needs from OCR, with provenance."""

    text: str
    confidence: float                      # mean word confidence, 0-1
    words: list[tuple[str, float]] = field(default_factory=list)   # (word, confidence 0-1)
    engine: str = "tesseract"
    pages: list[dict] = field(default_factory=list)                 # per-page notes
    second_opinion: dict | None = None     # optional PaddleOCR agreement data


def _read(image: Image.Image) -> tuple[str, list[tuple[str, float]]]:
    text = pytesseract.image_to_string(image)
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    words = []
    for word, confidence in zip(data.get("text", []), data.get("conf", [])):
        try:
            value = float(confidence)
        except (TypeError, ValueError):
            continue
        if str(word).strip() and value >= 0:
            words.append((str(word).strip(), round(value / 100, 4)))
    return text, words


def _mean(words: list[tuple[str, float]]) -> float:
    return round(sum(c for _, c in words) / len(words), 4) if words else 0.0


def ocr_pages(image_paths: list[Path], *, preprocess: str | None = None) -> OcrResult:
    """OCR every page; retry low-confidence pages on an OpenCV-cleaned copy.

    ``preprocess`` (or env ``OCR_PREPROCESS``): ``auto`` (default) cleans only
    pages that read poorly and keeps the better reading, ``always`` or ``off``.
    """
    from ingestion.ocr import preprocess as cleaner

    mode = (preprocess or os.environ.get("OCR_PREPROCESS", "auto")).lower()
    texts, all_words, pages = [], [], []
    for image_path in image_paths:
        image_path = Path(image_path)
        text, words = _read(Image.open(image_path))
        note = {"page": image_path.name, "confidence": _mean(words), "preprocessed": False}
        wants_clean = mode == "always" or (mode == "auto" and _mean(words) < PREPROCESS_RETRY_BELOW)
        if wants_clean and cleaner.available():
            cleaned_path, steps = cleaner.clean_image(image_path)
            clean_text, clean_words = _read(Image.open(cleaned_path))
            note["cleaned_confidence"] = _mean(clean_words)
            if mode == "always" or _mean(clean_words) > _mean(words):
                text, words = clean_text, clean_words
                note.update(preprocessed=True, steps=steps, confidence=_mean(clean_words))
        elif wants_clean:
            note["note"] = "opencv not installed; page read without clean-up"
        texts.append(text)
        all_words.extend(words)
        pages.append(note)
    result = OcrResult("\n".join(texts) + "\n", _mean(all_words), all_words, pages=pages)

    from ingestion.ocr import paddle_engine

    if paddle_engine.enabled():
        result.second_opinion = paddle_engine.second_opinion(image_paths)
    return result


def extract_text_from_images(image_paths: list[Path]) -> str:
    """Extract text from images using Tesseract OCR."""
    return ocr_pages(image_paths, preprocess="off").text


def extract_text_with_confidence(image_paths: list[Path]) -> tuple[str, float]:
    """Extract text and Tesseract's mean word confidence (0-1) across pages."""
    result = ocr_pages(image_paths)
    return result.text, result.confidence
