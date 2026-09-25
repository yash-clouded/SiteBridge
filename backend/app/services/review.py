"""Phase 8: review — the only code allowed to write to a schedule activity.

Everything upstream (Phases 4-7) produces evidence and opinion; nothing of
it changes the schedule. The transition happens here, explicitly, by a
Planner:

    PENDING / NEEDS_MANUAL --approve--> APPROVED  (also writes activity actuals)
    PENDING / NEEDS_MANUAL / APPROVED --reject--> REJECTED
    APPROVED / REJECTED / NEEDS_MANUAL --reopen--> PENDING

Rules the review obeys:
  * exactly one candidate can be approved per event (DB index enforces it);
  * approving twice with the same candidate is a no-op, with a different
    one is a 409 — change your mind by reopening first;
  * actuals always describe the ONE report being approved. Values the
    report does not state become NULL rather than being carried over from
    an earlier approval, so `actual_report_id` is a real provenance link;
  * undoing an approval (reject/reopen) clears the actuals that approval
    wrote, and only those.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    ExecutionEvent,
    FieldReport,
    MatchCandidate,
    ReviewStatus,
    User,
    WbsNode,
)
from .extraction import get_event

logger = logging.getLogger(__name__)


class ReviewError(Exception):
    """A review action is not possible in the report's current state."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event(db: Session, report: FieldReport) -> ExecutionEvent:
    event = get_event(db, report)
    if event is None:
        raise ReviewError(
            f"Report {report.id} has no execution event yet — run the pipeline first.",
            409,
        )
    return event


def _candidate(db: Session, event: ExecutionEvent, candidate_id: int | None) -> MatchCandidate:
    rows = db.scalars(
        select(MatchCandidate)
        .where(MatchCandidate.execution_event_id == event.id)
        .order_by(MatchCandidate.rank)
    ).all()
    if not rows:
        raise ReviewError(
            f"Event {event.id} has no match candidates — nothing to approve.",
            409,
        )
    if candidate_id is None:
        return rows[0]  # top-ranked candidate is the default choice
    for row in rows:
        if row.id == candidate_id:
            return row
    raise ReviewError(f"Candidate {candidate_id} does not belong to event {event.id}.", 404)


def approved_candidate(db: Session, event: ExecutionEvent) -> MatchCandidate | None:
    return db.scalar(
        select(MatchCandidate)
        .where(
            MatchCandidate.execution_event_id == event.id,
            MatchCandidate.approved_at.is_not(None),
        )
        .limit(1)
    )


def _clear_approval(db: Session, event: ExecutionEvent) -> None:
    for candidate in event.candidates:
        candidate.approved_at = None
        candidate.approved_by = None


def _clear_actuals(db: Session, report: FieldReport) -> None:
    """Remove activity actuals THIS report wrote (never someone else's)."""
    nodes = db.scalars(
        select(WbsNode).where(WbsNode.actual_report_id == report.id)
    ).all()
    for node in nodes:
        node.actual_status = None
        node.actual_progress = None
        node.actual_date = None
        node.actual_report_id = None
        node.actual_updated_at = None
        logger.info("Cleared actuals on activity %s (report %s reopened)", node.code, report.id)


def _write_actuals(db: Session, event: ExecutionEvent, candidate: MatchCandidate) -> None:
    """Copy the approved report's facts onto the activity it matched."""
    node = db.get(WbsNode, candidate.wbs_node_id)
    if node is None:
        raise ReviewError(f"Activity {candidate.wbs_node_id} no longer exists.", 409)
    # Full overwrite on purpose: actuals describe exactly this report, so
    # provenance stays a single id instead of a merge of several approvals.
    node.actual_status = event.status
    node.actual_progress = event.progress
    node.actual_date = event.event_date
    node.actual_report_id = event.field_report_id
    node.actual_updated_at = _now()


def approve(
    db: Session,
    report: FieldReport,
    user: User,
    *,
    candidate_id: int | None = None,
    note: str | None = None,
) -> ExecutionEvent:
    """Approve one candidate for the report's event and publish its actuals."""
    event = _event(db, report)
    chosen = _candidate(db, event, candidate_id)

    if event.review_status == ReviewStatus.APPROVED.value:
        current = approved_candidate(db, event)
        if current is not None and current.id == chosen.id:
            return event  # idempotent: approving the same choice twice
        raise ReviewError(
            f"Report {report.id} is already approved"
            + (f" against {current.activity.code}" if current else "")
            + " — reopen it before choosing a different activity.",
        )

    _clear_approval(db, event)
    chosen.approved_at = _now()
    chosen.approved_by = user.id

    event.review_status = ReviewStatus.APPROVED.value
    event.reviewed_at = _now()
    event.reviewed_by = user.id
    event.review_note = note

    _write_actuals(db, event, chosen)
    db.commit()
    db.refresh(event)
    logger.info(
        "Report %s approved by %s -> activity %s (confidence %.3f)",
        report.id,
        user.email,
        chosen.activity.code if chosen.activity else chosen.wbs_node_id,
        chosen.score,
    )
    return event


def reject(db: Session, report: FieldReport, user: User, *, note: str | None = None) -> ExecutionEvent:
    """Reject the report's match — the evidence is kept, the claim is refused."""
    event = _event(db, report)
    if event.review_status == ReviewStatus.REJECTED.value:
        return event

    _clear_approval(db, event)
    _clear_actuals(db, report)
    event.review_status = ReviewStatus.REJECTED.value
    event.reviewed_at = _now()
    event.reviewed_by = user.id
    event.review_note = note
    db.commit()
    db.refresh(event)
    logger.info("Report %s rejected by %s", report.id, user.email)
    return event


def reopen(db: Session, report: FieldReport, user: User, *, note: str | None = None) -> ExecutionEvent:
    """Return a reviewed report to the queue (and un-publish its actuals)."""
    event = _event(db, report)
    if event.review_status == ReviewStatus.PENDING.value:
        return event

    _clear_approval(db, event)
    _clear_actuals(db, report)
    event.review_status = ReviewStatus.PENDING.value
    event.reviewed_at = _now()
    event.reviewed_by = user.id
    event.review_note = note or "reopened for review"
    db.commit()
    db.refresh(event)
    logger.info("Report %s reopened by %s", report.id, user.email)
    return event
