"""Phase 1: schedule import (CSV / Excel, P6 / MS Project export shape).

Reads the ACTUAL level count and level names out of the imported data —
never assumes a fixed depth, never invents a level the file doesn't
contain, never hardcodes what a level means.

Expected columns (aliases accepted; headers are case/spacing-insensitive):
  activity_id*, activity_name*, wbs_path*, [level], [level_name],
  [ancestor_level_names], [planned_start], [planned_finish],
  [discipline], [area], [equipment_tag], [predecessors], [successors],
  [weight]
Required columns are marked with *. `wbs_path` is the ancestor path from
the project root down to the activity's parent, delimited by ">" (the
importer also understands "|", "/" and "."-style paths). If the file
carries a `level` column it wins; otherwise the depth is derived from
the actual path. `ancestor_level_names` optionally names each ancestor
depth, e.g. "Project>Phase>Area>System>Work".
"""
from __future__ import annotations

import io
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Project, WbsNode

logger = logging.getLogger(__name__)


class ImportValidationError(Exception):
    """Raised for user-facing problems with an uploaded schedule file."""


COLUMN_ALIASES: dict[str, list[str]] = {
    "activity_id": ["activity_id", "activity id", "id", "activity_code", "activity code", "task_id"],
    "activity_name": ["activity_name", "activity name", "name", "task_name", "task name", "activity"],
    "wbs_path": ["wbs_path", "wbs path", "wbs", "wbs_code", "wbs code", "path"],
    "level": ["level", "activity_level", "wbs_level", "depth"],
    "level_name": ["level_name", "level name", "wbs_level_name", "node_type"],
    "ancestor_level_names": ["ancestor_level_names", "ancestor level names", "level_names", "level names"],
    "planned_start": ["planned_start", "planned start", "start", "start_date", "early_start"],
    "planned_finish": ["planned_finish", "planned finish", "finish", "finish_date", "early_finish"],
    "discipline": ["discipline"],
    "area": ["area", "location", "location_area", "area_location", "zone", "region"],
    "equipment_tag": ["equipment_tag", "equipment tag", "tag", "equipment"],
    "predecessors": ["predecessors", "predecessor", "preds", "pred", "predecessor_ids"],
    "successors": ["successors", "successor", "succs", "succ", "successor_ids"],
    "weight": ["weight", "weighted_activities", "budget_weight", "weight_pct", "activity_weight"],
}

REQUIRED = ["activity_id", "activity_name", "wbs_path"]


def _norm_header(h: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(h).strip().lower())


def map_columns(df: pd.DataFrame) -> dict[str, str]:
    """Return {canonical_name: actual_column_name} for recognized columns."""
    normed = {_norm_header(c): c for c in df.columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normed:
                mapping[canonical] = normed[alias]
                break
    missing = [c for c in REQUIRED if c not in mapping]
    if missing:
        raise ImportValidationError(
            f"Missing required column(s): {missing}. Found columns: {list(df.columns)}"
        )
    return mapping


def _detect_delimiter(values: list[str]) -> str:
    for delim in (">", "|", "/"):
        if any(delim in v for v in values):
            return delim
    if any("." in v for v in values):
        return "."
    return ">"


def _split_path(value: Any, delim: str) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return []
    parts = [p.strip() for p in str(value).split(delim)]
    return [p for p in parts if p]


def _parse_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _split_ids(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)) or pd.isna(value):
        return []
    return [p.strip() for p in re.split(r"[,;|]", str(value)) if p.strip()]


def _read_table(content: bytes, filename: str) -> pd.DataFrame:
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), sheet_name=0, dtype=str)
    return pd.read_csv(io.BytesIO(content), dtype=str)


def import_schedule(
    db: Session,
    content: bytes,
    filename: str,
    project_code: str,
    project_name: str,
) -> Project:
    """Import a schedule file into the WBS tree. Commits on success."""
    df = _read_table(content, filename)
    if df.empty:
        raise ImportValidationError("The uploaded file contains no rows.")
    cols = map_columns(df)

    delim = _detect_delimiter([str(r[cols["wbs_path"]]) for r in df.to_dict("records")])

    if db.scalar(select(Project).where(Project.code == project_code)) is not None:
        raise ImportValidationError(
            f"Project '{project_code}' already exists — import blocked to protect existing data."
        )

    project = Project(
        code=project_code,
        name=project_name,
        source_filename=filename,
        level_count=0,
        level_names=[],
        weighting_field=None,
        meta={"delimiter": delim, "imported_rows": int(len(df))},
    )
    db.add(project)
    db.flush()

    # (parent_id, segment) -> container node, so shared prefixes are created once
    containers: dict[tuple[int | None, str], WbsNode] = {}
    activities: dict[str, WbsNode] = {}
    # depth -> list of level names observed at that depth (for data-driven metadata)
    depth_names: dict[int, list[str]] = defaultdict(list)
    has_weights = False

    def get_container(parent: WbsNode | None, segment: str, level: int, level_name: str) -> WbsNode:
        key = (parent.id if parent else None, segment)
        node = containers.get(key)
        if node is not None:
            return node
        node = WbsNode(
            project_id=project.id,
            parent_id=parent.id if parent else None,
            code=segment,
            name=segment,
            level=level,
            level_name=level_name,
            is_leaf=False,
            path="/",
        )
        db.add(node)
        db.flush()
        node.path = (parent.path + f"{node.id}/") if parent else f"/{node.id}/"
        containers[key] = node
        depth_names[level].append(level_name)
        return node

    for rec in df.to_dict("records"):
        activity_id = str(rec[cols["activity_id"]]).strip()
        activity_name = str(rec[cols["activity_name"]]).strip()
        if not activity_id or activity_id.lower() == "nan" or not activity_name:
            raise ImportValidationError("A row has an empty activity_id or activity_name.")
        if activity_id in activities:
            raise ImportValidationError(f"Duplicate activity_id '{activity_id}' in the file.")

        segments = _split_path(rec[cols["wbs_path"]], delim)

        if "ancestor_level_names" in cols:
            ancestor_names = _split_path(rec[cols["ancestor_level_names"]], delim)
        else:
            ancestor_names = []
        while len(ancestor_names) < len(segments):
            ancestor_names.append(f"Level {len(ancestor_names) + 1}")

        parent: WbsNode | None = None
        for i, segment in enumerate(segments, start=1):
            parent = get_container(parent, segment, i, ancestor_names[i - 1])

        # The activity's own level: from the file's `level` column when present,
        # otherwise the actual path depth. Whatever the file says the deepest
        # depth IS, that is the project's level count — nothing is added.
        if "level" in cols and not pd.isna(rec[cols["level"]]):
            own_level = int(float(rec[cols["level"]]))
            if own_level != len(segments) + 1:
                raise ImportValidationError(
                    f"Row {activity_id}: level column says {own_level} but wbs_path depth "
                    f"implies {len(segments) + 1} — these must agree."
                )
        else:
            own_level = len(segments) + 1

        if "level_name" in cols and not pd.isna(rec[cols["level_name"]]):
            own_level_name = str(rec[cols["level_name"]]).strip()
        else:
            own_level_name = f"Level {own_level}"

        weight = None
        if "weight" in cols and not pd.isna(rec[cols["weight"]]):
            try:
                weight = float(str(rec[cols["weight"]]).replace("%", "").strip())
                has_weights = True
            except ValueError:
                weight = None

        def opt(col: str) -> str | None:
            if col not in cols or pd.isna(rec[cols[col]]):
                return None
            value = str(rec[cols[col]]).strip()
            return value or None

        node = WbsNode(
            project_id=project.id,
            parent_id=parent.id if parent else None,
            code=activity_id,
            name=activity_name,
            level=own_level,
            level_name=own_level_name,
            is_leaf=True,
            path="/",
            planned_start=_parse_date(rec[cols["planned_start"]]) if "planned_start" in cols else None,
            planned_finish=_parse_date(rec[cols["planned_finish"]]) if "planned_finish" in cols else None,
            weight=weight,
            discipline=opt("discipline"),
            area=opt("area"),
            equipment_tag=opt("equipment_tag"),
            predecessor_ids=_split_ids(rec[cols["predecessors"]]) if "predecessors" in cols else [],
            successor_ids=_split_ids(rec[cols["successors"]]) if "successors" in cols else [],
        )
        db.add(node)
        db.flush()
        node.path = (parent.path + f"{node.id}/") if parent else f"/{node.id}/"
        activities[activity_id] = node
        depth_names[own_level].append(own_level_name)

    # --- level metadata READ FROM THE DATA ---
    max_depth = max(depth_names.keys())
    level_names = [
        Counter(depth_names[lvl]).most_common(1)[0][0] if depth_names.get(lvl) else f"Level {lvl}"
        for lvl in range(1, max_depth + 1)
    ]
    project.level_count = max_depth
    project.level_names = level_names
    project.weighting_field = "weight" if has_weights else None

    # Backfill the inverse side so predecessor/successor data is consistent
    # regardless of which direction(s) the file happens to provide.
    for node in activities.values():
        for pred_id in node.predecessor_ids:
            pred = activities.get(pred_id)
            if pred is not None and node.code not in pred.successor_ids:
                pred.successor_ids = [*pred.successor_ids, node.code]
        for succ_id in node.successor_ids:
            succ = activities.get(succ_id)
            if succ is not None and node.code not in succ.predecessor_ids:
                succ.predecessor_ids = [*succ.predecessor_ids, node.code]

    # Validate that referenced predecessor/successor IDs exist (warn, don't fail —
    # exports often reference codes outside this activity list).
    dangling = 0
    for node in activities.values():
        for ref in (*node.predecessor_ids, *node.successor_ids):
            if ref not in activities:
                dangling += 1
    if dangling:
        logger.warning("%s predecessor/successor references not found in the file.", dangling)
    project.meta["dangling_link_refs"] = dangling

    # Phase 5: embed leaf activity descriptions ONCE, at import.
    # A provider outage must not lose an import — the vectors can be
    # rebuilt later with POST /api/projects/{id}/embed.
    try:
        from .retrieval import embed_activities

        embedded = embed_activities(db, project.id)
        project.meta["embedded_activities"] = embedded
    except Exception:  # noqa: BLE001 — never fail an import over embeddings
        logger.exception(
            "Activity embedding failed for project %s — rerun "
            "POST /api/projects/%s/embed after fixing the provider.",
            project_code,
            project_code,
        )
        project.meta["embedded_activities"] = 0

    db.commit()
    return project
