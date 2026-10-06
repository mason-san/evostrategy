"""API models for document-ingestion jobs."""

from typing import Literal

from pydantic import BaseModel, Field

JobStatus = Literal["queued", "running", "completed", "failed"]


class PipelineStep(BaseModel):
    """Current state of one ingestion pipeline step."""

    key: str
    label: str
    detail: str
    state: Literal["pending", "active", "complete", "failed"]


class IngestionJob(BaseModel):
    """Public status returned to the onboarding client."""

    job_id: str
    status: JobStatus
    progress: int = Field(ge=0, le=100)
    files_received: int
    files_processed: int
    steps: list[PipelineStep]
    message: str
    error: str | None = None
