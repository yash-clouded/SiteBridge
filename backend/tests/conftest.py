"""Shared test fixtures: FastAPI client, per-role test users, cleanup.

Test users live at *@test.local and are removed after every test;
projects/reports created by tests use the TEST* code prefix so cleanup
never touches demo data (NPU, seed users).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import settings
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


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """The suite must never reach a real endpoint, whatever `.env` contains.

    Clearing the key makes `llm.configured()` false, so an unstubbed
    extraction falls back to Phase 11's heuristic rung (or reports
    `disabled` when EXTRACTION_FALLBACK=off) instead of paying for — or
    hanging on — a live call, and embeddings resolve to the local hash
    provider. Tests that exercise the transport stub `extraction.chat_json`
    itself; tests about the ladder stub `llm._call`; translation tests set a
    key and stub `translate._post` (the single HTTP seam).
    """
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "embedding_provider", "local")
    # Translation: no key in tests, so intake records `disabled` instead of
    # calling Sarvam. Tests about translation set a key AND stub `_post`.
    monkeypatch.setattr(settings, "sarvam_api_key", "")


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
