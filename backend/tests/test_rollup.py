"""Phase 9 tests: the roll-up — approved evidence aggregated over the schedule.

Two invariants drive every assertion here:
  * an activity is "reported" only when Phase 8 approved evidence for it
    (an untouched activity is unreported, never 0% complete);
  * progress is averaged over reported activities that STATE a value, and
    stays ``null`` when none does.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import app.services.extraction as extraction
from conftest import auth, login
from sqlalchemy import select

from app.db import SessionLocal
from app.models import ExecutionEvent, WbsNode
from app.services.importer import import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent.parent / "demo" / "schedule_sample.csv"


@pytest.fixture
def project_id(client):
    db = SessionLocal()
    try:
        project = import_schedule(
            db,
            SAMPLE_CSV.read_bytes(),
            "schedule_sample.csv",
            "TESTROLL",
            "Test Rollup Project",
        )
        db.commit()
        return project.id
    finally:
        db.close()


@pytest.fixture
def stub_llm(monkeypatch):
    def install(reply) -> None:
        text = reply if isinstance(reply, str) else json.dumps(reply)
        monkeypatch.setattr(extraction, "chat_json", lambda system, user: text)

    return install


def submit(client, token, project_id, text):
    resp = client.post(
        "/api/reports/text",
        headers=auth(token),
        json={"project_id": project_id, "raw_text": text, "source_type": "text"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def process(client, token, report_id):
    resp = client.post(f"/api/reports/{report_id}/process", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def approve(client, token, report_id, payload=None):
    resp = client.post(
        f"/api/reports/{report_id}/approve",
        headers=auth(token),
        json=payload or {},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def rollup(client, token, project_id):
    resp = client.get(f"/api/projects/{project_id}/rollup", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def report_and_approve(client, field, planner, project_id, install, reply) -> dict:
    install(reply)
    report = submit(client, field, project_id, reply.get("description", "some work"))
    process(client, planner, report["id"])
    approve(client, planner, report["id"])
    return report


def approved_nodes(report_id: int) -> list[WbsNode]:
    db = SessionLocal()
    try:
        return list(
            db.scalars(select(WbsNode).where(WbsNode.actual_report_id == report_id)).all()
        )
    finally:
        db.close()


def leaf_count(project_id: int) -> int:
    db = SessionLocal()
    try:
        return len(
            db.scalars(
                select(WbsNode).where(
                    WbsNode.project_id == project_id, WbsNode.is_leaf.is_(True)
                )
            ).all()
        )
    finally:
        db.close()


FULL_PROGRESS = {
    "description": "Excavate foundation for pump P-101",
    "discipline": "Civil",
    "location": "Area A",
    "tag": "P-101",
    "status": "complete",
    "progress": 100,
}


def test_only_approved_evidence_counts_as_reported(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    total = leaf_count(project_id)
    assert total > 1

    report_and_approve(client, field, planner, project_id, stub_llm, FULL_PROGRESS)

    body = rollup(client, planner, project_id)
    assert body["activities"] == total
    assert body["reported"] == 1, "only the approved activity counts"
    assert body["coverage"] == round(1 / total, 4)
    assert body["avg_progress"] == pytest.approx(100.0)
    assert body["approved"] == 1
    assert body["pending_review"] == 0


def test_unreported_activities_are_never_treated_as_zero_percent(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    total = leaf_count(project_id)

    # One approval, one report still waiting — nothing else exists.
    report_and_approve(client, field, planner, project_id, stub_llm, FULL_PROGRESS)
    pending = submit(client, field, project_id, "Poured pipe rack footings RA-1")
    process(client, planner, pending["id"])

    body = rollup(client, planner, project_id)
    assert body["reported"] == 1
    assert body["reported"] < body["activities"] == total
    assert body["pending_review"] == 1
    assert body["avg_progress"] == pytest.approx(100.0), "the unreported 35 stay out of the mean"


def test_null_progress_stays_null_instead_of_becoming_zero(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]

    report = report_and_approve(
        client,
        field,
        planner,
        project_id,
        stub_llm,
        {"description": "Graded subgrade Area B", "location": "Area B", "status": "in progress"},
    )

    body = rollup(client, planner, project_id)
    assert body["reported"] == 1
    assert body["avg_progress"] is None, "nobody stated progress — do not invent 0"

    written = approved_nodes(report["id"])
    assert len(written) == 1
    bucket = next(b for b in body["by_area"] if b["key"] == (written[0].area or ""))
    assert bucket["reported"] == 1
    assert bucket["avg_progress"] is None
    assert bucket["by_status"].get("in progress") == 1


def test_buckets_partition_the_whole_schedule(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report = report_and_approve(
        client, field, planner, project_id, stub_llm, FULL_PROGRESS
    )
    body = rollup(client, planner, project_id)

    assert len(body["by_wbs"]) > 1, "segments must split below the project root"
    for buckets in (body["by_area"], body["by_discipline"], body["by_wbs"]):
        assert buckets, "the sample schedule has areas, disciplines and segments"
        assert sum(b["activities"] for b in buckets) == body["activities"]
        assert sum(b["reported"] for b in buckets) == body["reported"]
        assert all(b["reported"] <= b["activities"] for b in buckets)
        assert all(b["last_update"] is None or b["reported"] for b in buckets)

    written = approved_nodes(report["id"])
    assert len(written) == 1
    bucket = next(b for b in body["by_area"] if b["key"] == (written[0].area or ""))
    assert bucket["reported"] == 1
    assert bucket["last_update"] is not None
    assert bucket["by_status"]


def test_series_records_approvals_by_day(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report_and_approve(client, field, planner, project_id, stub_llm, FULL_PROGRESS)

    body = rollup(client, planner, project_id)
    today = datetime.now(timezone.utc).date().isoformat()
    point = next((p for p in body["series"] if p["day"] == today), None)
    assert point is not None, "an approval must appear on the day it happened"
    assert point["approved"] == 1
    assert body["updated_at"] is not None


def test_rejected_and_reopened_evidence_leaves_the_rollup(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report = report_and_approve(
        client, field, planner, project_id, stub_llm, FULL_PROGRESS
    )
    assert rollup(client, planner, project_id)["reported"] == 1

    rejected = client.post(
        f"/api/reports/{report['id']}/reject",
        headers=auth(planner),
        json={"note": "wrong activity"},
    )
    assert rejected.status_code == 200, rejected.text
    body = rollup(client, planner, project_id)
    assert body["reported"] == 0, "an actual only counts while its approval stands"
    assert body["approved"] == 0
    assert body["rejected"] == 1
    assert body["coverage"] == 0.0
    assert body["avg_progress"] is None


def test_rollup_is_planner_and_pm_read_only(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]

    assert client.get(f"/api/projects/{project_id}/rollup", headers=auth(pm)).status_code == 200
    assert rollup(client, planner, project_id)["project_id"] == project_id
    assert client.get(f"/api/projects/{project_id}/rollup", headers=auth(field)).status_code == 403
    assert client.get(f"/api/projects/{project_id}/rollup").status_code == 401
    assert client.get("/api/projects/999999/rollup", headers=auth(planner)).status_code == 404
