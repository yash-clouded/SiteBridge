"""Phase 7: confidence — one number and one band per candidate.

Phases 5 and 6 leave two separate answers on each (event, activity)
candidate: how alike they *look* (semantic cosine + knowledge-graph
context) and what the deterministic rules *decided* about them. A planner
cannot act on two numbers, so this module folds them into a single
confidence score, re-ranks the list, and flags the candidates that no
human should trust.

The formula is deliberately boring and printed into the breakdown:

    final = w_r * retrieval + w_w * rules          (weights from settings)

    retrieval  Phase 5 score, already 0.7*cosine + 0.3*kg
    rules      passed / (passed + failed) over the DECIDABLE Phase 6 rules

``unknown`` rules are excluded from the ratio rather than counted as
failures: missing data can neither raise nor lower confidence. When no
rule is decidable the weights renormalise onto retrieval alone, and the
breakdown says so instead of pretending rules agreed.

Nothing here invents evidence — it only ranks what Phases 4-6 produced.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from ..config import settings
from ..models import ExecutionEvent, MatchCandidate, ReviewStatus, RuleCheck, RuleResult

logger = logging.getLogger(__name__)

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


class ConfidenceError(Exception):
    """Confidence could not be computed (bad configuration or empty input)."""


def band_for(score: float) -> str:
    if score >= settings.confidence_high:
        return HIGH
    if score >= settings.confidence_medium:
        return MEDIUM
    return LOW


def rule_summary(checks: list[RuleCheck]) -> dict:
    counts = {RuleResult.PASS.value: 0, RuleResult.FAIL.value: 0, RuleResult.UNKNOWN.value: 0}
    for check in checks:
        counts[check.result] = counts.get(check.result, 0) + 1

    decidable = counts[RuleResult.PASS.value] + counts[RuleResult.FAIL.value]
    score = counts[RuleResult.PASS.value] / decidable if decidable else None
    return {
        "score": None if score is None else round(score, 6),
        "pass": counts[RuleResult.PASS.value],
        "fail": counts[RuleResult.FAIL.value],
        "unknown": counts[RuleResult.UNKNOWN.value],
        "decidable": decidable,
        "total": len(checks),
        "weight": settings.confidence_rule_weight,
    }


def combine(retrieval_score: float, rule_score: float | None) -> tuple[float, str]:
    """Return (final score clamped to 0..1, formula actually applied)."""
    w_retrieval = settings.confidence_retrieval_weight
    w_rules = settings.confidence_rule_weight

    if rule_score is None:
        # No decidable rules -> their weight transfers to retrieval, so the
        # score is the retrieval score exactly (not a fraction of it).
        final = retrieval_score
        formula = "retrieval only (no decidable rules)"
    else:
        final = w_retrieval * retrieval_score + w_rules * rule_score
        formula = f"{w_retrieval:.2f}*retrieval + {w_rules:.2f}*rules"

    return max(0.0, min(1.0, final)), formula


def rank_and_score(
    event: ExecutionEvent,
    candidates: list[MatchCandidate],
    checks: list[RuleCheck],
) -> list[MatchCandidate]:
    """Score every candidate, re-rank in place, and flag low confidence.

    Mutates the ORM rows (``score``, ``breakdown``, ``rank``) and, when the
    event is still awaiting review, its ``review_status``. Does not commit —
    the caller owns the transaction.
    """
    if not candidates:
        # Nothing retrieved (usually: the report yielded no embeddable text).
        # The report stays PENDING so it still shows up in the queue — a
        # missing candidate is an extraction problem, not a weak match, and
        # NEEDS_MANUAL is reserved for "we found options and none are safe".
        logger.info("Event %s has no candidates to score", event.id)
        return []

    checks_by_node: dict[int, list[RuleCheck]] = defaultdict(list)
    for check in checks:
        checks_by_node[check.wbs_node_id].append(check)

    for candidate in candidates:
        # Read the Phase 5 value before overwriting it with the final score.
        retrieval_score = candidate.score
        summary = rule_summary(checks_by_node.get(candidate.wbs_node_id, []))
        final, formula = combine(retrieval_score, summary["score"])
        breakdown = dict(candidate.breakdown or {})
        breakdown["confidence"] = {
            "final": round(final, 6),
            "band": band_for(final),
            "retrieval": round(retrieval_score, 6),
            "rules": summary,
            "formula": formula,
        }
        candidate.score = final
        candidate.breakdown = breakdown

    ordered = sorted(
        candidates,
        key=lambda c: (-c.score, -c.semantic_score, c.wbs_node_id),
    )
    for position, candidate in enumerate(ordered, start=1):
        candidate.rank = position

    _sync_review_status(event, band_for(ordered[0].score))
    return ordered


def _sync_review_status(event: ExecutionEvent, top_band: str) -> None:
    """Only PENDING <-> NEEDS_MANUAL moves here; approvals are Phase 8."""
    awaiting = {ReviewStatus.PENDING.value, ReviewStatus.NEEDS_MANUAL.value}
    if event.review_status not in awaiting:
        return
    target = (
        ReviewStatus.NEEDS_MANUAL.value if top_band == LOW else ReviewStatus.PENDING.value
    )
    if event.review_status != target:
        event.review_status = target
        logger.info("Event %s review status -> %s (top band %s)", event.id, target, top_band)
