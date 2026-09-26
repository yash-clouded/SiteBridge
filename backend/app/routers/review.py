"""Phase 8 HTTP surface: the review queue and its three actions.

  GET  /api/queue                 Planner / PM: everything awaiting a decision
  POST /api/reports/{id}/approve  Planner: accept a candidate -> activity actuals
  POST /api/reports/{id}/reject   Planner: refuse the match, keep the evidence
  POST /api/reports/{id}/reopen   Planner: send a decision back to the queue

PM is read-only by design: it can open the queue and every match, but the
three mutations are PLANNER-only (403 otherwise).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    ExecutionEvent,
    FieldReport,
    MatchCandidate,
    ReviewStatus,
    Role,
    RuleCheck,
    WbsNode,
)
from ..schemas import (
    ActivitySummary,
    ApproveRequest,
    ExecutionEventOut,
    MatchOut,
    QueueItem,
    QueueOut,
    QueueTop,
    ReportOut,
    ReviewNote,
    RuleCheckOut,
)
from ..security import roles_for
from ..services.review import ReviewError, approve, reject, reopen
from .matching import build_match

router = APIRouter(prefix="/api", tags=["review"])

PENDING_STATES = {
    ReviewStatus.PENDING.value,
    ReviewStatus.NEEDS_MANUAL.value,
}


def _report(db: Session, report_id: int) -> FieldReport:
    report = db.get(FieldReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found.")
    return report


@router.get("/queue", response_model=QueueOut)
def review_queue(
    project_id: Optional[int] = None,
    filter: str = "all",  # all | pending | approved | rejected
    limit: int = 100,
    db: Session = Depends(get_db),
    user=Depends(roles_for("review")) ,
) -> QueueOut:
    """Reports with their top candidate — the planner's work list."""
    query = (
        select(FieldReport)
        .order_by(FieldReport.created_at.desc(), FieldReport.id.desc())
        .limit(max(1, min(limit, 500)))
    )
    if project_id is not None:
        query = query.where(FieldReport.project_id == project_id)
    reports = list(db.scalars(query).all())
    report_ids = [r.id for r in reports] or [-1]

    events = {
        e.field_report_id: e
        for e in db.scalars(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id.in_(report_ids))
        ).all()
    }
    event_ids = [e.id for e in events.values()] or [-1]

    candidates: dict[int, list[MatchCandidate]] = defaultdict(list)
    for candidate in db.scalars(
        select(MatchCandidate)
        .where(MatchCandidate.execution_event_id.in_(event_ids))
        .order_by(MatchCandidate.rank)
    ).all():
        candidates[candidate.execution_event_id].append(candidate)

    rules: dict[tuple[int, int], list[RuleCheck]] = defaultdict(list)
    for check in db.scalars(
        select(RuleCheck).where(RuleCheck.execution_event_id.in_(event_ids))
    ).all():
        rules[(check.execution_event_id, check.wbs_node_id)].append(check)

    node_ids = {c.wbs_node_id for rows in candidates.values() for c in rows} or {-1}
    nodes = {
        node.id: node
        for node in db.scalars(select(WbsNode).where(WbsNode.id.in_(node_ids))).all()
    }

    counts: dict[str, int] = {
        "all": 0,
        "pending": 0,  # awaiting a decision (PENDING + NEEDS_MANUAL)
        "needs_manual": 0,  # ... of those, flagged for manual mapping
        "approved": 0,
        "rejected": 0,
        "no_event": 0,
    }
    items: list[QueueItem] = []
    for report in reports:
        event = events.get(report.id)
        review_status = event.review_status if event is not None else None

        counts["all"] += 1
        if review_status is None:
            counts["no_event"] += 1
        elif review_status in PENDING_STATES:
            counts["pending"] += 1
            if review_status == ReviewStatus.NEEDS_MANUAL.value:
                counts["needs_manual"] += 1
        elif review_status == ReviewStatus.APPROVED.value:
            counts["approved"] += 1
        elif review_status == ReviewStatus.REJECTED.value:
            counts["rejected"] += 1

        top = None
        rows = candidates.get(event.id, []) if event is not None else []
        if rows and rows[0].wbs_node_id in nodes:
            best = rows[0]
            confidence = (best.breakdown or {}).get("confidence") or {}
            top = QueueTop(
                candidate_id=best.id,
                wbs_node_id=best.wbs_node_id,
                score=best.score,
                confidence_band=confidence.get("band"),
                activity=ActivitySummary.model_validate(nodes[best.wbs_node_id]),
                rules=[
                    RuleCheckOut.model_validate(c)
                    for c in sorted(
                        rules.get((event.id, best.wbs_node_id), []), key=lambda r: r.rule
                    )
                ],
            )

        if filter == "pending" and not (review_status in PENDING_STATES or review_status is None):
            continue
        if filter == "approved" and review_status != ReviewStatus.APPROVED.value:
            continue
        if filter == "rejected" and review_status != ReviewStatus.REJECTED.value:
            continue

        items.append(
            QueueItem(
                report=ReportOut.model_validate(report),
                event=ExecutionEventOut.model_validate(event) if event is not None else None,
                review_status=review_status,
                top=top,
                candidate_count=len(rows),
            )
        )

    return QueueOut(project_id=project_id, items=items, counts=counts)


def _resolve(db: Session, report_id: int, action, user, **kwargs) -> MatchOut:
    report = _report(db, report_id)
    try:
        action(db, report, user=user, **kwargs)
    except ReviewError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    db.refresh(report)
    return build_match(db, report)


@router.post("/reports/{report_id}/approve", response_model=MatchOut)
def approve_endpoint(
    report_id: int,
    payload: Optional[ApproveRequest] = None,
    db: Session = Depends(get_db),
    user=Depends(roles_for("review")),
) -> MatchOut:
    """Approve a candidate (default: rank 1) and publish the activity actuals."""
    body = payload or ApproveRequest()
    return _resolve(
        db,
        report_id,
        approve,
        user,
        candidate_id=body.candidate_id,
        note=body.note,
    )


@router.post("/reports/{report_id}/reject", response_model=MatchOut)
def reject_endpoint(
    report_id: int,
    payload: Optional[ReviewNote] = None,
    db: Session = Depends(get_db),
    user=Depends(roles_for("review")),
) -> MatchOut:
    """Refuse the match; the report and its evidence are kept intact."""
    body = payload or ReviewNote()
    return _resolve(db, report_id, reject, user, note=body.note)


@router.post("/reports/{report_id}/reopen", response_model=MatchOut)
def reopen_endpoint(
    report_id: int,
    payload: Optional[ReviewNote] = None,
    db: Session = Depends(get_db),
    user=Depends(roles_for("review")),
) -> MatchOut:
    """Undo a decision: back to PENDING, actuals this report wrote are cleared."""
    body = payload or ReviewNote()
    return _resolve(db, report_id, reopen, user, note=body.note)
