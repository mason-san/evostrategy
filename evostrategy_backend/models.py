"""API models for the EvoStrategy backend."""

from typing import Any, Literal

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
    log: list[str] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class ReviewRequest(BaseModel):
    """A reviewer decision on one reconciliation case."""

    action: Literal["ACCEPT", "REJECT", "CORRECT"]
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str | None = Field(default=None, max_length=1000)
    field: Literal["amount", "date", "category", "counterparty"] | None = None
    corrected_value: str | None = Field(default=None, max_length=200)


class ScenarioRequest(BaseModel):
    """What-if levers; all optional."""

    horizon: int = Field(default=6, ge=1, le=24)
    volume_change_pct: float = Field(default=0, ge=-90, le=300)
    pricing_adjustment_pct: float = Field(default=0, ge=-90, le=300)
    price_elasticity: float = Field(default=0.5, ge=0, le=5)
    headcount_change: int = Field(default=0, ge=-1000, le=1000)
    baseline_headcount: int = Field(default=15, ge=1, le=100000)
    vendor_consolidation_pct: float = Field(default=0, ge=0, le=90)
    other_cost_change_pct: float = Field(default=0, ge=-90, le=300)


class FinanceSettings(BaseModel):
    """Inputs that cannot be read from documents: cash on hand and headcount."""

    cash_balance: float | None = Field(default=None, ge=-1e12, le=1e12)
    cash_as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM; default = latest verified month")
    headcount: int | None = Field(default=None, ge=1, le=100000)


class SettingsRequest(BaseModel):
    """Annual expense budgets per category and finance settings; omit a key to leave it unchanged."""

    budgets: dict[str, float] | None = None
    finance: FinanceSettings | None = None


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AssistantRequest(BaseModel):
    """A question for EvoAssistant plus the visible conversation so far."""

    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    model: str | None = None
    conversation_id: str | None = None   # omit to start a new saved chat


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
