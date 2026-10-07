"""OpenCV image clean-up before OCR (implementation plan, week 3).

Three steps, applied only to pages that read poorly, so clean, born-digital pages are not harmed:

- denoise   remove speckle from scans (non-local means)
- binarise  turn the grey, faded page into clean black-on-white text
            (Otsu's threshold) — Tesseract reads grey noisy paper very badly
- deskew    find the tilt of the text lines and rotate them level
            (only when tilted by more than half a degree)

(CLAHE contrast stretching was tried and dropped: on noisy scans it amplified
the noise and made Tesseract read nothing.)

The OCR engine decides when to use this: it reads the original page first and
only tries the cleaned page if confidence is low, keeping whichever reads better.
"""

from __future__ import annotations

from pathlib import Path

MIN_SKEW_DEGREES = 0.5
UPSCALE_BELOW_PIXELS = 2400  # longest side; a 300 DPI letter page is 3300


def available() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


def estimate_skew(binary) -> float:
    """Angle (degrees) that levels the text lines; 0 when the page is already level.

    Projection-profile search: rotate a small copy of the black-and-white page
    through -5..+5 degrees and keep the angle where the text rows are sharpest
    (largest variance of ink per row). Robust to noise and dark table bars.
    """
    import cv2
    import numpy as np

    ink = (binary < 128).astype(np.float32)
    scale = 800 / max(ink.shape)
    small = cv2.resize(ink, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else ink
    height, width = small.shape
    center = (width / 2, height / 2)

    def sharpness(angle: float) -> float:
        rotated = cv2.warpAffine(small, cv2.getRotationMatrix2D(center, angle, 1.0), (width, height))
        return float(np.var(rotated.sum(axis=1)))

    coarse = max(np.arange(-5.0, 5.01, 0.5), key=sharpness)
    best = max(np.arange(coarse - 0.5, coarse + 0.51, 0.1), key=sharpness)
    if abs(best) < MIN_SKEW_DEGREES:
        return 0.0
    return round(float(best), 2)


def clean_image(image_path: Path, output_path: Path | None = None) -> tuple[Path, dict]:
    """Write a cleaned copy of ``image_path``; return (path, what was done)."""
    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError(f"Could not read image: {image_path}")
    steps: dict = {}

    if max(image.shape) < UPSCALE_BELOW_PIXELS:   # low-resolution scan: give Tesseract bigger letters
        image = cv2.resize(image, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        steps["upscale"] = 1.5

    image = cv2.fastNlMeansDenoising(image, None, h=15, templateWindowSize=7, searchWindowSize=15)
    steps["denoise"] = "non-local means h=15"

    _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    angle = estimate_skew(binary)
    if angle:
        # rotate the grey image (smooth edges), then binarise; rotating the
        # black-and-white copy would chip the letters
        height, width = image.shape
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
        image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=255)
        _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    steps["deskew_degrees"] = angle
    steps["binarise"] = "Otsu threshold"
    image = binary

    output_path = output_path or image_path.with_name(f"{image_path.stem}_clean{image_path.suffix}")
    cv2.imwrite(str(output_path), image)
    return output_path, steps
