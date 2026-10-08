"""Background job: uploaded files -> Stage 1 -> Stage 2 -> analytics warm-up."""

from __future__ import annotations

import threading
from pathlib import Path

from .job_store import JobStore
from .models import PipelineStep

STEPS = (
    ("received", "Documents received", "Files available"),
    ("extracting", "Extracting business information", "Source-faithful fields"),
    ("reconciling", "Reconciling records", "Reviewable comparisons"),
    ("intelligence", "Building company intelligence", "Verified analytics & forecasts"),
    ("workspace", "Preparing your workspace", "Next"),
)
# One pipeline run at a time: they share the local SQLite registry.
_PIPELINE_LOCK = threading.Lock()
_PROGRESS = {"received": 5, "extracting": 10, "reconciling": 75, "intelligence": 88, "workspace": 96}


def initial_steps() -> list[PipelineStep]:
    """Return a fresh pipeline state for a queued job."""
    return [
        PipelineStep(key=key, label=label, detail=detail, state="pending")
        for key, label, detail in STEPS
    ]


def _steps(active_key: str, failed: bool = False) -> list[PipelineStep]:
    steps = initial_steps()
    active_index = next(index for index, step in enumerate(steps) if step.key == active_key)
    for index, step in enumerate(steps):
        if index < active_index:
            step.state = "complete"
        elif index == active_index:
            step.state = "failed" if failed else "active"
    return steps


def _set_step(store: JobStore, job_id: str, key: str, message: str | None = None, progress: int | None = None) -> None:
    steps = _steps(key)
    store.update(
        job_id,
        status="running",
        progress=progress if progress is not None else _PROGRESS[key],
        steps=steps,
        message=message or steps[[s.key for s in steps].index(key)].label,
    )


def _log(store: JobStore, job_id: str, line: str) -> None:
    job = store.get(job_id)
    if job:
        store.update(job_id, log=[*job.log[-49:], line])


def _finish(store: JobStore, job_id: str, summary: dict, failures: list[dict]) -> None:
    steps = initial_steps()
    for step in steps:
        step.state = "complete"
    open_cases = sum(
        count for status, count in summary.get("case_status_counts", {}).items()
        if status in {"ESCALATED", "MISSING", "AMBIGUOUS"}
    )
    store.update(
        job_id,
        status="completed",
        progress=100,
        steps=steps,
        summary=summary,
        failures=failures,
        message=(
            f"{summary.get('documents', 0)} documents reconciled · {open_cases} need review"
            + (f" · {len(failures)} file(s) could not be read" if failures else "")
        ),
    )


def _fail(store: JobStore, job_id: str, error: Exception | str) -> None:
    current = store.get(job_id)
    active_key = next(
        (step.key for step in current.steps if step.state == "active"), "extracting"
    ) if current else "extracting"
    store.update(
        job_id,
        status="failed",
        steps=_steps(active_key, failed=True),
        error=str(error),
        message="Ingestion could not complete",
    )


def _warm_analytics() -> None:
    from analytics.aggregates import overview
    from analytics.verified import load_transactions, verified_transactions

    overview(load_transactions(), verified_transactions())


def process_job(job_id: str, paths: list[Path], store: JobStore) -> None:
    """Run uploaded files through the full pipeline, reporting real progress."""
    from pipeline import ingest_paths, run_reconciliation

    with _PIPELINE_LOCK:
        _process_job(job_id, paths, store, ingest_paths, run_reconciliation)


def _process_job(job_id, paths, store, ingest_paths, run_reconciliation) -> None:
    try:
        _set_step(store, job_id, "received")

        def progress(name: str, index: int, total: int) -> None:
            if not name:
                return
            share = 10 + round(60 * index / max(total, 1))
            _set_step(store, job_id, "extracting", f"Extracting {name}", share)
            _log(store, job_id, f"[{index + 1}/{total}] {name}")

        documents, failures = ingest_paths(paths, progress=progress)
        for failure in failures:
            _log(store, job_id, f"! {failure['file']}: {failure['error']}")
        store.update(job_id, files_processed=len(paths) - len(failures))
        if not documents and failures:
            raise RuntimeError("None of the uploaded files could be read: " + "; ".join(
                f"{f['file']} ({f['error']})" for f in failures))

        _set_step(store, job_id, "reconciling")
        _log(store, job_id, f"Reconciling {len(documents)} new document(s) against the registry")
        summary = run_reconciliation()
        _log(store, job_id, f"{summary['links']} links · {summary['cases']} cases")

        _set_step(store, job_id, "intelligence")
        _warm_analytics()
        _set_step(store, job_id, "workspace")
        _finish(store, job_id, summary, failures)
    except Exception as error:  # noqa: BLE001 - surfaced to the client
        _fail(store, job_id, error)


def process_demo_job(job_id: str, store: JobStore) -> None:
    """Rebuild and process the bundled demo dataset on a fresh registry."""
    from pipeline import run_demo

    with _PIPELINE_LOCK:
        _process_demo(job_id, store, run_demo)


def _process_demo(job_id, store, run_demo) -> None:
    try:
        _set_step(store, job_id, "received", "Loading demo dataset")

        def progress(name: str, index: int, total: int) -> None:
            if not name:
                return
            store.update(job_id, files_received=total, files_processed=index)
            _set_step(store, job_id, "extracting", f"Extracting {name}", 10 + round(60 * index / max(total, 1)))
            _log(store, job_id, f"[{index + 1}/{total}] {name}")

        summary = run_demo(progress=progress)
        failures = summary.pop("failures", [])
        _set_step(store, job_id, "intelligence")
        _warm_analytics()
        _finish(store, job_id, summary, failures)
    except Exception as error:  # noqa: BLE001
        _fail(store, job_id, error)
