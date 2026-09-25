"""Shared test fixtures: FastAPI client, per-role test users, cleanup.

Test users live at *@test.local and are removed after every test;
projects/reports created by tests use the TEST* code prefix so cleanup
never touches demo data (NPU, seed users).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import FieldReport, Project, User
from app.security import hash_password

PASSWORD = "test-pass-123"
USERS = {
    "field": ("field@test.local", "FIELD"),
    "field2": ("field2@test.local", "FIELD"),
    "planner": ("planner@test.local", "PLANNER"),
    "pm": ("pm@test.local", "PM"),
}


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(app) as c:  # runs lifespan (idempotent schema create)
        yield c


@pytest.fixture(autouse=True)
def _test_workspace(client):
    db = SessionLocal()
    for email, role in USERS.values():
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(
                User(
                    email=email,
                    full_name=email.split("@")[0],
                    password_hash=hash_password(PASSWORD),
                    role=role,
                )
            )
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    for email, _ in USERS.values():
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
            for report in db.scalars(select(FieldReport).where(FieldReport.user_id == user.id)):
                db.delete(report)
            db.delete(user)
    for project in db.scalars(select(Project).where(Project.code.like("TEST%"))).all():
        db.delete(project)
    db.commit()
    db.close()


def login(client: TestClient, key: str) -> dict:
    email, _ = USERS[key]
    resp = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def first_project_id(client: TestClient, token: str) -> int:
    projects = client.get("/api/projects", headers=auth(token)).json()
    assert projects, "seed the demo project before running tests"
    return projects[0]["id"]
