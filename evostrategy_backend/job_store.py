"""In-memory job state for the prototype ingestion API."""

from threading import Lock

from .models import IngestionJob


class JobStore:
    """Thread-safe store used by the background ingestion workers."""

    def __init__(self) -> None:
        self._jobs: dict[str, IngestionJob] = {}
        self._lock = Lock()

    def create(self, job: IngestionJob) -> None:
        """Insert a newly queued job."""
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> IngestionJob | None:
        """Return a snapshot of a job, if it exists."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def update(self, job_id: str, **changes: object) -> None:
        """Update a job atomically."""
        with self._lock:
            current = self._jobs[job_id]
            self._jobs[job_id] = current.model_copy(update=changes, deep=True)
