"""Seed the dev database: create tables, import the sample schedule.

Usage: uv run python seed.py
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.models import Project, User, WbsNode
from app.security import hash_password
from app.services.importer import import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent / "demo" / "schedule_sample.csv"
PROJECT_CODE = "NPU"

# Phase 2 demo users — one per role (roles grant functions, never WBS levels)
SEED_PASSWORD = "demo1234"
SEED_USERS = [
    ("field@sitebridge.dev", "Dana Fielder", "FIELD"),      # Field User (Supervisor/Contractor)
    ("planner@sitebridge.dev", "Elena Voss", "PLANNER"),    # Planner / Project Controls
    ("pm@sitebridge.dev", "Raj Mehta", "PM"),               # Project Manager / Management
]


def ensure_users(db: Session) -> None:
    for email, name, role in SEED_USERS:
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(
                User(
                    email=email,
                    full_name=name,
                    password_hash=hash_password(SEED_PASSWORD),
                    role=role,
                )
            )
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        ensure_users(db)
        print("Users (password: %s):" % SEED_PASSWORD)
        for email, name, role in SEED_USERS:
            print(f"  {email:28s} {name:16s} {role}")

        if db.scalar(select(Project).where(Project.code == PROJECT_CODE)) is not None:
            print(f"Project {PROJECT_CODE} already imported — skipping.")
            return

        project = import_schedule(
            db=db,
            content=SAMPLE_CSV.read_bytes(),
            filename=SAMPLE_CSV.name,
            project_code=PROJECT_CODE,
            project_name="North Plant Utilities Upgrade",
        )
        leaves = db.scalar(
            select(func.count(WbsNode.id)).where(
                WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True)
            )
        )
        total = db.scalar(select(func.count(WbsNode.id)).where(WbsNode.project_id == project.id))
        by_discipline = db.execute(
            select(WbsNode.discipline, func.count(WbsNode.id))
            .where(WbsNode.project_id == project.id, WbsNode.is_leaf.is_(True))
            .group_by(WbsNode.discipline)
        ).all()
        print(f"Imported '{project.name}' ({project.code})")
        print(f"  levels: {project.level_count} -> {project.level_names}")
        print(f"  nodes:  {total} ({leaves} leaf activities)")
        print(f"  weighting field: {project.weighting_field}")
        print(f"  leaves by discipline: {dict(by_discipline)}")
        print(f"  dangling link refs:   {project.meta.get('dangling_link_refs')}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
