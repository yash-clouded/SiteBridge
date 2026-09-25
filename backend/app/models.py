"""SiteBridge data model — Phase 1: WBS / project structure.

The WBS/Project hierarchy answers "where does this work belong?". It is
imported top-down from the schedule file: the root project node exists
first, then phases, and so on down to executable activities.

The number of levels and their names are READ FROM THE IMPORTED DATA
(`projects.level_count`, `projects.level_names`) — nothing in this code
assumes a fixed number of levels or hardcodes what any level means.

(Role/permission model arrives in Phase 2 and is deliberately a separate
hierarchy that never references WBS levels.)
"""
from __future__ import annotations

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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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

    project: Mapped[Project] = relationship(back_populates="nodes")
    parent: Mapped[Optional["WbsNode"]] = relationship(
        remote_side=[id], back_populates="children"
    )
    children: Mapped[list["WbsNode"]] = relationship(back_populates="parent")

    __table_args__ = (
        UniqueConstraint("project_id", "parent_id", "code", name="uq_wbs_project_parent_code"),
        Index("ix_wbs_nodes_project_level", "project_id", "level"),
    )
