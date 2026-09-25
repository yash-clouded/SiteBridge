"""Phase 6: deterministic verification — pure code, no LLM.

Four rules run against the knowledge-graph tables for every candidate:

  location         event.location  vs the activity's area (WBS ancestors too)
  discipline       event.discipline vs the activity's discipline
  tag              event.tag        vs the activity's equipment tag
  date_plausibility event date vs the status of the activity's predecessors

Every rule returns ``pass`` / ``fail`` / ``unknown``. ``unknown`` means the
data needed to decide is missing on one side — it is stored as ``unknown``
and must never be counted as a pass or a fail anywhere downstream.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import ExecutionEvent, MatchCandidate, RuleCheck, RuleResult, WbsNode
from .retrieval import compare

logger = logging.getLogger(__name__)

LOCATION = "location"
DISCIPLINE = "discipline"
TAG = "tag"
DATE_PLAUSIBILITY = "date_plausibility"
RULES = (LOCATION, DISCIPLINE, TAG, DATE_PLAUSIBILITY)

# Status vocabulary that is recognised. Anything else (e.g. "mechanically
# complete", "punch list") is deliberately NOT guessed at -> unknown.
COMPLETE_STATUSES = {"complete", "completed", "done", "finished", "closed"}
INCOMPLETE_STATUSES = {
    "not started",
    "in progress",
    "started",
    "wip",
    "on hold",
    "hold",
    "delayed",
    "pending",
    "open",
    "active",
}


class VerificationError(Exception):
    """A rule could not be evaluated because of an internal problem."""


def is_complete(status: str | None) -> bool | None:
    """Tri-state: True / False / None (None = vocabulary not recognised)."""
    if not status:
        return None
    cleaned = re.sub(r"\s+", " ", status.strip().lower())
    if not cleaned:
        return None
    match = re.search(r"\d+(?:\.\d+)?", cleaned)
    if match:
        return float(match.group(0)) >= 100
    if cleaned in COMPLETE_STATUSES:
        return True
    if cleaned in INCOMPLETE_STATUSES:
        return False
    return None


def _field_rule(event_value: str | None, activity_value: str | None) -> tuple[str, str]:
    result = compare(event_value, activity_value)
    if result is None:
        missing = "event does not state it" if not event_value else "activity has no value"
        return (
            RuleResult.UNKNOWN.value,
            f"cannot compare: {missing} (event={event_value!r}, activity={activity_value!r})",
        )
    if result:
        return RuleResult.PASS.value, f"{event_value!r} matches {activity_value!r}"
    return RuleResult.FAIL.value, f"{event_value!r} does not match {activity_value!r}"


def _location_rule(event: ExecutionEvent, node: WbsNode) -> tuple[str, str]:
    result = compare(event.location, node.area)
    if result is None:
        missing = (
            "event does not state a location" if not event.location else "activity has no area"
        )
        return (
            RuleResult.UNKNOWN.value,
            f"cannot compare: {missing} (event={event.location!r}, activity={node.area!r})",
        )
    if result:
        return RuleResult.PASS.value, f"{event.location!r} matches area {node.area!r}"
    return RuleResult.FAIL.value, f"{event.location!r} does not match area {node.area!r}"


def _activity_state(db: Session, node: WbsNode) -> tuple[str | None, date | None]:
    """Status and date the activity was last APPROVED at.

    Reads the approval chain (candidate -> approved event). Phase 8 also
    writes the outcome onto the activity itself; until an approval exists
    both values are None and dependent rules report unknown.
    """
    row = db.execute(
        select(ExecutionEvent.status, ExecutionEvent.event_date)
        .join(MatchCandidate, MatchCandidate.execution_event_id == ExecutionEvent.id)
        .where(
            MatchCandidate.wbs_node_id == node.id,
            ExecutionEvent.review_status == "APPROVED",
        )
        .order_by(ExecutionEvent.event_date.desc().nulls_last())
        .limit(1)
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


def _date_rule(db: Session, event: ExecutionEvent, node: WbsNode) -> tuple[str, str]:
    if event.event_date is None:
        return RuleResult.UNKNOWN.value, "event states no date"

    pred_codes = [c for c in node.predecessor_ids if c]
    if not pred_codes:
        return RuleResult.UNKNOWN.value, "activity has no predecessors"

    failures: list[str] = []
    unknowns: list[str] = []
    passes: list[str] = []

    for code in pred_codes:
        pred = db.scalar(
            select(WbsNode).where(
                WbsNode.project_id == node.project_id, WbsNode.code == code
            )
        )
        if pred is None:
            unknowns.append(f"predecessor {code} is not in this schedule")
            continue
        status, state_date = _activity_state(db, pred)
        complete = is_complete(status)
        if complete is None:
            unknowns.append(
                f"predecessor {code} has no approved status"
                if status is None
                else f"predecessor {code} status {status!r} is not a recognised completion state"
            )
            continue
        if state_date is None:
            unknowns.append(f"predecessor {code} has an approved status but no date")
            continue
        if not complete:
            failures.append(f"predecessor {code} is {status!r}, not complete")
            continue
        if state_date > event.event_date:
            failures.append(
                f"predecessor {code} completed {state_date.isoformat()}, "
                f"after the event date {event.event_date.isoformat()}"
            )
            continue
        passes.append(f"predecessor {code} completed {state_date.isoformat()}")

    if failures:
        return RuleResult.FAIL.value, "; ".join(failures)
    if unknowns:
        return RuleResult.UNKNOWN.value, "; ".join(unknowns)
    return RuleResult.PASS.value, "; ".join(passes)


def evaluate(
    db: Session, event: ExecutionEvent, node: WbsNode
) -> list[tuple[str, str, str]]:
    """Run all rules for one (event, activity) pair -> [(rule, result, detail)]."""
    return [
        (LOCATION, *_location_rule(event, node)),
        (DISCIPLINE, *_field_rule(event.discipline, node.discipline)),
        (TAG, *_field_rule(event.tag, node.equipment_tag)),
        (DATE_PLAUSIBILITY, *_date_rule(db, event, node)),
    ]


def run_rules(
    db: Session, event: ExecutionEvent, candidates: list[MatchCandidate]
) -> list[RuleCheck]:
    """Verify every candidate. Replaces previous checks. Does not commit."""
    db.execute(delete(RuleCheck).where(RuleCheck.execution_event_id == event.id))
    db.flush()

    checks: list[RuleCheck] = []
    for candidate in candidates:
        node = db.get(WbsNode, candidate.wbs_node_id)
        if node is None:
            continue
        for rule, result, detail in evaluate(db, event, node):
            checks.append(
                RuleCheck(
                    execution_event_id=event.id,
                    wbs_node_id=node.id,
                    rule=rule,
                    result=result,
                    detail=detail,
                )
            )
    db.add_all(checks)
    db.flush()
    logger.info("Verified %s candidates for event %s", len(candidates), event.id)
    return checks
