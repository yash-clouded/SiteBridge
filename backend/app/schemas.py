"""Phase 1 request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    source_filename: Optional[str]
    imported_at: datetime
    level_count: int
    level_names: list[str]
    weighting_field: Optional[str]
    node_count: int = 0
    leaf_count: int = 0


class WbsNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: Optional[int]
    code: str
    name: str
    level: int
    level_name: str
    is_leaf: bool
    planned_start: Optional[date]
    planned_finish: Optional[date]
    weight: Optional[float]
    discipline: Optional[str]
    area: Optional[str]
    equipment_tag: Optional[str]
    predecessor_ids: list[str] = []
    successor_ids: list[str] = []


class ImportResponse(BaseModel):
    project: ProjectOut
    message: str


# --- Auth (Phase 2) ---------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: str  # Role.value: FIELD | PLANNER | PM


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- Field intake (Phase 3) ------------------------------------------------

class TextReportRequest(BaseModel):
    project_id: int
    raw_text: str = Field(min_length=1)
    # text (typed) | voice (transcribed before intake) | dpr (daily progress note)
    source_type: str = "text"
    # Evidence pointer for non-file sources, e.g. {"timestamp": "..."}
    pointer: dict[str, Any] = Field(default_factory=dict)


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int
    source_type: str
    raw_text: str
    filename: Optional[str]
    pointer: dict[str, Any]
    extraction_status: str = "pending"  # pending | extracted | failed | disabled
    extraction_error: Optional[str] = None
    created_at: datetime


# --- Execution events + matching (Phases 4-6) -------------------------------

class ExecutionEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    field_report_id: int
    # null = "the report does not say" — never a default value.
    description: Optional[str]
    discipline: Optional[str]
    location: Optional[str]
    tag: Optional[str]
    event_date: Optional[date]
    status: Optional[str]
    quantity: Optional[float]
    progress: Optional[float]
    model: Optional[str]
    prompt_version: str
    review_status: str
    reviewed_at: Optional[datetime]
    reviewed_by: Optional[int] = None
    review_note: Optional[str] = None
    extracted_at: datetime
    raw_model_response: Optional[str] = None


class ActivitySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    level: int
    level_name: str
    discipline: Optional[str]
    area: Optional[str]
    equipment_tag: Optional[str]
    planned_start: Optional[date]
    planned_finish: Optional[date]
    # Phase 8: actuals written by an approval (null = not reported / not approved)
    actual_status: Optional[str] = None
    actual_progress: Optional[float] = None
    actual_date: Optional[date] = None
    actual_report_id: Optional[int] = None


class RuleCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule: str
    result: str  # pass | fail | unknown
    detail: Optional[str]
    wbs_node_id: int


class CandidateOut(BaseModel):
    id: int
    rank: int
    wbs_node_id: int
    score: float
    semantic_score: float
    kg_score: float
    breakdown: dict[str, Any]
    activity: ActivitySummary
    rules: list[RuleCheckOut] = []
    # Phase 7: high | medium | low, read from breakdown["confidence"]
    confidence_band: Optional[str] = None
    # Phase 8: is this the candidate the approval chose?
    approved: bool = False


class MatchOut(BaseModel):
    report: ReportOut
    extraction_status: str
    extraction_error: Optional[str]
    event: Optional[ExecutionEventOut]
    candidates: list[CandidateOut] = []


class EmbedResponse(BaseModel):
    project_id: int
    embedded: int
    provider: str
    model: str
    dim: int


# --- Review queue (Phase 8) -------------------------------------------------

class QueueTop(BaseModel):
    candidate_id: int
    wbs_node_id: int
    score: float
    confidence_band: Optional[str] = None
    activity: ActivitySummary
    rules: list[RuleCheckOut] = []


class QueueItem(BaseModel):
    report: ReportOut
    event: Optional[ExecutionEventOut] = None
    review_status: Optional[str] = None  # None = no event extracted yet
    top: Optional[QueueTop] = None
    candidate_count: int = 0


class QueueOut(BaseModel):
    project_id: Optional[int] = None
    items: list[QueueItem] = []
    counts: dict[str, int] = {}


class ReviewNote(BaseModel):
    note: Optional[str] = None


class ApproveRequest(BaseModel):
    """`candidate_id` omitted = the top-ranked candidate."""

    candidate_id: Optional[int] = None
    note: Optional[str] = None


# --- Roll-up (Phase 9) ------------------------------------------------------

class RollupBucket(BaseModel):
    key: str  # area / discipline value; "" = not stated in the schedule
    activities: int
    reported: int  # activities with an approved actual
    avg_progress: Optional[float] = None  # mean over REPORTED activities only
    last_update: Optional[date] = None
    by_status: dict[str, int] = {}


class RollupSeriesPoint(BaseModel):
    day: date
    approved: int


class RollupOut(BaseModel):
    project_id: int
    activities: int  # leaf activities in the schedule
    reported: int  # ... that have approved evidence
    coverage: float  # reported / activities
    avg_progress: Optional[float] = None  # None = no activity states progress
    pending_review: int = 0
    needs_manual: int = 0
    approved: int = 0
    rejected: int = 0
    by_area: list[RollupBucket] = []
    by_discipline: list[RollupBucket] = []
    by_wbs: list[RollupBucket] = []
    series: list[RollupSeriesPoint] = []
    updated_at: Optional[datetime] = None
