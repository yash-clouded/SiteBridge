"""Phase 10 tests: GET /api/reports closes the loop for whoever submitted it.

The list is the field user's own dashboard: every row says where the report
ended up — which rung extracted it, whether anyone reviewed it, and which
activity an approval mapped it to. Planners and PMs see everything.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import auth, login

from app.db import SessionLocal
from app.services.importer import import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent.parent / "demo" / "schedule_sample.csv"


@pytest.fixture
def project_id(client):
    db = SessionLocal()
    try:
        project = import_schedule(
            db, SAMPLE_CSV.read_bytes(), "schedule_sample.csv", "TESTOUT", "Test Outcome Project"
        )
        db.commit()
        return project.id
    finally:
        db.close()


def submit(client, token, project_id, text):
    resp = client.post(
        "/api/reports/text",
        headers=auth(token),
        json={"project_id": project_id, "raw_text": text, "source_type": "text"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_field_user_sees_the_outcome_of_their_own_reports(client, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report = submit(
        client, field, project_id, "Area A excavation for pump P-101 completed 2026-03-04"
    )

    processed = client.post(f"/api/reports/{report['id']}/process", headers=auth(planner))
    assert processed.status_code == 200, processed.text
    approved = client.post(
        f"/api/reports/{report['id']}/approve",
        headers=auth(planner),
        json={"note": "checked"},
    )
    assert approved.status_code == 200, approved.text

    rows = client.get("/api/reports", headers=auth(field)).json()
    mine = next(r for r in rows if r["id"] == report["id"])
    assert mine["review_status"] == "APPROVED"
    assert mine["extracted_by"] is not None, "say WHICH rung extracted it"
    assert "—" in mine["mapped_activity"], "name the activity the approval chose"

    # the raw evidence is still the submission itself
    assert mine["raw_text"].startswith("Area A excavation")


def test_a_report_without_an_event_has_no_outcome_yet(client, project_id, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auto_extract_on_intake", False)
    field = login(client, "field")["access_token"]
    report = submit(client, field, project_id, "waiting for extraction")

    rows = client.get("/api/reports", headers=auth(field)).json()
    mine = next(r for r in rows if r["id"] == report["id"])
    assert mine["review_status"] is None
    assert mine["extracted_by"] is None
    assert mine["mapped_activity"] is None


def test_field_users_only_see_their_own_reports(client, project_id):
    field = login(client, "field")["access_token"]
    other = login(client, "field2")["access_token"]
    planner = login(client, "planner")["access_token"]
    mine = submit(client, field, project_id, "my report")
    submit(client, other, project_id, "someone else's report")

    field_rows = {r["id"] for r in client.get("/api/reports", headers=auth(field)).json()}
    other_rows = {r["id"] for r in client.get("/api/reports", headers=auth(other)).json()}
    planner_rows = {r["id"] for r in client.get("/api/reports", headers=auth(planner)).json()}

    assert mine["id"] in field_rows
    assert mine["id"] not in other_rows, "another field user must not see it"
    assert mine["id"] in planner_rows, "planners need the whole picture"


def test_planner_can_scope_the_list_to_one_project(client, project_id):
    planner = login(client, "planner")["access_token"]
    field = login(client, "field")["access_token"]
    report = submit(client, field, project_id, "scoped report")

    rows = client.get(f"/api/reports?project_id={project_id}", headers=auth(planner)).json()
    assert all(r["project_id"] == project_id for r in rows)
    assert any(r["id"] == report["id"] for r in rows)
