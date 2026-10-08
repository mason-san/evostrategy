"""FastAPI entrypoint for EvoStrategy.

Ingestion jobs   POST /api/ingestion/jobs, GET /api/ingestion/jobs/{id}, POST /api/demo
Workspace        GET  /api/summary, /api/documents, /api/documents/{id}, page images
Verification     GET  /api/cases, /api/cases/{id}; POST /api/cases/{id}/review; GET /api/audit
Analytics        GET  /api/analytics/overview, /api/forecast, /api/forecast/snapshots,
                      /api/runway; POST /api/whatif
Settings         GET/PUT /api/settings (budgets, cash balance, headcount)
Evaluation       GET  /api/metrics, /api/audit/verify
Admin            POST /api/reconcile, POST /api/reset

When evostrategy_frontend/dist exists it is served at "/", so a single
process runs the whole local ("shoebox") deployment.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from analytics.aggregates import overview
from analytics.forecasting import forecast_series
from analytics.verified import load_transactions, verified_transactions
from analytics.whatif import Scenario, simulate
from analytics.aggregates import monthly_series
from analytics.finance import data_sources, runway
from ingestion.service import SUPPORTED_TYPES
from storage import registry
from utils.config import DEFAULT_FORECAST_HORIZON, DEMO_DATA_DIR, PROJECT_ROOT, UPLOAD_DIR

from . import workspace
from .ingestion_service import initial_steps, process_demo_job, process_job
from .job_store import JobStore
from .models import IngestionJob, ReviewRequest, ScenarioRequest, SettingsRequest

FRONTEND_DIST = PROJECT_ROOT / "evostrategy_frontend" / "dist"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

app = FastAPI(title="EvoStrategy API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
    ).split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
jobs = JobStore()


def _new_job(files_received: int, message: str) -> IngestionJob:
    job = IngestionJob(
        job_id=str(uuid4()),
        status="queued",
        progress=0,
        files_received=files_received,
        files_processed=0,
        steps=initial_steps(),
        message=message,
    )
    jobs.create(job)
    return job


@app.get("/health")
def health() -> dict[str, str]:
    """Return service readiness."""
    return {"status": "ok"}


# --------------------------------------------------------------------------- ingestion

@app.post("/api/ingestion/jobs", response_model=IngestionJob, status_code=202)
async def create_ingestion_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> IngestionJob:
    """Persist uploaded documents and start their ingestion job."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one document is required.")
    for uploaded in files:
        suffix = Path(uploaded.filename or "").suffix.lower()
        if suffix not in SUPPORTED_TYPES:
            raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")

    job = _new_job(len(files), "Documents queued for ingestion")
    job_dir = UPLOAD_DIR / job.job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    try:
        for uploaded in files:
            content = await uploaded.read()
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"{uploaded.filename} is larger than 50 MB.")
            destination = job_dir / Path(uploaded.filename or "document").name
            destination.write_bytes(content)
            saved_paths.append(destination)
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Uploaded documents could not be stored.") from exc

    background_tasks.add_task(process_job, job.job_id, saved_paths, jobs)
    return job


@app.post("/api/demo", response_model=IngestionJob, status_code=202)
def load_demo(background_tasks: BackgroundTasks) -> IngestionJob:
    """Reset the workspace and process the bundled demo dataset."""
    job = _new_job(0, "Loading demo dataset")
    background_tasks.add_task(process_demo_job, job.job_id, jobs)
    return job


@app.get("/api/ingestion/jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(job_id: str) -> IngestionJob:
    """Return the latest progress for an ingestion job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    return job


# --------------------------------------------------------------------------- workspace

@app.get("/api/summary")
def get_summary() -> dict:
    return workspace.summary()


@app.get("/api/documents")
def get_documents() -> list[dict]:
    return workspace.list_documents()


@app.get("/api/documents/{document_id}")
def get_document(document_id: str) -> dict:
    detail = workspace.document_detail(document_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return detail


@app.get("/api/documents/{document_id}/pages/{page}")
def get_document_page(document_id: str, page: int) -> FileResponse:
    """Serve a rendered page image for the side-by-side source viewer."""
    document = registry.get_document(document_id)
    images = (document or {}).get("page_images") or []
    if not 1 <= page <= len(images):
        raise HTTPException(status_code=404, detail="Page not found.")
    path = Path(images[page - 1])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Page image is no longer on disk.")
    return FileResponse(path, media_type="image/png")


# --------------------------------------------------------------------------- verification

@app.get("/api/cases")
def get_cases(status: str | None = Query(default=None, description="open | reviewed | <STATUS>")) -> list[dict]:
    return workspace.list_cases(status)


@app.get("/api/cases/{case_id:path}/detail")
def get_case(case_id: str) -> dict:
    detail = workspace.case_detail(case_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return detail


@app.post("/api/cases/{case_id:path}/review")
def review_case(case_id: str, request: ReviewRequest) -> dict:
    """Record ACCEPT / REJECT / CORRECT with reviewer identity and reason."""
    if registry.get_case(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    reason = (request.reason or "").strip() or None
    if request.action in {"REJECT", "CORRECT"} and not reason:
        raise HTTPException(status_code=422, detail="A reason is required to reject or correct.")
    value = (request.corrected_value or "").strip() or None
    if request.action == "CORRECT":
        if not request.field or value is None:
            raise HTTPException(status_code=422, detail="Choose a field and enter the corrected value.")
        if request.field == "amount":
            try:
                float(value.replace(",", "").replace("$", ""))
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Corrected amount must be a number.") from exc
        if request.field == "date":
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail="Corrected date must be YYYY-MM-DD.") from exc
    registry.log_review_action(
        case_id,
        request.action,
        request.reviewer.strip(),
        reason,
        value if request.action == "CORRECT" else None,
        field=request.field if request.action == "CORRECT" else None,
    )
    return workspace.case_detail(case_id)


@app.get("/api/audit")
def get_audit(limit: int = Query(default=200, ge=1, le=2000)) -> list[dict]:
    return registry.get_review_actions()[:limit]


# --------------------------------------------------------------------------- analytics

def _budgets() -> dict[str, float] | None:
    return registry.get_setting("budgets") or None


def _finance() -> dict:
    return registry.get_setting("finance") or {}


def _traceability(verified: list[dict]) -> dict:
    dates = sorted(t["date"] for t in verified if t.get("date"))
    return {
        "verified_records": len(verified),
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "data_source": data_sources(verified, registry.get_documents(), str(DEMO_DATA_DIR)),
    }


@app.get("/api/analytics/overview")
def get_overview() -> dict:
    verified = verified_transactions()
    result = overview(load_transactions(), verified, _budgets())
    result["traceability"]["data_source"] = _traceability(verified)["data_source"]
    return result


@app.get("/api/forecast")
def get_forecast(
    metric: str = Query(default="revenue", pattern="^(revenue|expense|profit)$"),
    horizon: int = Query(default=DEFAULT_FORECAST_HORIZON, ge=1, le=24),
) -> dict:
    """Forecast one verified monthly series; every distinct result is snapshotted."""
    import hashlib
    import json

    verified = verified_transactions()
    series = monthly_series(verified)
    if not series["months"]:
        return {"error": "No verified data yet.", "metric": metric}
    result = {"metric": metric, **forecast_series(series["months"], series[metric], horizon=horizon,
                                                  non_negative=metric != "profit")}
    if "error" not in result:
        result["traceability"] = _traceability(verified)
        inputs = json.dumps({"months": series["months"], "values": series[metric]}, sort_keys=True)
        input_hash = hashlib.sha256(inputs.encode()).hexdigest()[:16]
        result["snapshot_id"] = registry.save_forecast_snapshot(metric, horizon, input_hash, {
            "forecast_months": result["forecast_months"],
            "ensemble": result["models"]["ensemble"],
            "backtest": result["backtest"],
            "rolling_backtest": result["rolling_backtest"],
            "traceability": result["traceability"],
        })
        result["input_hash"] = input_hash
    return result


@app.get("/api/forecast/snapshots")
def get_forecast_snapshots(limit: int = Query(default=20, ge=1, le=200)) -> list[dict]:
    return registry.get_forecast_snapshots(limit)


@app.get("/api/runway")
def get_runway() -> dict:
    verified = verified_transactions()
    result = runway(verified, _finance())
    if result.get("configured") and "error" not in result:
        result["traceability"] = _traceability(verified)
    return result


@app.post("/api/whatif")
def run_whatif(request: ScenarioRequest) -> dict:
    return simulate(verified_transactions(), Scenario(**request.model_dump()),
                    budgets=_budgets(), finance=_finance())


@app.get("/api/settings")
def get_settings() -> dict:
    return {"budgets": registry.get_setting("budgets") or {}, "finance": _finance()}


@app.put("/api/settings")
def put_settings(request: SettingsRequest) -> dict:
    if request.budgets is not None:
        registry.set_setting("budgets", {k.strip(): v for k, v in request.budgets.items() if k.strip() and v > 0})
    if request.finance is not None:
        finance = request.finance.model_dump()
        finance["source"] = "entered in Settings"
        registry.set_setting("finance", finance)
    return get_settings()


@app.get("/api/metrics")
def get_metrics() -> dict:
    """Last full evaluation (scripts/evaluate_all.py) plus live review-efficiency."""
    import json

    from analytics.efficiency import review_efficiency
    from ingestion.ocr import paddle_engine

    path = PROJECT_ROOT / "evaluation_dataset" / "evaluation_results.json"
    report = json.loads(path.read_text()) if path.is_file() else None
    return {
        "evaluation": report,
        "evaluation_available": report is not None,
        "how_to_refresh": "python scripts/evaluate_all.py",
        "live_review_efficiency": review_efficiency(registry.get_cases(), registry.get_transactions()),
        "audit_chain": registry.verify_audit_chain(),
        "second_ocr_engine": paddle_engine.status(),
    }


@app.get("/api/audit/verify")
def verify_audit() -> dict:
    """Recompute the audit hash chain to show that no decision was altered."""
    return registry.verify_audit_chain()


# --------------------------------------------------------------------------- admin

@app.post("/api/reconcile")
def reconcile() -> dict:
    from pipeline import run_reconciliation

    return run_reconciliation()


@app.post("/api/reset")
def reset() -> dict:
    backup = registry.reset_registry()
    return {"status": "reset", "backup": backup.name if backup else None}


# --------------------------------------------------------------------------- frontend

if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file() and FRONTEND_DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
