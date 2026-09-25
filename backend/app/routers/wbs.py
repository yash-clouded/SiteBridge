"""WBS browse endpoints (Phase 1): flat tree-ordered node list for any role."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Project, WbsNode
from ..schemas import WbsNodeOut
from ..security import get_current_user

router = APIRouter(prefix="/api", tags=["wbs"])


def _tree_ordered(nodes: list[WbsNode]) -> list[WbsNode]:
    """Depth-first order (creation order within each parent) for display."""
    children: dict[int | None, list[WbsNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    for siblings in children.values():
        siblings.sort(key=lambda n: n.id)

    ordered: list[WbsNode] = []

    def walk(parent_id: int | None) -> None:
        for node in children.get(parent_id, []):
            ordered.append(node)
            walk(node.id)

    walk(None)
    return ordered


@router.get("/projects/{project_id}/wbs", response_model=list[WbsNodeOut])
def get_wbs(
    project_id: int,
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),  # any authenticated role may browse
) -> list[WbsNodeOut]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    nodes = db.scalars(
        select(WbsNode).where(WbsNode.project_id == project_id)
    ).all()
    return [WbsNodeOut.model_validate(n) for n in _tree_ordered(nodes)]
