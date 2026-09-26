"""Phase 9 HTTP surface: the project roll-up.

  GET /api/projects/{id}/rollup   Planner / PM — read-only aggregation of
                                  approved field evidence over the schedule.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, Role
from ..schemas import RollupOut
from ..security import roles_for
from ..services.rollup import project_rollup

router = APIRouter(prefix="/api", tags=["rollup"])


@router.get("/projects/{project_id}/rollup", response_model=RollupOut)
def get_rollup(
    project_id: int,
    db: Session = Depends(get_db),
    user=Depends(roles_for("management")),
) -> RollupOut:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project_rollup(db, project)
