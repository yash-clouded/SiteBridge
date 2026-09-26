"""SiteBridge data model — Phase 1: WBS / project structure.

The WBS/Project hierarchy answers "where does this work belong?". It is
imported top-down from the schedule file: the root project node exists
first, then phases, and so on down to executable activities.

The number of levels and their names are READ FROM THE IMPORTED DATA
(`projects.level_count`, `projects.level_names`) — nothing in this code
assumes a fixed number of levels or hardcodes what any level means.

The role/permission hierarchy (`users.role` below) is deliberately a
separate hierarchy that never references WBS levels: a Planner is a role
that can review/approve matches anywhere in the tree — there is no such
thing as an "L1 user".
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from .config import settings
from .db import Base


class Project(Base):
    """One imported schedule (the system of record's WBS snapshot)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[Optional[str]] = mapped_column(String(255))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Read from the imported file — never hardcoded:
    #   level_count: how many hierarchy depths the file actually contains
    #   level_names[i]: the name of depth (i+1) as given by the file
    #     (e.g. ["Project", "Phase", "Area", "System", "Work", "Activity"])
    level_count: Mapped[int] = mapped_column(Integer, default=0)
    level_names: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # Name of the imported weighting column, if the file provided weights.
    weighting_field: Mapped[Optional[str]] = mapped_column(String(64))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    nodes: Mapped[list["WbsNode"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class WbsNode(Base):
    """A node in the WBS tree (adjacency list via parent_id).

    Container nodes (is_leaf=False) carry the hierarchy imported from the
    WBS path; leaf nodes (is_leaf=True) are executable activities with
    schedule dates, discipline/area/tag attributes, and predecessor /
    successor activity IDs — all exactly as imported from the file.
    """

    __tablename__ = "wbs_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("wbs_nodes.id", ondelete="CASCADE"), index=True
    )

    # WBS code / activity ID from the file (containers use their path segment).
    code: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(Text)

    # 1-based depth, read from the file (or derived from the actual path depth).
    level: Mapped[int] = mapped_column(Integer)
    # Name of this depth as given by the file, e.g. "Phase" or "Executable Activity".
    level_name: Mapped[str] = mapped_column(String(128))
    is_leaf: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Materialized ancestor path ("/12/34/") for cheap subtree/ancestor queries.
    path: Mapped[str] = mapped_column(String(4096), default="/")

    # Schedule data (activity rows)
    planned_start: Mapped[Optional[date]] = mapped_column(Date)
    planned_finish: Mapped[Optional[date]] = mapped_column(Date)
    weight: Mapped[Optional[float]] = mapped_column(Float)
    discipline: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    area: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    equipment_tag: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # Activity IDs exactly as imported; normalized link tables come with Phase 5.
    predecessor_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    successor_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    # Phase 8: actuals written by an approval — and only what the approved
    # report actually states. A single reported date is stored as such;
    # nothing here is ever back-filled from the plan (planned_* stays the
    # baseline, actual_* is the evidence).
    actual_status: Mapped[Optional[str]] = mapped_column(String(128))
    actual_progress: Mapped[Optional[float]] = mapped_column(Float)  # percent as stated
    actual_date: Mapped[Optional[date]] = mapped_column(Date)
    actual_report_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("field_reports.id", ondelete="SET NULL"), index=True
    )
    actual_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="nodes")
    parent: Mapped[Optional["WbsNode"]] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["WbsNode"]] = relationship(back_populates="parent")

    __table_args__ = (
        UniqueConstraint("project_id", "parent_id", "code", name="uq_wbs_project_parent_code"),
        Index("ix_wbs_nodes_project_level", "project_id", "level"),
    )


# ---------------------------------------------------------------------------
# Hierarchy 2: role/permission model (SEPARATE from the WBS tree)
#
# A user's role determines which functions they can access — never which
# WBS level they are "assigned to". Permissions are granted by function
# (submit / review+approve / read-only rollup), never by tree position.
# ---------------------------------------------------------------------------

class Role(str, enum.Enum):
    """Seven business roles used by the SiteBridge workstation.

    FIELD is retained as a legacy database value so older installations remain
    readable. New users should use SITE_OPERATIVES.
    """

    CLIENT = "CLIENT"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    CONTRACTOR = "CONTRACTOR"
    SITE_ENGINEER = "SITE_ENGINEER"
    SITE_OPERATIVES = "SITE_OPERATIVES"
    PLANNER = "PLANNER"
    DISCIPLINE_ENGINEER = "DISCIPLINE_ENGINEER"

    # Backwards compatibility with the original three-role database values.
    FIELD = "FIELD"
    PM = "PM"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), index=True)  # Role.value
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 3: field intake — raw input + pointer stored as evidence.
# Every downstream record (execution event, match, approval) references
# this table, so the full chain traces back to the original submission.
# ---------------------------------------------------------------------------

class FieldReport(Base):
    """One raw field submission, exactly as received.

    `pointer` records where the text came from inside the source artifact:
      pdf  -> {"pages": [1, 2], "page_offsets": [{"page": 1, "start": 0, "end": 142}, ...]}
      excel-> {"sheet": "DPR", "rows": {"start": 1, "end": 14}}      (single tab)
             {"sheets": [{"sheet": "DPR", "start": 1, "end": 14}, ...]}  (multi-tab)
      txt  -> {"chars": 512}
      text -> {}   (typed directly)
      voice-> {"timestamp": "2026-09-25T08:31:00Z"}  (transcribed before intake)
      dpr  -> {"day": "2026-09-25", "sheet": ..., "rows": ...}
    """

    __tablename__ = "field_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # text | voice | dpr | txt | excel | pdf
    source_type: Mapped[str] = mapped_column(String(16))
    raw_text: Mapped[str] = mapped_column(Text)
    filename: Mapped[Optional[str]] = mapped_column(String(255))
    pointer: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Phase 4: has the one-extraction-per-report run happened yet?
    # pending | extracted | failed | disabled
    extraction_status: Mapped[str] = mapped_column(String(16), default="pending")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text)
    # Multilingual intake: `raw_text` above stays verbatim; the English
    # rendering (when one was produced) is stored beside it and is what
    # extraction reads. `language_code` is the detected/declared source.
    #   none (not attempted) | skipped (already English) | translated
    #   | failed | disabled (no key)
    translation_status: Mapped[str] = mapped_column(
        String(16), default="none", server_default=text("'none'")
    )
    language_code: Mapped[Optional[str]] = mapped_column(String(16))
    translated_text: Mapped[Optional[str]] = mapped_column(Text)
    translation_error: Mapped[Optional[str]] = mapped_column(Text)
    translation_model: Mapped[Optional[str]] = mapped_column(String(64))
    translated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def input_text(self) -> str:
        """What extraction reads: the English rendering when one exists,
        otherwise the report exactly as submitted."""
        return self.translated_text or self.raw_text

    user: Mapped[User] = relationship()
    event: Mapped[Optional["ExecutionEvent"]] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )


# ---------------------------------------------------------------------------
# Phase 4: execution events — one structured record per report, produced by
# exactly one LLM call. Every field that the report does not state is NULL:
# the model is told to omit rather than guess, and anything it omits becomes
# null here. Nothing downstream may treat null as a value.
# ---------------------------------------------------------------------------

# Bumped whenever the extraction prompt changes — stored on every event so
# re-extraction after a prompt change is detectable.
PROMPT_VERSION = "v1"


class ExecutionEvent(Base):
    """A structured execution event extracted from one FieldReport."""

    __tablename__ = "execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Evidence chain: every event points at the raw submission it came from.
    field_report_id: Mapped[int] = mapped_column(
        ForeignKey("field_reports.id", ondelete="CASCADE"), unique=True, index=True
    )

    # Extracted fields — null means "not stated in the report", never "zero".
    description: Mapped[Optional[str]] = mapped_column(Text)
    discipline: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    location: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    tag: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    event_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    status: Mapped[Optional[str]] = mapped_column(String(64))
    quantity: Mapped[Optional[float]] = mapped_column(Float)
    progress: Mapped[Optional[float]] = mapped_column(Float)  # percent as stated

    # Audit trail for the extraction itself.
    model: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(32), default=PROMPT_VERSION)
    raw_model_response: Mapped[Optional[str]] = mapped_column(Text)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Phase 8: review lifecycle (PENDING | NEEDS_MANUAL | APPROVED | REJECTED).
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING", index=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text)

    report: Mapped[FieldReport] = relationship(back_populates="event")
    candidates: Mapped[list["MatchCandidate"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    rule_checks: Mapped[list["RuleCheck"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Phase 5: retrieval — embeddings live in their own tables so they can be
# rebuilt (re-import / re-embed) without touching the schedule data.
# ---------------------------------------------------------------------------

class ActivityEmbedding(Base):
    """Vector for ONE leaf activity, embedded once at schedule import."""

    __tablename__ = "activity_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    wbs_node_id: Mapped[int] = mapped_column(
        ForeignKey("wbs_nodes.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text)  # exact text that was embedded
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventEmbedding(Base):
    """Vector for one execution event's description, embedded at intake."""

    __tablename__ = "event_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    execution_event_id: Mapped[int] = mapped_column(
        ForeignKey("execution_events.id", ondelete="CASCADE"), unique=True, index=True
    )
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dim))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchCandidate(Base):
    """One (event, activity) candidate produced by retrieval.

    `score` / `breakdown` hold the retrieval-stage result (Phase 5); Phase 7
    overwrites `score` with the final confidence and extends `breakdown` with
    the rule signals, keeping the individual signals visible either way.
    """

    __tablename__ = "match_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    field_report_id: Mapped[int] = mapped_column(
        ForeignKey("field_reports.id", ondelete="CASCADE"), index=True
    )
    execution_event_id: Mapped[int] = mapped_column(
        ForeignKey("execution_events.id", ondelete="CASCADE"), index=True
    )
    wbs_node_id: Mapped[int] = mapped_column(
        ForeignKey("wbs_nodes.id", ondelete="CASCADE"), index=True
    )
    rank: Mapped[int] = mapped_column(Integer)
    # 0..1 cosine similarity between the event and the activity text.
    semantic_score: Mapped[float] = mapped_column(Float)
    # 0..1 knowledge-graph context bonus (area / discipline / tag / links).
    kg_score: Mapped[float] = mapped_column(Float)
    # Phase 5 score first, then Phase 7 overwrites it with the final
    # confidence (the retrieval-stage value stays visible in `breakdown`).
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Phase 8: the ONE candidate an approval chose (unique per event below).
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    event: Mapped[ExecutionEvent] = relationship(back_populates="candidates")
    activity: Mapped[WbsNode] = relationship()

    __table_args__ = (
        UniqueConstraint("execution_event_id", "wbs_node_id", name="uq_candidate_event_node"),
        # At most one approved candidate per event — an approval is a single
        # choice, never a multi-select.
        Index(
            "uq_match_candidate_approved",
            "execution_event_id",
            unique=True,
            postgresql_where=text("approved_at IS NOT NULL"),
        ),
    )


# ---------------------------------------------------------------------------
# Phase 6: deterministic verification — pure code against the relational
# knowledge graph, never an LLM. Results are tri-state on purpose: `unknown`
# (missing data on either side) is stored as its own outcome and must never
# be collapsed into pass or fail downstream.
# ---------------------------------------------------------------------------

class RuleResult(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class ReviewStatus(str, enum.Enum):
    """Phase 8 lifecycle of a report's execution event.

    NEEDS_MANUAL is set by Phase 7 when nothing scored high enough to
    suggest; it means "a human must map this", not "rejected".
    """

    PENDING = "PENDING"
    NEEDS_MANUAL = "NEEDS_MANUAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RuleCheck(Base):
    """One rule evaluated for one (event, activity) candidate."""

    __tablename__ = "rule_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    execution_event_id: Mapped[int] = mapped_column(
        ForeignKey("execution_events.id", ondelete="CASCADE"), index=True
    )
    wbs_node_id: Mapped[int] = mapped_column(
        ForeignKey("wbs_nodes.id", ondelete="CASCADE"), index=True
    )
    # location | discipline | tag | date_plausibility
    rule: Mapped[str] = mapped_column(String(48))
    result: Mapped[str] = mapped_column(String(16))  # RuleResult.value
    detail: Mapped[Optional[str]] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    event: Mapped[ExecutionEvent] = relationship(back_populates="rule_checks")
    activity: Mapped[WbsNode] = relationship()

    __table_args__ = (
        UniqueConstraint("execution_event_id", "wbs_node_id", "rule", name="uq_rule_event_node"),
    )
