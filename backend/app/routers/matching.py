"""HTTP surface for Phases 4-6: extract, retrieve, verify.

  POST /api/reports/{id}/process   Planner: run (or re-run) the pipeline
  GET  /api/reports/{id}/match     Planner / PM: read the stored result
  POST /api/projects/{id}/embed    Planner: (re)build leaf activity vectors

Auto-processing also runs at intake (Phase 3) whenever extraction can run —
an endpoint on the Phase 11 ladder, or the heuristic rung — so these
endpoints are for re-runs, backfills and the review screen.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    FieldReport,
    MatchCandidate,
    Project,
    Role,
    RuleCheck,
    WbsNode,
)
from ..schemas import (
    ActivitySummary,
    CandidateOut,
    EmbedResponse,
    ExecutionEventOut,
    MatchOut,
    ReportOut,
    RuleCheckOut,
)
from ..security import require_roles
from ..services.embeddings import EmbeddingError, model_name, provider
from ..services.retrieval import index_provider
from ..services.extraction import ExtractionError, get_event
from ..services.llm import LlmError, LlmNotConfigured
from ..services.pipeline import PipelineBlocked, process_report
from ..services.retrieval import embed_activities

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["matching"])


def _report(db: Session, report_id: int) -> FieldReport:
    report = db.get(FieldReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found.")
    return report


def build_match(db: Session, report: FieldReport) -> MatchOut:
    """Assemble the stored event + candidates + rule checks for the UI."""
    event = get_event(db, report)
    candidates: list[CandidateOut] = []

    if event is not None:
        rules_by_node: dict[int, list[RuleCheckOut]] = defaultdict(list)
        for check in db.scalars(
            select(RuleCheck).where(RuleCheck.execution_event_id == event.id)
        ):
            rules_by_node[check.wbs_node_id].append(RuleCheckOut.model_validate(check))

        rows = db.scalars(
            select(MatchCandidate)
            .where(MatchCandidate.execution_event_id == event.id)
            .order_by(MatchCandidate.rank)
        ).all()
        for candidate in rows:
            node = db.get(WbsNode, candidate.wbs_node_id)
            if node is None:
                continue
            breakdown = candidate.breakdown or {}
            confidence = breakdown.get("confidence") or {}
            candidates.append(
                CandidateOut(
                    id=candidate.id,
                    rank=candidate.rank,
                    wbs_node_id=candidate.wbs_node_id,
                    score=candidate.score,
                    semantic_score=candidate.semantic_score,
                    kg_score=candidate.kg_score,
                    breakdown=breakdown,
                    activity=ActivitySummary.model_validate(node),
                    rules=sorted(
                        rules_by_node.get(candidate.wbs_node_id, []),
                        key=lambda r: r.rule,
                    ),
                    confidence_band=confidence.get("band"),
                    approved=candidate.approved_at is not None,
                )
            )

    return MatchOut(
        report=ReportOut.model_validate(report),
        extraction_status=report.extraction_status,
        extraction_error=report.extraction_error,
        event=ExecutionEventOut.model_validate(event) if event is not None else None,
        candidates=candidates,
    )


def _run(db: Session, report: FieldReport, **kwargs) -> MatchOut:
    try:
        process_report(db, report, **kwargs)
    except PipelineBlocked as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except LlmNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except LlmError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    db.refresh(report)
    return build_match(db, report)


@router.post("/reports/{report_id}/process", response_model=MatchOut)
def process_report_endpoint(
    report_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_roles(Role.PLANNER)),
) -> MatchOut:
    """Run extraction -> retrieval -> verification for one report."""
    report = _report(db, report_id)
    return _run(db, report)


@router.get("/reports/{report_id}/match", response_model=MatchOut)
def get_match(
    report_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_roles(Role.PLANNER, Role.PM)),
) -> MatchOut:
    """Read-only view of the event, its candidates and their rule results."""
    return build_match(db, _report(db, report_id))


@router.post("/projects/{project_id}/embed", response_model=EmbedResponse)
def embed_project(
    project_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    user=Depends(require_roles(Role.PLANNER)),
) -> EmbedResponse:
    """Embed (or rebuild) every leaf activity of a project."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    try:
        embedded = embed_activities(db, project_id, force=force)
        db.commit()
    except (LlmError, EmbeddingError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — embedding provider failures
        db.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Embedding failed: {exc}") from exc
    return EmbedResponse(
        project_id=project_id,
        embedded=embedded,
        provider=index_provider(db, project_id) or provider(),
        model=model_name(index_provider(db, project_id) or provider()),
        dim=settings.embedding_dim,
    )
