"""Phase 8 tests: the review queue and its approve / reject / reopen actions.

The invariant under test is the only place the schedule changes: approving
writes the approved report's facts onto the activity (and nothing else),
and undoing an approval removes exactly those facts. Roles are enforced
server-side — FIELD submits, PLANNER decides, PM only reads.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import app.services.extraction as extraction
from conftest import auth, login
from sqlalchemy import select

from app.db import SessionLocal
from app.models import WbsNode
from app.services.importer import import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent.parent / "demo" / "schedule_sample.csv"


@pytest.fixture
def project_id(client):
    """A schedule of its own, so approvals never touch the demo project."""
    db = SessionLocal()
    try:
        project = import_schedule(
            db,
            SAMPLE_CSV.read_bytes(),
            "schedule_sample.csv",
            "TESTREVIEW",
            "Test Review Project",
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


def review(client, token, report_id, action, payload=None):
    return client.post(
        f"/api/reports/{report_id}/{action}",
        headers=auth(token),
        json=payload or {},
    )


def approved_candidate(body) -> dict:
    flagged = [c for c in body["candidates"] if c["approved"]]
    assert len(flagged) == 1, "exactly one candidate may be approved"
    return flagged[0]


def node_for(wbs_node_id) -> WbsNode:
    db = SessionLocal()
    try:
        return db.get(WbsNode, wbs_node_id)
    finally:
        db.close()


def actuals_for(report_id: int) -> list[WbsNode]:
    """Every activity whose actuals came from this report's approval."""
    db = SessionLocal()
    try:
        return list(
            db.scalars(select(WbsNode).where(WbsNode.actual_report_id == report_id)).all()
        )
    finally:
        db.close()


def full_match(client, token, report_id) -> dict:
    resp = client.get(f"/api/reports/{report_id}/match", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


CIVIL_EXCAVATION = {
    "description": "Excavate foundation for pump P-101",
    "discipline": "Civil",
    "location": "Area A",
    "tag": "P-101",
    "date": "2026-01-15",
    "status": "complete",
    "progress": 100,
}


def ready_report(
    client, field, planner, project_id, install, reply=CIVIL_EXCAVATION
) -> tuple[dict, dict]:
    """Submit + process with a stubbed LLM, returning (report, match)."""
    install(reply)
    report = submit(client, field, project_id, "Excavated foundation for pump P-101 in Area A")
    return report, process(client, planner, report["id"])


def test_approve_publishes_the_activity_actuals(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, body = ready_report(client, field, planner, project_id, stub_llm)

    resp = review(client, planner, report["id"], "approve", {"note": "checked against DPR"})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["event"]["review_status"] == "APPROVED"
    assert body["event"]["review_note"] == "checked against DPR"
    assert body["event"]["reviewed_by"] is not None
    chosen = approved_candidate(body)
    assert chosen["rank"] == 1, "the default choice is the top-ranked candidate"

    node = node_for(chosen["wbs_node_id"])
    assert node.actual_status == "complete"
    assert node.actual_progress == 100
    assert node.actual_date == date(2026, 1, 15)
    assert node.actual_report_id == report["id"], "actuals must point at their evidence"
    assert node.actual_updated_at is not None
    # the planned baseline is untouched
    assert node.planned_start is not None

    # the same facts are visible through the read API
    top = next(c for c in full_match(client, planner, report["id"])["candidates"]
               if c["approved"])
    assert top["activity"]["actual_status"] == "complete"
    assert top["activity"]["actual_report_id"] == report["id"]


def test_actuals_describe_only_the_report_that_was_approved(client, stub_llm, project_id):
    """A terse second approval must not keep the first report's progress."""
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, body = ready_report(client, field, planner, project_id, stub_llm)
    node_id = body["candidates"][0]["wbs_node_id"]

    review(client, planner, report["id"], "approve", {})
    assert node_for(node_id).actual_progress == 100
    assert actuals_for(report["id"]), "the approval wrote actuals"

    # Reopen: this approval's actuals must disappear, not linger.
    assert review(client, planner, report["id"], "reopen", {}).status_code == 200
    assert node_for(node_id).actual_report_id is None

    # Now approve a report that states neither progress nor a date.
    stub_llm({"description": "Excavate foundation for pump P-101", "status": "in progress"})
    report2 = submit(client, field, project_id, "Excavated foundation for pump P-101")
    process(client, planner, report2["id"])
    assert review(client, planner, report2["id"], "approve", {}).status_code == 200

    written = actuals_for(report2["id"])
    assert len(written) == 1, "an approval writes actuals to exactly one activity"
    node = written[0]
    assert node.actual_status == "in progress"
    assert node.actual_progress is None, "an unstated value is null, never carried over"
    assert node.actual_date is None

    previous = node_for(node_id)
    if previous.id != node.id:
        assert previous.actual_report_id is None


def test_reject_then_reopen_clears_the_actuals(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, body = ready_report(client, field, planner, project_id, stub_llm)
    node_id = body["candidates"][0]["wbs_node_id"]

    review(client, planner, report["id"], "approve", {})
    assert node_for(node_id).actual_report_id == report["id"]

    rejected = review(client, planner, report["id"], "reject", {"note": "wrong activity"})
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["event"]["review_status"] == "REJECTED"
    node = node_for(node_id)
    assert node.actual_report_id is None
    assert node.actual_status is None and node.actual_progress is None
    assert not any(c["approved"] for c in rejected.json()["candidates"])

    reopened = review(client, planner, report["id"], "reopen", {})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["event"]["review_status"] == "PENDING"


def test_approving_a_different_candidate_requires_a_reopen(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, body = ready_report(client, field, planner, project_id, stub_llm)
    second = body["candidates"][1]

    assert review(client, planner, report["id"], "approve", {}).status_code == 200
    conflict = review(client, planner, report["id"], "approve", {"candidate_id": second["id"]})
    assert conflict.status_code == 409
    assert "reopen" in conflict.json()["detail"].lower()

    # the original approval is untouched by the failed attempt
    assert len([c for c in full_match(client, planner, report["id"])["candidates"]
                if c["approved"]]) == 1

    assert review(client, planner, report["id"], "reopen", {}).status_code == 200
    switched = review(client, planner, report["id"], "approve", {"candidate_id": second["id"]})
    assert switched.status_code == 200, switched.text
    chosen = approved_candidate(switched.json())
    assert chosen["id"] == second["id"]
    assert chosen["activity"]["code"] == second["activity"]["code"]


def test_reprocessing_is_blocked_once_evidence_is_approved(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, _ = ready_report(client, field, planner, project_id, stub_llm)

    review(client, planner, report["id"], "approve", {})
    blocked = client.post(f"/api/reports/{report['id']}/process", headers=auth(planner))
    assert blocked.status_code == 409
    assert "APPROVED" in blocked.json()["detail"]


def test_decisions_are_planner_only(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]
    report, _ = ready_report(client, field, planner, project_id, stub_llm)

    assert review(client, field, report["id"], "approve").status_code == 403
    assert review(client, pm, report["id"], "approve").status_code == 403
    assert client.post(f"/api/reports/{report['id']}/approve").status_code == 401
    assert review(client, field, report["id"], "reject").status_code == 403
    assert review(client, field, report["id"], "reopen").status_code == 403


def test_approval_without_an_event_is_a_clear_409(client, project_id, monkeypatch):
    """A report with no event yet must not read as an approval failure."""
    from app.config import settings as app_settings

    # no event at intake: Phase 11 would otherwise create one heuristically
    monkeypatch.setattr(app_settings, "auto_extract_on_intake", False)
    planner = login(client, "planner")["access_token"]
    field = login(client, "field")["access_token"]
    report = submit(client, field, project_id, "Area C grounding grid installed")
    assert report["extraction_status"] in {"pending", "disabled"}

    resp = review(client, planner, report["id"], "approve")
    assert resp.status_code == 409
    assert "no execution event" in resp.json()["detail"]


def test_unknown_report_is_404(client):
    planner = login(client, "planner")["access_token"]
    assert review(client, planner, 999999, "approve").status_code == 404


def test_queue_lists_the_work_with_its_top_candidate(client, stub_llm, project_id):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]
    report, body = ready_report(client, field, planner, project_id, stub_llm)

    queue = client.get(f"/api/queue?project_id={project_id}", headers=auth(planner))
    assert queue.status_code == 200, queue.text
    payload = queue.json()

    mine = next(i for i in payload["items"] if i["report"]["id"] == report["id"])
    assert mine["review_status"] in {"PENDING", "NEEDS_MANUAL"}
    assert mine["top"]["activity"]["code"] == body["candidates"][0]["activity"]["code"]
    assert mine["top"]["confidence_band"] in {"high", "medium", "low"}
    assert {r["rule"] for r in mine["top"]["rules"]} == {
        "location", "discipline", "tag", "date_plausibility"
    }
    assert payload["counts"]["all"] == 1, "the queue is scoped to the project"
    assert payload["counts"]["pending"] == 1, "PENDING must be counted exactly once"
    assert payload["counts"]["approved"] == 0

    # approve, then the same report shows up under the approved filter
    review(client, planner, report["id"], "approve", {})
    approved = client.get(
        f"/api/queue?project_id={project_id}&filter=approved", headers=auth(planner)
    ).json()
    assert any(i["report"]["id"] == report["id"] for i in approved["items"])
    assert approved["counts"]["approved"] == 1
    assert approved["counts"]["pending"] == 0

    # PM reads the queue, FIELD cannot
    assert client.get(f"/api/queue?project_id={project_id}", headers=auth(pm)).status_code == 200
    assert client.get("/api/queue", headers=auth(field)).status_code == 403
    assert client.get("/api/queue").status_code == 401


def test_test_project_never_leaks_into_the_demo_data(client, stub_llm, project_id):
    """Cleanup contract: an approval touches only its own project's nodes.

    Asserted as a before/after diff — the demo DB legitimately carries
    actuals of its own, so scanning for "any actuals outside TEST" would
    fail for reasons unrelated to what this test did.
    """
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    report, _ = ready_report(client, field, planner, project_id, stub_llm)

    def actuals_by_id() -> dict[int, int | None]:
        db = SessionLocal()
        try:
            return {n.id: n.actual_report_id for n in db.scalars(select(WbsNode)).all()}
        finally:
            db.close()

    before = actuals_by_id()
    review(client, planner, report["id"], "approve", {})
    after = actuals_by_id()

    changed = [i for i in after if after[i] != before.get(i)]
    assert changed, "the approved activity should carry actuals"

    db = SessionLocal()
    try:
        touched = db.scalars(select(WbsNode).where(WbsNode.id.in_(changed))).all()
    finally:
        db.close()
    outside = [n.code for n in touched if n.project_id != project_id]
    assert not outside, f"actuals must never be written onto the demo project: {outside}"
