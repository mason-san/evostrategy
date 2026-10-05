"""Background orchestration around the existing EvoStrategy ingestion stages."""

from pathlib import Path

from ingestion.extraction.llm_parser import parse_document_llm
from ingestion.ocr.tesseract_engine import extract_text_from_images
from ingestion.pdf.pdf_to_image import pdf_to_images
from ingestion.schemas.invoice_schema import DocumentExtraction
from utils.save_json import save_document

from .job_store import JobStore
from .models import PipelineStep

STEPS = (
    ("received", "Documents received", "Files available"),
    ("extracting", "Extracting business information", "Source-faithful fields"),
    ("reconciling", "Reconciling records", "Reviewable comparisons"),
    ("intelligence", "Building company intelligence", "Preparing your workspace"),
    ("workspace", "Preparing your workspace", "Next"),
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


def process_job(job_id: str, paths: list[Path], store: JobStore) -> None:
    """Run uploaded PDFs through the existing preprocessing and extraction stages."""
    try:
        _set_step(store, job_id, "received")
        if any(path.suffix.lower() != ".pdf" for path in paths):
            raise ValueError("The current ingestion pipeline supports PDF files only.")

        for index, path in enumerate(paths):
            _set_step(store, job_id, "extracting")
            images = pdf_to_images(path)
            text = extract_text_from_images(images)
            extracted_data = parse_document_llm(text)
            document = DocumentExtraction(**extracted_data)
            save_document(document, path)
            store.update(job_id, files_processed=index + 1)

        _set_step(store, job_id, "reconciling")
        _set_step(store, job_id, "intelligence")
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
        store.update(
            job_id,
            status="failed",
            error=str(exc),
            message="Ingestion could not complete",
        )
