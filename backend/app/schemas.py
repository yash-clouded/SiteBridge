"""Phase 1 request/response schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    source_filename: Optional[str]
    imported_at: datetime
    level_count: int
    level_names: list[str]
    weighting_field: Optional[str]
    node_count: int = 0
    leaf_count: int = 0


class WbsNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: Optional[int]
    code: str
    name: str
    level: int
    level_name: str
    is_leaf: bool
    planned_start: Optional[date]
    planned_finish: Optional[date]
    weight: Optional[float]
    discipline: Optional[str]
    area: Optional[str]
    equipment_tag: Optional[str]
    predecessor_ids: list[str] = []
    successor_ids: list[str] = []


class ImportResponse(BaseModel):
    project: ProjectOut
    message: str
