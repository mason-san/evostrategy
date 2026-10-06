"""Choose the Stage 1 field extractor: Gemini, local Ollama, or offline rules.

Selection is controlled by ``LLM_PROVIDER``:

- ``gemini``  -> Google Gemini (needs ``GEMINI_API_KEY``)
- ``ollama``  -> a local Ollama model (``OLLAMA_MODEL``, ``OLLAMA_URL``)
- ``rules``   -> deterministic offline parser, no network
- ``auto``    -> (default) Gemini when a key is set, otherwise rules

If an LLM provider fails, extraction falls back to the rule parser and the
failure is recorded in the returned method string so it is never silent.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .rule_parser import parse_document_rules


def parse_document_ollama(text: str) -> dict[str, Any]:
    """Extract fields with a local Ollama model using the Stage 1 instruction."""
    from .llm_parser import _INSTRUCTION

    model = os.environ.get("OLLAMA_MODEL")
    if not model:
        raise RuntimeError("OLLAMA_MODEL environment variable not set")
    url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload = json.dumps(
        {
            "model": model,
            "system": _INSTRUCTION,
            "prompt": text,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode()
    request = urllib.request.Request(
        f"{url}/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        body = json.loads(response.read())
    return json.loads(body["response"])


def _provider() -> str:
    provider = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    if provider == "auto":
        return "gemini" if os.environ.get("GEMINI_API_KEY") else "rules"
    return provider


def parse_document(text: str, ocr_confidence: float | None = None) -> tuple[dict[str, Any], str]:
    """Return ``(extraction, method)`` with per-field confidence attached.

    Field confidence = parser confidence (rules) or 1.0 (LLM), multiplied by the
    OCR engine's document confidence when available.
    """
    provider = _provider()
    method = provider
    try:
        if provider == "gemini":
            from .llm_parser import parse_document_llm

            data = parse_document_llm(text)
        elif provider == "ollama":
            data = parse_document_ollama(text)
        elif provider == "rules":
            data = parse_document_rules(text)
        else:
            raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
    except Exception as error:  # noqa: BLE001 - recorded, then safe fallback
        data = parse_document_rules(text)
        method = f"rules (fallback after {provider} error: {error})"

    data.setdefault("fields", [])
    data.setdefault("tables", [])
    for index, field in enumerate(data["fields"]):
        field.setdefault("field_id", f"field-{index + 1}")
        base = field.get("confidence")
        base = float(base) if isinstance(base, (int, float)) else 1.0
        if ocr_confidence is not None:
            base *= ocr_confidence
        field["confidence"] = round(max(0.0, min(base, 1.0)), 4)
    return data, method
