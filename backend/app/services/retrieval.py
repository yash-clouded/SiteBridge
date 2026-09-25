"""Phase 5: retrieval — vector search plus knowledge-graph re-scoring.

Flow (all pure data access, no LLM):

  1. leaf activity descriptions are embedded ONCE at schedule import;
  2. the execution event's description is embedded when it is extracted;
  3. the top-K activities are pulled out of pgvector by cosine distance;
  4. the relational knowledge graph (area, discipline, equipment tag,
     predecessor/successor links, WBS ancestors) re-scores those K.

Signals that cannot be evaluated (missing field on either side) are recorded
as ``unknown`` and left out of the knowledge-graph score — they are never
counted as a match or a mismatch.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    ActivityEmbedding,
    EventEmbedding,
    ExecutionEvent,
    MatchCandidate,
    RuleCheck,
    WbsNode,
)
from .embeddings import embed_texts, model_name, provider

logger = logging.getLogger(__name__)

# Weight of the knowledge-graph signal when at least one signal is known.
KG_WEIGHT = 0.30
MATCH = "match"
MISMATCH = "mismatch"
UNKNOWN = "unknown"

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


class RetrievalError(Exception):
    """Retrieval cannot run (usually an embedding problem)."""


def _norm(value: str | None) -> str:
    if not value:
        return ""
    return _TOKEN_RE.sub(" ", value.lower()).strip()


def compare(left: str | None, right: str | None) -> bool | None:
    """Tri-state comparison used by both re-scoring and verification.

    None means "cannot be judged" (a side is missing) — callers must not
    turn it into True or False.
    """
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return None
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    return False


def activity_text(node: WbsNode) -> str:
    """The exact string embedded for a leaf activity (stable, rebuildable)."""
    parts = [f"{node.code}: {node.name}"]
    if node.discipline:
        parts.append(f"Discipline: {node.discipline}")
    if node.area:
        parts.append(f"Area: {node.area}")
    if node.equipment_tag:
        parts.append(f"Tag: {node.equipment_tag}")
    return ". ".join(parts)


def event_text(event: ExecutionEvent) -> str:
    """Description if present, otherwise whatever the event does state."""
    if event.description:
        return event.description
    parts = []
    if event.discipline:
        parts.append(f"Discipline: {event.discipline}")
    if event.location:
        parts.append(f"Area: {event.location}")
    if event.tag:
        parts.append(f"Tag: {event.tag}")
    if event.status:
        parts.append(f"Status: {event.status}")
    return ". ".join(parts)


def embed_activities(db: Session, project_id: int, *, force: bool = False) -> int:
    """Embed every leaf activity of a project (idempotent, does not commit).

    Called once at import; safe to re-run to backfill or rebuild.
    """
    leaves = list(
        db.scalars(
            select(WbsNode).where(WbsNode.project_id == project_id, WbsNode.is_leaf.is_(True))
        ).all()
    )
    existing = {
        row.wbs_node_id: row
        for row in db.scalars(
            select(ActivityEmbedding).where(ActivityEmbedding.project_id == project_id)
        ).all()
    }
    todo = [n for n in leaves if force or n.id not in existing]
    if not todo:
        return 0

    texts = [activity_text(n) for n in todo]
    vectors = embed_texts(texts, role="index")
    for node, text, vector in zip(todo, texts, vectors):
        row = existing.get(node.id)
        if row is None:
            db.add(
                ActivityEmbedding(
                    project_id=project_id,
                    wbs_node_id=node.id,
                    content=text,
                    provider=provider(),
                    model=model_name(),
                    embedding=vector,
                )
            )
        else:
            row.content = text
            row.provider = provider()
            row.model = model_name()
            row.embedding = vector
    db.flush()
    logger.info("Embedded %s activities for project %s", len(todo), project_id)
    return len(todo)


def embed_event(db: Session, event: ExecutionEvent) -> EventEmbedding | None:
    """Embed one event description (does not commit). None when there is no text."""
    text = event_text(event)
    row = db.scalar(
        select(EventEmbedding).where(EventEmbedding.execution_event_id == event.id)
    )
    if not text.strip():
        if row is not None:
            db.delete(row)
        return None

    vector = embed_texts([text], role="query")[0]
    if row is None:
        row = EventEmbedding(
            project_id=event.project_id,
            execution_event_id=event.id,
            content=text,
            provider=provider(),
            model=model_name(),
            embedding=vector,
        )
        db.add(row)
    else:
        row.content = text
        row.provider = provider()
        row.model = model_name()
        row.embedding = vector
    db.flush()
    return row


def _ancestor_names(db: Session, node: WbsNode) -> list[str]:
    """Names of the container nodes above this activity (area context)."""
    names: list[str] = []
    current = node.parent
    seen = 0
    while current is not None and seen < 32:
        names.append(current.name)
        current = current.parent
        seen += 1
    return names


def _signal(event_value: Any, activity_value: Any) -> dict[str, Any]:
    result = compare(event_value, activity_value)
    return {
        "result": UNKNOWN if result is None else (MATCH if result else MISMATCH),
        "event": event_value,
        "activity": activity_value,
    }


def _area_signal(event: ExecutionEvent, node: WbsNode, ancestors: list[str]) -> dict[str, Any]:
    """Location vs the activity's area, falling back to its WBS ancestors."""
    detail: dict[str, Any] = {"event": event.location, "activity": node.area}
    if not event.location:
        detail["result"] = UNKNOWN
        detail["why"] = "event states no location"
        return detail

    direct = compare(event.location, node.area) if node.area else None
    ancestor_hits = [a for a in ancestors if compare(event.location, a) is True]
    if direct is True or ancestor_hits:
        detail["result"] = MATCH
        if ancestor_hits and direct is not True:
            detail["via"] = ancestor_hits[0]
        return detail
    if direct is False:
        detail["result"] = MISMATCH
        return detail

    known_ancestors = [a for a in ancestors if a]
    judged = [compare(event.location, a) for a in known_ancestors]
    if known_ancestors and all(j is False for j in judged):
        detail["result"] = MISMATCH
        detail["via"] = "ancestors"
        return detail
    detail["result"] = UNKNOWN
    detail["why"] = "activity has no area and no matching ancestor"
    return detail


def _linked_signal(node: WbsNode, other_codes: set[str]) -> dict[str, Any]:
    refs = [r for r in (*node.predecessor_ids, *node.successor_ids) if r]
    hits = sorted(set(refs) & other_codes)
    return {
        "result": MATCH if hits else MISMATCH,
        "linked_to": hits,
        "why": "predecessor/successor of another candidate" if hits else "no link to other candidates",
    }


def knowledge_graph_score(
    event: ExecutionEvent,
    node: WbsNode,
    ancestors: list[str],
    other_codes: set[str],
) -> tuple[float, dict[str, Any]]:
    """Contextual re-score inputs for one candidate.

    Returns (score in 0..1, breakdown). Unknown signals are excluded from
    the average rather than being scored as 0 or 1.
    """
    signals = {
        "area": _area_signal(event, node, ancestors),
        "discipline": _signal(event.discipline, node.discipline),
        "tag": _signal(event.tag, node.equipment_tag),
        "links": _linked_signal(node, other_codes),
    }
    known = [s for s in signals.values() if s["result"] != UNKNOWN]
    if known:
        score = sum(1.0 if s["result"] == MATCH else 0.0 for s in known) / len(known)
    else:
        score = 0.0
    return score, {
        "score": round(score, 6),
        "known_signals": len(known),
        "weight": KG_WEIGHT,
        "signals": signals,
    }


@dataclass
class _Hit:
    """One vector-search result before scoring."""

    node: WbsNode
    distance: float


def _vector_hits(db: Session, event: ExecutionEvent, vector: list[float], k: int) -> list[_Hit]:
    distance = ActivityEmbedding.embedding.cosine_distance(vector)
    rows = db.execute(
        select(WbsNode, distance.label("dist"))
        .join(ActivityEmbedding, ActivityEmbedding.wbs_node_id == WbsNode.id)
        .where(
            ActivityEmbedding.project_id == event.project_id,
            WbsNode.is_leaf.is_(True),
        )
        .order_by(distance)
        .limit(k)
    ).all()
    return [_Hit(node=node, distance=float(dist)) for node, dist in rows]


def _is_zero(vector: list[float]) -> bool:
    return not any(v for v in vector)


def retrieve(db: Session, event: ExecutionEvent, *, top_k: int | None = None) -> list[MatchCandidate]:
    """Build the candidate list for an event. Replaces any previous run.

    Does not commit — callers own the transaction.
    """
    k = top_k or settings.retrieval_top_k

    # Idempotent re-run: drop the previous retrieval for this event.
    db.execute(delete(RuleCheck).where(RuleCheck.execution_event_id == event.id))
    db.execute(delete(MatchCandidate).where(MatchCandidate.execution_event_id == event.id))
    db.flush()

    embed_event(db, event)
    if (
        db.scalar(
            select(ActivityEmbedding.id).where(ActivityEmbedding.project_id == event.project_id)
        )
        is None
    ):
        embed_activities(db, event.project_id)

    event_row = db.scalar(
        select(EventEmbedding).where(EventEmbedding.execution_event_id == event.id)
    )
    if event_row is None or _is_zero(event_row.embedding):
        logger.info("Event %s has no embeddable text — no candidates.", event.id)
        return []

    hits = _vector_hits(db, event, list(event_row.embedding), k)
    if not hits:
        logger.info("No embedded activities for project %s.", event.project_id)
        return []

    candidate_codes = {h.node.code for h in hits}
    scored: list[tuple[float, float, dict[str, Any], _Hit]] = []
    for hit in hits:
        semantic = max(0.0, min(1.0, 1.0 - hit.distance))
        kg, kg_breakdown = knowledge_graph_score(
            event, hit.node, _ancestor_names(db, hit.node), candidate_codes - {hit.node.code}
        )
        known = kg_breakdown["known_signals"] > 0
        score = (
            round((1 - KG_WEIGHT) * semantic + KG_WEIGHT * kg, 6)
            if known
            else round(semantic, 6)
        )
        breakdown = {
            "semantic": round(semantic, 6),
            "cosine_distance": round(hit.distance, 6),
            "kg": kg_breakdown,
            "formula": (
                f"{round(1 - KG_WEIGHT, 2)}*semantic + {KG_WEIGHT}*kg"
                if known
                else "semantic (no knowledge-graph signal available)"
            ),
        }
        scored.append((score, semantic, {"breakdown": breakdown, "kg": kg}, hit))

    scored.sort(key=lambda item: item[0], reverse=True)

    candidates: list[MatchCandidate] = []
    for rank, (score, semantic, extra, hit) in enumerate(scored, start=1):
        candidate = MatchCandidate(
            project_id=event.project_id,
            field_report_id=event.field_report_id,
            execution_event_id=event.id,
            wbs_node_id=hit.node.id,
            rank=rank,
            semantic_score=round(semantic, 6),
            kg_score=round(extra["kg"], 6),
            score=score,
            breakdown=extra["breakdown"],
        )
        db.add(candidate)
        candidates.append(candidate)
    db.flush()
    logger.info("Event %s -> %s candidates", event.id, len(candidates))
    return candidates
