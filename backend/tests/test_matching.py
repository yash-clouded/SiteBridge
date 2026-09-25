"""Phase 5 + Phase 6 tests: retrieval with knowledge-graph re-scoring, and
the deterministic pass/fail/unknown rule checks.

The LLM is stubbed so the pipeline under test is retrieval + verification.
"""
from __future__ import annotations

import json
from datetime import date

import pytest
import app.services.extraction as extraction
from conftest import auth, first_project_id, login
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    ActivityEmbedding,
    ExecutionEvent,
    FieldReport,
    MatchCandidate,
    WbsNode,
)

RULES = {"location", "discipline", "tag", "date_plausibility"}


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


def run(client, token, report_id):
    resp = client.post(f"/api/reports/{report_id}/process", headers=auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def match(client, token, report_id):
    return client.get(f"/api/reports/{report_id}/match", headers=auth(token))


def rules_of(candidate) -> dict:
    return {r["rule"]: r for r in candidate["rules"]}


def candidate_by_code(body, code: str) -> dict | None:
    return next((c for c in body["candidates"] if c["activity"]["code"] == code), None)


def approve_predecessor(project_id, node_code, report, *, status, event_date):
    """Create an approved execution event for an activity (stands in for Phase 8)."""
    db = SessionLocal()
    try:
        node = db.scalar(
            select(WbsNode).where(WbsNode.project_id == project_id, WbsNode.code == node_code)
        )
        assert node is not None, f"{node_code} not in schedule"
        event = db.scalar(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id == report["id"])
        )
        if event is None:
            event = ExecutionEvent(
                project_id=project_id, field_report_id=report["id"]
            )
            db.add(event)
            db.flush()
        event.project_id = project_id
        event.status = status
        event.event_date = date.fromisoformat(event_date) \
            if isinstance(event_date, str) else event_date
        event.review_status = "APPROVED"
        candidate = db.scalar(
            select(MatchCandidate).where(
                MatchCandidate.execution_event_id == event.id,
                MatchCandidate.wbs_node_id == node.id,
            )
        )
        if candidate is None:
            db.add(
                MatchCandidate(
                    project_id=project_id,
                    field_report_id=report["id"],
                    execution_event_id=event.id,
                    wbs_node_id=node.id,
                    rank=1,
                    semantic_score=1.0,
                    kg_score=1.0,
                    score=1.0,
                    breakdown={},
                )
            )
        db.commit()
    finally:
        db.close()


def test_activities_are_embedded_at_import(client):
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, planner)
    resp = client.post(f"/api/projects/{pid}/embed", headers=auth(planner))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["embedded"] >= 0
    assert body["dim"] > 0

    db = SessionLocal()
    try:
        leaves = db.scalars(
            select(WbsNode).where(WbsNode.project_id == pid, WbsNode.is_leaf.is_(True))
        ).all()
        embedded = db.scalars(
            select(ActivityEmbedding).where(ActivityEmbedding.project_id == pid)
        ).all()
    finally:
        db.close()
    assert len(embedded) == len(leaves), "every leaf must have exactly one vector"
    assert all(e.content for e in embedded), "the embedded text is stored for auditability"


def test_retrieval_returns_ranked_candidates_with_signal_breakdown(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Excavated foundation for pump P-101 in Area A.")

    stub_llm({
        "description": "Excavate foundation for pump P-101",
        "discipline": "Civil",
        "location": "Area A",
        "tag": "P-101",
        "date": "2026-01-15",
        "status": "complete",
        "quantity": 1,
        "progress": 100,
    })
    body = run(client, planner, report["id"])

    assert body["event"]["description"].startswith("Excavate foundation")
    assert 1 <= len(body["candidates"]) <= 5
    ranks = [c["rank"] for c in body["candidates"]]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)

    for candidate in body["candidates"]:
        breakdown = candidate["breakdown"]
        assert {"semantic", "cosine_distance", "kg", "formula"} <= set(breakdown)
        assert 0.0 <= candidate["semantic_score"] <= 1.0
        assert 0.0 <= candidate["score"] <= 1.0
        # the individual signals are exposed, not just the total
        signals = breakdown["kg"]["signals"]
        assert set(signals) == {"area", "discipline", "tag", "links"}
        for signal in signals.values():
            assert signal["result"] in {"match", "mismatch", "unknown"}
        assert candidate["kg_score"] == pytest.approx(breakdown["kg"]["score"])

    top = body["candidates"][0]
    assert top["activity"]["code"] == "A1011", "semantic + KG should surface the exact activity"

    rules = rules_of(top)
    assert set(rules) == RULES
    assert rules["location"]["result"] == "pass"
    assert rules["discipline"]["result"] == "pass"
    assert rules["tag"]["result"] == "pass"
    # no approval history exists yet -> the rule must stay unknown, not pass
    assert rules["date_plausibility"]["result"] == "unknown"


def test_unknown_is_never_reported_as_pass_or_fail(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Some civil work in Area A.")

    # No tag stated by the report, and nothing about dates.
    stub_llm({"description": "Some civil work", "discipline": "Civil", "location": "Area A"})
    body = run(client, planner, report["id"])
    assert body["candidates"], "expected candidates"

    for candidate in body["candidates"]:
        rules = rules_of(candidate)
        assert rules["tag"]["result"] == "unknown"
        assert rules["date_plausibility"]["result"] == "unknown"
        assert rules["location"]["result"] in {"pass", "fail", "unknown"}


def test_mismatching_discipline_is_a_fail_not_unknown(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Cable tray installed for pump P-101.")

    stub_llm({"description": "Excavate foundation for pump P-101",
              "discipline": "Electrical", "location": "Area A", "tag": "P-101"})
    body = run(client, planner, report["id"])

    target = candidate_by_code(body, "A1011")
    assert target is not None, "A1011 should be among the top candidates"
    rules = rules_of(target)
    assert rules["discipline"]["result"] == "fail"
    assert rules["discipline"]["detail"]
    assert rules["location"]["result"] == "pass"
    assert rules["tag"]["result"] == "pass"


def test_date_plausibility_fails_when_a_predecessor_finished_later(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)

    # A1013 (pour foundation) has predecessor A1012 (rebar + formwork).
    report = submit(client, field, pid, "Poured concrete foundation P-101.")
    stub_llm({"description": "Pour concrete foundation P-101",
              "discipline": "Civil", "location": "Area A", "tag": "P-101",
              "date": "2026-01-20", "status": "complete"})
    body = run(client, planner, report["id"])
    target = candidate_by_code(body, "A1013")
    assert target is not None, "A1013 should be among the top candidates"
    assert rules_of(target)["date_plausibility"]["result"] == "unknown"

    # Approve the predecessor as complete AFTER the event date -> must FAIL.
    pred_report = submit(client, field, pid, "Rebar and formwork done.")
    approve_predecessor(
        pid, "A1012", pred_report, status="complete", event_date="2026-01-25"
    )

    body = run(client, planner, report["id"])
    target = candidate_by_code(body, "A1013")
    result = rules_of(target)["date_plausibility"]
    assert result["result"] == "fail"
    assert "A1012" in result["detail"]
    assert "2026-01-25" in result["detail"]


def test_date_plausibility_passes_when_predecessor_finished_before(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)

    report = submit(client, field, pid, "Poured concrete foundation P-101.")
    stub_llm({"description": "Pour concrete foundation P-101",
              "discipline": "Civil", "location": "Area A", "tag": "P-101",
              "date": "2026-01-26"})
    run(client, planner, report["id"])

    pred_report = submit(client, field, pid, "Rebar and formwork done.")
    approve_predecessor(
        pid, "A1012", pred_report, status="complete", event_date="2026-01-20"
    )

    body = run(client, planner, report["id"])
    result = rules_of(candidate_by_code(body, "A1013"))["date_plausibility"]
    assert result["result"] == "pass"
    assert "A1012" in result["detail"]


def test_unrecognised_predecessor_status_stays_unknown(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)

    report = submit(client, field, pid, "Poured concrete foundation P-101.")
    stub_llm({"description": "Pour concrete foundation P-101",
              "date": "2026-01-26"})
    run(client, planner, report["id"])

    pred_report = submit(client, field, pid, "Rebar done.")
    approve_predecessor(
        pid, "A1012", pred_report, status="mechanically complete", event_date="2026-01-20"
    )

    body = run(client, planner, report["id"])
    result = rules_of(candidate_by_code(body, "A1013"))["date_plausibility"]
    assert result["result"] == "unknown"
    assert "not a recognised completion state" in result["detail"]


def test_pm_can_read_matches_but_cannot_process(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Installed valve V-204 in Area B.")

    stub_llm({"description": "Install valve V-204", "discipline": "Piping",
              "location": "Area B"})
    run(client, planner, report["id"])

    read = match(client, pm, report["id"])
    assert read.status_code == 200, read.text
    assert read.json()["event"]["description"] == "Install valve V-204"
    assert client.post(
        f"/api/reports/{report['id']}/process", headers=auth(pm)
    ).status_code == 403

    assert match(client, field, report["id"]).status_code == 403
    assert match(client, planner, report["id"]).status_code == 200


def test_reprocessing_replaces_candidates_and_rule_checks(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Graded subgrade Area B.")

    stub_llm({"description": "Graded subgrade Area B", "location": "Area B"})
    first = run(client, planner, report["id"])
    second = run(client, planner, report["id"])

    ids1 = [c["id"] for c in first["candidates"]]
    ids2 = [c["id"] for c in second["candidates"]]
    assert not set(ids1) & set(ids2), "old candidates must be replaced, not duplicated"
    assert len(second["candidates"]) == len(first["candidates"])

    db = SessionLocal()
    try:
        event = db.scalar(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id == report["id"])
        )
        checks = db.scalars(
            select(MatchCandidate).where(MatchCandidate.execution_event_id == event.id)
        ).all()
        report_row = db.get(FieldReport, report["id"])
    finally:
        db.close()
    assert len(checks) == len(second["candidates"])
    assert report_row.extraction_status == "extracted"
