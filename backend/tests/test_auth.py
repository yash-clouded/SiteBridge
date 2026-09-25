"""Phase 2 tests: JWT login + role guards.

Covers the separation of concerns: any role may browse the WBS, but
functions like schedule import are gated by role — never by WBS level.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal, init_db
from app.main import app
from app.models import Project, Role, User
from app.security import hash_password

PASSWORD = "test-pass-123"
USERS = {
    "field": ("field@test.local", Role.FIELD),
    "planner": ("planner@test.local", Role.PLANNER),
    "pm": ("pm@test.local", Role.PM),
}

MINI_CSV = b"""activity_id,activity_name,wbs_path,level,level_name,ancestor_level_names,planned_start,planned_finish,discipline,area,predecessors,weight
T1,Pour slab,Phase One>Area 1>Slab Works,4,Activity,Project>Phase>Area,2026-03-02,2026-03-06,Civil,Area 1,,4
T2,Strip forms,Phase One>Area 1>Slab Works,4,Activity,Project>Phase>Area,2026-03-09,2026-03-13,Civil,Area 1,T1,2
"""


@pytest.fixture(scope="session")
def client():
    init_db()
    with TestClient(app) as c:  # runs lifespan (idempotent schema create)
        yield c


@pytest.fixture(autouse=True)
def _test_users(client):
    db = SessionLocal()
    for email, role in USERS.values():
        if db.scalar(select(User).where(User.email == email)) is None:
            db.add(
                User(
                    email=email,
                    full_name=email.split("@")[0],
                    password_hash=hash_password(PASSWORD),
                    role=role.value,
                )
            )
    db.commit()
    db.close()
    yield
    db = SessionLocal()
    for email, _ in USERS.values():
        user = db.scalar(select(User).where(User.email == email))
        if user is not None:
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


def test_login_returns_token_and_role(client):
    body = login(client, "planner")
    assert body["access_token"]
    assert body["user"]["role"] == "PLANNER"


def test_login_wrong_password_rejected(client):
    email, _ = USERS["field"]
    resp = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert resp.status_code == 401


def test_me_returns_current_user(client):
    body = login(client, "pm")
    resp = client.get("/api/auth/me", headers=auth(body["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["role"] == "PM"


def test_browse_requires_authentication(client):
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/projects/1/wbs").status_code == 401


def test_any_role_can_browse_the_hierarchy(client):
    """Field/PM/Planner all see the same WBS — access is not level-based."""
    for key in USERS:
        token = login(client, key)["access_token"]
        assert client.get("/api/projects", headers=auth(token)).status_code == 200
        # note: project id 1 may not exist in a fresh DB; use whatever exists
        projects = client.get("/api/projects", headers=auth(token)).json()
        if projects:
            pid = projects[0]["id"]
            assert client.get(f"/api/projects/{pid}/wbs", headers=auth(token)).status_code == 200


def test_schedule_import_is_planner_only(client):
    field_token = login(client, "field")["access_token"]
    pm_token = login(client, "pm")["access_token"]
    files = {"file": ("mini.csv", MINI_CSV, "text/csv")}
    data = {"project_code": "TESTIMPORT", "project_name": "Import Guard Test"}
    assert (
        client.post("/api/projects/import", headers=auth(field_token), files=files, data=data).status_code
        == 403
    )
    assert (
        client.post("/api/projects/import", headers=auth(pm_token), files=files, data=data).status_code
        == 403
    )
    assert client.post("/api/projects/import").status_code == 401

    planner_token = login(client, "planner")["access_token"]
    resp = client.post("/api/projects/import", headers=auth(planner_token), files=files, data=data)
    assert resp.status_code == 200, resp.text
    assert resp.json()["project"]["level_count"] == 4
