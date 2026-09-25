"""Project endpoints: list imported schedules, import a new one (Phase 1)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, WbsNode
from ..schemas import ImportResponse, ProjectOut
from ..services.importer import ImportValidationError, import_schedule

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["projects"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _project_out(project: Project, db: Session) -> ProjectOut:
    node_count = db.scalar(
        select(func.count(WbsNode.id)).where(WbsNode.project_id == project.id)
    ) or 0
    leaf_count = db.scalar(
        select(func.count(WbsNode.id)).where(
            WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True)
        )
    ) or 0
    out = ProjectOut.model_validate(project)
    out.node_count = node_count
    out.leaf_count = leaf_count
    return out


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectOut]:
    projects = db.scalars(select(Project).order_by(Project.imported_at.desc())).all()
    return [_project_out(p, db) for p in projects]


@router.post("/import", response_model=ImportResponse)
async def import_project(
    file: UploadFile = File(...),
    project_code: str = Form(...),
    project_name: str = Form(...),
    db: Session = Depends(get_db),
) -> ImportResponse:
    """Import a P6/MS Project-style CSV or Excel schedule export."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (10 MB max).")
    code = project_code.strip().upper()
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "project_code is required.")
    try:
        project = import_schedule(
            db=db,
            content=content,
            filename=file.filename or "schedule.csv",
            project_code=code,
            project_name=project_name.strip() or code,
        )
    except ImportValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface parse problems as a client error
        logger.exception("Import failed")
        db.rollback()
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not parse schedule file: {exc}"
        ) from exc
    return ImportResponse(
        project=_project_out(project, db),
        message=(
            f"Imported {project.meta.get('imported_rows', 0)} activities across "
            f"{project.level_count} levels."
        ),
    )
