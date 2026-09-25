"""Phase 1 importer tests.

Proves the critical requirement: level count and level names are read
from the imported data — a 4-level project stays 4 levels (no invented
L5/L7), and the 6-level sample imports all its depths.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import Project, WbsNode
from app.services.importer import ImportValidationError, import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent.parent / "demo" / "schedule_sample.csv"

MINI_CSV = b"""activity_id,activity_name,wbs_path,level,level_name,ancestor_level_names,planned_start,planned_finish,discipline,area,predecessors,weight
A1,Pour slab phase one,Phase One>Area 1>Slab Works,4,Activity,Project>Phase>Area,2026-01-05,2026-01-10,Civil,Area 1,,4
A2,Strip slab forms,Phase One>Area 1>Slab Works,4,Activity,Project>Phase>Area,2026-01-12,2026-01-16,Civil,Area 1,A1,2
"""

MISMATCH_CSV = b"""activity_id,activity_name,wbs_path,level,level_name
X1,Some task,Phase One>Area 1,9,Activity
"""

MISSING_COL_CSV = b"""task_id,some_name
1,hello
"""


@pytest.fixture(scope="session")
def db():
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _clean_test_projects(db):
    yield
    db.rollback()
    for project in db.scalars(select(Project).where(Project.code.like("TEST%"))).all():
        db.delete(project)
    db.commit()


def test_four_level_project_stays_four_levels(db):
    """A file with 4 depths must produce exactly 4 levels — nothing invented."""
    project = import_schedule(db, MINI_CSV, "mini.csv", "TESTMINI", "Mini Project")

    assert project.level_count == 4
    assert project.level_names == ["Project", "Phase", "Area", "Activity"]
    assert project.weighting_field == "weight"

    nodes = db.scalars(select(WbsNode).where(WbsNode.project_id == project.id)).all()
    assert max(n.level for n in nodes) == 4, "an L5 was invented for a 4-level file"
    leaves = [n for n in nodes if n.is_leaf]
    assert len(leaves) == 2
    # Top-down structure: root first, activities hang off depth-3 containers
    roots = [n for n in nodes if n.parent_id is None]
    assert len(roots) == 1 and roots[0].name == "Phase One" and roots[0].level == 1


def test_predecessor_backfill_creates_inverse_links(db):
    project = import_schedule(db, MINI_CSV, "mini.csv", "TESTMINI", "Mini Project")
    nodes = {n.code: n for n in db.scalars(select(WbsNode).where(WbsNode.project_id == project.id)).all()}
    assert nodes["A2"].predecessor_ids == ["A1"]
    assert nodes["A1"].successor_ids == ["A2"]  # backfilled from A2's predecessor list


def test_level_column_must_agree_with_path_depth(db):
    with pytest.raises(ImportValidationError, match="must agree"):
        import_schedule(db, MISMATCH_CSV, "bad.csv", "TESTBAD", "Bad Project")


def test_missing_required_column_rejected(db):
    with pytest.raises(ImportValidationError, match="Missing required column"):
        import_schedule(db, MISSING_COL_CSV, "bad2.csv", "TESTBAD2", "Bad Project 2")


def test_duplicate_project_code_blocked(db):
    import_schedule(db, MINI_CSV, "mini.csv", "TESTMINI", "Mini Project")
    with pytest.raises(ImportValidationError, match="already exists"):
        import_schedule(db, MINI_CSV, "mini.csv", "TESTMINI", "Mini Project Again")


def test_sample_schedule_imports_six_levels(db):
    project = import_schedule(
        db, SAMPLE_CSV.read_bytes(), SAMPLE_CSV.name, "TESTSAMPLE", "Sample"
    )
    assert project.level_count == 6
    assert project.level_names == [
        "Project", "Phase", "Area", "System", "Work", "Activity",
    ]
    leaves = db.scalar(
        select(func.count(WbsNode.id)).where(
            WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True)
        )
    )
    assert 30 <= leaves <= 50, f"expected 30-50 leaf activities, got {leaves}"
    assert project.meta["dangling_link_refs"] == 0

    disciplines = {
        row for row in db.scalars(
            select(WbsNode.discipline).where(
                WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True)
            )
        )
    }
    assert disciplines == {"Civil", "Piping", "Electrical"}
