"""Phases 4 -> 5 -> 6 -> 7 as one pipeline over a single field report.

    report  --(Phase 4: LLM ladder)---->  execution event
            --(Phase 5: pgvector + KG)--> top-K match candidates
            --(Phase 6: pure code)----->  pass/fail/unknown rule checks
            --(Phase 7: pure code)----->  final confidence + re-ranked list

Nothing here invents data: extraction failures leave the report marked
``failed``/``disabled`` with no event, and retrieval/verification simply
have nothing to say. When no LLM answers, Phase 11's heuristic rung reads
the text directly (values the report does not state stay null) and the
event records which rung produced it. Approval (Phase 8) is a separate,
explicit step — this pipeline never writes to a schedule activity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import ExecutionEvent, FieldReport, MatchCandidate, RuleCheck
from .confidence import rank_and_score
from . import heuristic
from .extraction import extract_event, get_event
from .llm import LlmError, LlmNotConfigured
from .retrieval import RetrievalError, retrieve
from .verification import run_rules

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    report: FieldReport
    event: ExecutionEvent | None = None
    candidates: list[MatchCandidate] = field(default_factory=list)
    checks: list[RuleCheck] = field(default_factory=list)
    error: str | None = None

    @property
    def status(self) -> str:
        return self.report.extraction_status


class PipelineBlocked(Exception):
    """The report cannot be (re)processed in its current state."""

    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def process_report(
    db: Session,
    report: FieldReport,
    *,
    top_k: int | None = None,
) -> PipelineResult:
    """Run the pipeline for one report. Commits on success.

    Re-running is safe: candidates and rule checks for the event are
    rebuilt from scratch. Reviewed events (approved/rejected) are never
    re-extracted or re-retrieved — that would rewrite reviewed evidence.
    Read them with GET /api/reports/{id}/match instead.
    """
    event = get_event(db, report)

    if event is not None and event.review_status in {"APPROVED", "REJECTED"}:
        raise PipelineBlocked(
            f"Report {report.id} is {event.review_status} — re-processing would "
            "rewrite reviewed evidence."
        )

    # Phase 11: an event extracted by the heuristic rung is a stand-in, not a
    # result — re-processing upgrades it as soon as an endpoint answers, and
    # simply re-reads the same text when none does. A model-extracted event is
    # final for this endpoint and is only re-run when the report has no event.
    if (
        event is None
        or report.extraction_status != "extracted"
        or event.model == heuristic.MODEL
    ):
        event = extract_event(db, report)  # Phase 4 (raises on failure)

    candidates = retrieve(db, event, top_k=top_k)  # Phase 5
    checks = run_rules(db, event, candidates)  # Phase 6
    rank_and_score(event, candidates, checks)  # Phase 7
    db.commit()
    db.refresh(event)
    return PipelineResult(report, event, candidates, checks)


def auto_process(db: Session, report: FieldReport, *, top_k: int | None = None) -> PipelineResult:
    """Best-effort run used at intake — never breaks the submission itself.

    If no LLM is configured the report is marked ``disabled`` and the raw
    evidence is kept exactly as submitted.
    """
    try:
        return process_report(db, report, top_k=top_k)
    except (LlmNotConfigured, LlmError) as exc:
        logger.info("Skipping extraction for report %s: %s", report.id, exc)
        db.rollback()
        return PipelineResult(report, error=str(exc))
    except Exception as exc:  # noqa: BLE001 — intake must not fail on the AI layer
        logger.exception("Pipeline failed for report %s", report.id)
        db.rollback()
        return PipelineResult(report, error=str(exc))
