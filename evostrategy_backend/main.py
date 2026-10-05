"""FastAPI entrypoint for the EvoStrategy onboarding ingestion flow."""

from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .ingestion_service import initial_steps, process_job
from .job_store import JobStore
from .models import IngestionJob

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
ALLOWED_EXTENSIONS = {".pdf", ".csv", ".xlsx", ".docx"}

app = FastAPI(title="EvoStrategy Ingestion API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
jobs = JobStore()


@app.get("/health")
def health() -> dict[str, str]:
    """Return service readiness."""
    return {"status": "ok"}


@app.post("/api/ingestion/jobs", response_model=IngestionJob, status_code=202)
async def create_ingestion_job(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> IngestionJob:
    """Persist uploaded documents and start their ingestion job."""
    if not files:
        raise HTTPException(status_code=400, detail="At least one document is required.")

    job_id = str(uuid4())
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    try:
        for uploaded_file in files:
            suffix = Path(uploaded_file.filename or "").suffix.lower()
            if suffix not in ALLOWED_EXTENSIONS:
                raise HTTPException(status_code=415, detail=f"Unsupported file type: {suffix or 'unknown'}")
            destination = job_dir / Path(uploaded_file.filename or "document").name
            destination.write_bytes(await uploaded_file.read())
            saved_paths.append(destination)
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Uploaded documents could not be stored.") from exc

    job = IngestionJob(
        job_id=job_id,
        status="queued",
        progress=0,
        files_received=len(saved_paths),
        files_processed=0,
        steps=initial_steps(),
        message="Documents queued for ingestion",
    )
    jobs.create(job)
    background_tasks.add_task(process_job, job_id, saved_paths, jobs)
    return job


@app.get("/api/ingestion/jobs/{job_id}", response_model=IngestionJob)
def get_ingestion_job(job_id: str) -> IngestionJob:
    """Return the latest progress for an ingestion job."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found.")
    return job
