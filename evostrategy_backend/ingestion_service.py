"""Background orchestration around the existing EvoStrategy ingestion stages."""

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal

from ingestion.extraction.llm_parser import parse_document_llm
from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.schemas.invoice_schema import DocumentExtraction
from utils.save_json import save_document

from .job_store import JobStore
from .models import PipelineStep, StreamEvent

STEPS = (
    ("received", "Documents received", "Files saved for processing"),
    ("extracting", "Extracting business information", "Rasterizing pages and running OCR"),
    ("validating", "Validating extracted data", "Checking source-faithful fields"),
    ("persisting", "Persisting source records", "Writing traceable JSON output"),
    ("workspace", "Preparing your workspace", "Ready for the next stage"),
)


def initial_steps() -> list[PipelineStep]:
    """Return a fresh pipeline state for a queued job."""
    return [
        PipelineStep(key=key, label=label, detail=detail, state="pending")
        for key, label, detail in STEPS
    ]


def _set_step(store: JobStore, job_id: str, active_key: str, failed: bool = False) -> None:
    """Mark one step active or failed and prior steps complete."""
    steps = initial_steps()
    active_index = next(index for index, step in enumerate(steps) if step.key == active_key)
    for index, step in enumerate(steps):
        if index < active_index:
            step.state = "complete"
        elif index == active_index:
            step.state = "failed" if failed else "active"
    store.update(
        job_id,
        status="running",
        progress=round(active_index / (len(steps) - 1) * 100),
        steps=steps,
        message=steps[active_index].label,
    )


def _emit(
    store: JobStore,
    job_id: str,
    message: str,
    level: Literal["info", "success", "error"] = "info",
) -> None:
    """Append one observable worker event to the job stream."""
    current = store.get(job_id)
    if current is None:
        return
    event = StreamEvent(
        timestamp=datetime.now(timezone.utc).strftime("%H:%M:%S"),
        message=message,
        level=level,
    )
    store.update(job_id, events=[*current.events, event])


def process_job(job_id: str, paths: list[Path], store: JobStore) -> None:
    """Run uploaded PDFs through the existing preprocessing and extraction stages."""
    try:
        _set_step(store, job_id, "received")
        _emit(store, job_id, f"{len(paths)} document(s) received and stored", "success")
        if any(path.suffix.lower() != ".pdf" for path in paths):
            raise ValueError("The current ingestion pipeline supports PDF files only.")

        for index, path in enumerate(paths):
            _set_step(store, job_id, "extracting")
            _emit(store, job_id, f"Rasterizing {path.name} into page images")
            images = pdf_to_images(path)
            _emit(store, job_id, f"Running OCR across {len(images)} page(s)")
            text = extract_text_from_images(images)
            _emit(store, job_id, f"Extracted {len(text)} OCR characters from {path.name}")
            _emit(store, job_id, "Sending OCR text to the configured local/cloud extraction model")
            extracted_data = parse_document_llm(text)
            _set_step(store, job_id, "validating")
            document = DocumentExtraction(**extracted_data)
            _emit(store, job_id, "Validated source-faithful fields and tables", "success")
            _set_step(store, job_id, "persisting")
            save_document(document, path)
            _emit(store, job_id, f"Saved traceable extraction for {path.name}", "success")
            store.update(job_id, files_processed=index + 1)

        _set_step(store, job_id, "intelligence")
        _emit(store, job_id, "Ingestion complete; reconciliation is available in the next stage", "success")
        _set_step(store, job_id, "workspace")
        steps = initial_steps()
        for step in steps:
            step.state = "complete"
        store.update(
            job_id,
            status="completed",
            progress=100,
            steps=steps,
            message="Ingestion complete",
        )
    except Exception as exc:
        current = store.get(job_id)
        active_key = next(
            (step.key for step in current.steps if step.state == "active"),
            "extracting",
        ) if current else "extracting"
        _set_step(store, job_id, active_key, failed=True)
        _emit(store, job_id, str(exc), "error")
        store.update(
            job_id,
            status="failed",
            error=str(exc),
            message="Ingestion could not complete",
        )
