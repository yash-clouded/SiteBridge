"""Phase 9: roll-up — approved evidence aggregated up the WBS.

Read-only, pure SQL: no LLM, no retrieval, nothing invented. Two rules
shape every number here:

  * an activity counts as **reported** only when Phase 8 actually approved
    evidence against it — an activity nobody has reported on is unreported,
    never 0% complete;
  * progress averages are taken over reported activities THAT STATE a
    progress value. If nobody stated progress the bucket reports ``null``,
    not a fabricated zero.

That keeps coverage ("how much of the schedule do we have evidence for")
and progress ("how far along is the part we have evidence for") separate,
which is the whole point of a roll-up built on field reports.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ExecutionEvent, Project, ReviewStatus, WbsNode
from ..schemas import RollupBucket, RollupOut, RollupSeriesPoint

logger = logging.getLogger(__name__)

UNSTATED = ""  # key used when the schedule field is empty


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _buckets(
    rows: list[tuple[str, bool, float | None, datetime | None, str | None]],
) -> list[RollupBucket]:
    """(key, reported, progress, updated_at, actual_status) -> sorted buckets."""
    grouped: dict[str, list[tuple[bool, float | None, datetime | None, str | None]]] = (
        defaultdict(list)
    )
    for key, reported, progress, updated, status in rows:
        grouped[key].append((reported, progress, updated, status))

    buckets: list[RollupBucket] = []
    for key, values in grouped.items():
        reported_rows = [v for v in values if v[0]]
        progress_values = [v[1] for v in reported_rows if v[1] is not None]
        updates = [v[2] for v in reported_rows if v[2] is not None]
        by_status: dict[str, int] = {}
        for _, _, _, status in reported_rows:
            label = status or UNSTATED
            by_status[label] = by_status.get(label, 0) + 1
        buckets.append(
            RollupBucket(
                key=key,
                activities=len(values),
                reported=len(reported_rows),
                avg_progress=_mean(progress_values),
                last_update=max(updates).date() if updates else None,
                by_status=by_status,
            )
        )
    buckets.sort(key=lambda b: (-b.reported, -b.activities, b.key))
    return buckets


def project_rollup(db: Session, project: Project) -> RollupOut:
    """Aggregate one project's approved evidence. Does not commit."""
    leaves = list(
        db.scalars(
            select(WbsNode).where(WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True))
        ).all()
    )

    # WBS segment for each leaf: the branch directly UNDER the project root
    # ("/1/2/3/8/" -> 2 = "Civil Works"). parts[0] is the root itself, so
    # taking it would put the entire project in one bucket and the roll-up
    # would say nothing about where the work actually is.
    def segment(node: WbsNode) -> int | None:
        parts = [p for p in (node.path or "").split("/") if p]
        if not parts:
            return None
        candidate = parts[1] if len(parts) > 1 else parts[0]
        try:
            return int(candidate)
        except ValueError:
            return None

    top_nodes: dict[int, WbsNode | None] = {}
    for node in leaves:
        key = segment(node)
        if key is not None and key not in top_nodes:
            top_nodes[key] = db.get(WbsNode, key)

    reported_count = 0
    progress_values: list[float] = []
    area_rows = []
    discipline_rows = []
    wbs_rows = []
    last_updates: list[datetime] = []

    for node in leaves:
        reported = node.actual_report_id is not None
        progress = node.actual_progress if reported else None
        updated = node.actual_updated_at if reported else None
        status = node.actual_status if reported else None

        if reported:
            reported_count += 1
            if progress is not None:
                progress_values.append(progress)
            if updated is not None:
                last_updates.append(updated)

        record = (node.id, reported, progress, updated, status)
        area_rows.append((node.area or UNSTATED, *record[1:]))
        discipline_rows.append((node.discipline or UNSTATED, *record[1:]))
        top = top_nodes.get(segment(node) or -1)
        label = UNSTATED
        if top is not None:
            # Container code and name are usually identical — don't print both.
            label = top.name if top.code == top.name else f"{top.code} {top.name}"
        wbs_rows.append((label.strip(), *record[1:]))

    events = list(
        db.scalars(select(ExecutionEvent).where(ExecutionEvent.project_id == project.id)).all()
    )
    counts = {status.value: 0 for status in ReviewStatus}
    per_day: dict[date, int] = defaultdict(int)
    for event in events:
        counts[event.review_status] = counts.get(event.review_status, 0) + 1
        if event.review_status == ReviewStatus.APPROVED.value and event.reviewed_at is not None:
            per_day[event.reviewed_at.date()] += 1

    leaf_count = len(leaves)
    return RollupOut(
        project_id=project.id,
        activities=leaf_count,
        reported=reported_count,
        coverage=round(reported_count / leaf_count, 4) if leaf_count else 0.0,
        avg_progress=_mean(progress_values),
        pending_review=counts.get(ReviewStatus.PENDING.value, 0)
        + counts.get(ReviewStatus.NEEDS_MANUAL.value, 0),
        needs_manual=counts.get(ReviewStatus.NEEDS_MANUAL.value, 0),
        approved=counts.get(ReviewStatus.APPROVED.value, 0),
        rejected=counts.get(ReviewStatus.REJECTED.value, 0),
        by_area=_buckets(area_rows),
        by_discipline=_buckets(discipline_rows),
        by_wbs=_buckets(wbs_rows),
        series=[
            RollupSeriesPoint(day=day, approved=per_day[day]) for day in sorted(per_day)
        ],
        updated_at=max(last_updates) if last_updates else None,
    )
