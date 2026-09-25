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
