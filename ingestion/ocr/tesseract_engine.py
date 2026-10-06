# Convert the images into text. OCR reading directly from images

from pathlib import Path
from PIL import Image
import pytesseract


def extract_text_from_images(image_paths: list[Path]) -> str:
    """Extract text from images using Tesseract OCR.

    Args:
        image_paths (list[Path]): A list of paths to the input images.

    Returns:
        str: The text scanned from inside the image.
    """
    text, _ = extract_text_with_confidence(image_paths)
    return text


def extract_text_with_confidence(image_paths: list[Path]) -> tuple[str, float]:
    """Extract text and Tesseract's mean word confidence (0-1) across pages.

    The confidence is the average of Tesseract's per-word confidences for
    words that contain text. It is a document-level signal used downstream to
    flag low-quality extractions (< 0.85) for human review.
    """
    combined_text = ""
    confidences: list[float] = []

    for image_path in image_paths:
        image = Image.open(image_path)
        combined_text += pytesseract.image_to_string(image) + "\n"
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        for word, confidence in zip(data.get("text", []), data.get("conf", [])):
            try:
                value = float(confidence)
            except (TypeError, ValueError):
                continue
            if str(word).strip() and value >= 0:
                confidences.append(value)

    mean_confidence = sum(confidences) / len(confidences) / 100 if confidences else 0.0
    return combined_text, round(mean_confidence, 4)
