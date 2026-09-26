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
    ("client@sitebridge.dev", "Maya Sen", "CLIENT"),
    ("pm@sitebridge.dev", "Raj Mehta", "PROJECT_MANAGER"),
    ("contractor@sitebridge.dev", "Arjun Rao", "CONTRACTOR"),
    ("site.engineer@sitebridge.dev", "Ramesh Sharma", "SITE_ENGINEER"),
    ("operative@sitebridge.dev", "M. Hazarika", "SITE_OPERATIVES"),
    ("planner@sitebridge.dev", "Elena Voss", "PLANNER"),
    ("discipline@sitebridge.dev", "Kamal Gogoi", "DISCIPLINE_ENGINEER"),
    ("field@sitebridge.dev", "Dana Fielder", "FIELD")
]


def ensure_users(db: Session) -> None:
    for email, name, role in SEED_USERS:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            db.add(
                User(
                    email=email,
                    full_name=name,
                    password_hash=hash_password(SEED_PASSWORD),
                    role=role,
                )
            )
        else:
            # Keep the checked-in demo accounts aligned with the seven-role model
            # when running seed.py against an older local database.
            user.full_name = name
            user.role = role
            user.is_active = True
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
            _backfill_embeddings(db, PROJECT_CODE)
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
        _backfill_embeddings(db, PROJECT_CODE)
    finally:
        db.close()


def _backfill_embeddings(db: Session, project_code: str) -> None:
    """Phase 5: make sure the imported leaves have vectors (idempotent)."""
    from app.services.retrieval import embed_activities

    project = db.scalar(select(Project).where(Project.code == project_code))
    if project is None:
        return
    try:
        embedded = embed_activities(db, project.id)
        db.commit()
        print(f"  embedded activities: {embedded} new vector(s)")
    except Exception as exc:  # noqa: BLE001 — embeddings must not block the demo
        db.rollback()
        print(f"  embedding skipped: {exc}")


if __name__ == "__main__":
    main()
