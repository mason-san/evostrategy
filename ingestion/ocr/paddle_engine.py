"""Optional second OCR engine (PaddleOCR) for dual-engine agreement.

The implementation plan pairs Tesseract (printed text) with PaddleOCR (tables
and layouts). PaddleOCR needs PaddlePaddle, a large download that is not
installed by default. Enable it with:

    pip install paddleocr paddlepaddle
    export OCR_SECOND_ENGINE=paddle

When enabled, each extracted field value is checked against PaddleOCR's text:
values both engines read the same keep their confidence, values only Tesseract
read are marked lower so a reviewer looks at them. When PaddleOCR is not
installed the pipeline runs exactly as before and says so in the document's
OCR notes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

DISAGREEMENT_PENALTY = 0.8
_engine = None


def requested() -> bool:
    return os.environ.get("OCR_SECOND_ENGINE", "").strip().lower() == "paddle"


def enabled() -> bool:
    if not requested():
        return False
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        return False
    return True


def status() -> str:
    if not requested():
        return "off (set OCR_SECOND_ENGINE=paddle to enable)"
    return "on" if enabled() else "requested but paddleocr is not installed"


def _reader():
    global _engine
    if _engine is None:
        from paddleocr import PaddleOCR

        _engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    return _engine


def second_opinion(image_paths: list[Path]) -> dict[str, Any]:
    """Run PaddleOCR on the pages; return its text for agreement checks."""
    lines: list[str] = []
    for path in image_paths:
        for page in _reader().ocr(str(path), cls=True) or []:
            for _, (text, _score) in page or []:
                lines.append(text)
    return {"engine": "paddleocr", "text": "\n".join(lines)}


def _squash(text: str) -> str:
    return re.sub(r"[\s,]+", "", str(text)).casefold()


def agreement(value: Any, other_text: str | None) -> bool | None:
    """True if the other engine also read ``value``; None when it cannot say."""
    if value in (None, "") or not other_text:
        return None
    return _squash(value) in _squash(other_text)
