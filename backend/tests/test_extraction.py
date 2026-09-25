"""Phase 4 tests: one LLM call per report -> one structured event.

The LLM is stubbed — these tests are about the contract, not the model:
JSON only, missing field => null, never a substitute value, and a failed
extraction records why instead of writing a half-filled event.
"""
from __future__ import annotations

import json

import pytest
import app.services.extraction as extraction
from conftest import auth, first_project_id, login

from app.config import settings
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import ExecutionEvent, FieldReport


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the transport: `install(reply)` makes the next call return reply."""
    calls: list[str] = []

    def install(reply) -> None:
        if isinstance(reply, Exception):
            def _raise(system: str, user: str) -> str:
                raise reply
            monkeypatch.setattr(extraction, "chat_json", _raise)
            return
        text = reply if isinstance(reply, str) else json.dumps(reply)
        def _reply(system: str, user: str) -> str:
            calls.append(user)
            return text
        monkeypatch.setattr(extraction, "chat_json", _reply)

    install.default_calls = calls  # type: ignore[attr-defined]
    return install


def submit(client, token, project_id, text="Pipework in Area A complete"):
    resp = client.post(
        "/api/reports/text",
        headers=auth(token),
        json={"project_id": project_id, "raw_text": text, "source_type": "text"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def process(client, planner_token, report_id):
    return client.post(f"/api/reports/{report_id}/process", headers=auth(planner_token))


def db_report(report_id: int) -> FieldReport:
    db = SessionLocal()
    try:
        return db.get(FieldReport, report_id)
    finally:
        db.close()


def test_unstated_fields_are_null_never_invented(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Installed 24-inch spool pieces rack bays 1 to 3.")

    stub_llm({"description": "Installed 24-inch spool pieces rack bays 1 to 3",
              "discipline": "Piping"})
    resp = process(client, planner, report["id"])
    assert resp.status_code == 200, resp.text
    event = resp.json()["event"]

    assert event["description"] == "Installed 24-inch spool pieces rack bays 1 to 3"
    assert event["discipline"] == "Piping"
    for key in ("location", "tag", "event_date", "status", "quantity", "progress"):
        assert event[key] is None, f"{key} was invented: {event[key]!r}"

    # evidence chain: event -> the raw report it came from
    assert event["field_report_id"] == report["id"]
    stored = db_report(report["id"])
    assert stored.extraction_status == "extracted"
    assert stored.extraction_error is None


def test_empty_object_extracts_a_fully_null_event(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "did some work")

    stub_llm({})
    resp = process(client, planner, report["id"])
    assert resp.status_code == 200, resp.text
    event = resp.json()["event"]
    assert event["description"] is None
    assert event["event_date"] is None
    assert event["quantity"] is None
    assert event["review_status"] == "PENDING"


def test_wrong_types_are_dropped_not_converted(client, stub_llm):
    """A number is not a description; garbage is null, not a coercion."""
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "work happened")

    stub_llm({"description": 123, "quantity": "several", "tag": {"id": 7},
              "date": "not a date", "progress": True})
    resp = process(client, planner, report["id"])
    assert resp.status_code == 200, resp.text
    event = resp.json()["event"]
    assert event["description"] is None
    assert event["quantity"] is None
    assert event["tag"] is None
    assert event["event_date"] is None
    assert event["progress"] is None


def test_values_are_coerced_to_their_declared_types(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "poured 12 m3, 60% complete on 2026-01-15")

    stub_llm({"date": "2026-01-15", "quantity": "12 m3", "progress": "60%",
              "status": "In progress"})
    resp = process(client, planner, report["id"])
    event = resp.json()["event"]
    assert event["event_date"] == "2026-01-15"
    assert event["quantity"] == 12.0
    assert event["progress"] == 60.0
    assert event["status"] == "In progress"


def test_code_fences_are_tolerated(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "graded subgrade Area B")

    stub_llm('```json\n{"description": "Graded subgrade Area B"}\n```')
    resp = process(client, planner, report["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["event"]["description"] == "Graded subgrade Area B"


def test_non_json_reply_fails_the_extraction_without_writing_an_event(
    client, stub_llm, monkeypatch
):
    """A model that ANSWERS with junk is failed — never downgraded to a rung
    that would happily guess where the model would not."""
    monkeypatch.setattr(settings, "auto_extract_on_intake", False)
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "graded subgrade Area B")

    stub_llm("Sure! Here is the work you asked for: ...")
    resp = process(client, planner, report["id"])
    assert resp.status_code == 422, resp.text

    stored = db_report(report["id"])
    assert stored.extraction_status == "failed"
    assert "not JSON" in (stored.extraction_error or "")
    db = SessionLocal()
    try:
        count = db.scalar(
            select(func.count(ExecutionEvent.id)).where(
                ExecutionEvent.field_report_id == report["id"]
            )
        )
    finally:
        db.close()
    assert count == 0, "a half-parsed event was written"


def test_no_llm_falls_back_to_the_heuristic_rung(client):
    """Phase 11: no endpoint -> pattern extraction, still no invention.

    Values the report states are read; everything else stays null, and the
    event records WHICH rung produced it so the queue can show it.
    """
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(
        client,
        field,
        pid,
        "Area C grounding grid installed 12 pads on 2026-01-15, 60% complete.",
    )

    assert report["extraction_status"] == "extracted"
    assert report["extraction_error"] is None

    resp = process(client, planner, report["id"])
    assert resp.status_code == 200, resp.text
    event = resp.json()["event"]
    assert event["model"] == "heuristic-v1"
    assert event["prompt_version"] == "heuristic"
    assert event["location"] == "Area C"
    assert event["quantity"] == 12.0
    assert event["progress"] == 60.0
    assert event["event_date"] == "2026-01-15"
    assert event["discipline"] is None, "the report names no trade — do not invent one"
    assert "heuristic-v1" in (event["raw_model_response"] or "")

    # raw evidence is untouched either way
    stored = db_report(report["id"])
    assert stored.raw_text.startswith("Area C grounding grid")


def test_heuristic_fallback_can_be_switched_off(client, monkeypatch):
    """EXTRACTION_FALLBACK=off keeps the strict contract: no endpoint, no event."""
    monkeypatch.setattr(settings, "extraction_fallback", "off")
    field = login(client, "field")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "Area C grounding grid installed")

    assert report["extraction_status"] == "disabled"
    assert "LLM" in (report["extraction_error"] or "")
    db = SessionLocal()
    try:
        stored = db.get(FieldReport, report["id"])
        assert stored is not None
        assert stored.raw_text.startswith("Area C grounding grid")
        assert db.scalar(
            select(func.count(ExecutionEvent.id)).where(
                ExecutionEvent.field_report_id == report["id"]
            )
        ) == 0
    finally:
        db.close()


def test_only_planner_can_process(client, stub_llm):
    stub_llm({"description": "some work"})
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "some work")

    assert process(client, field, report["id"]).status_code == 403
    assert process(client, pm, report["id"]).status_code == 403
    assert process(client, planner, report["id"]).status_code == 200
    assert client.post(f"/api/reports/{report['id']}/process").status_code == 401


def test_reviewed_event_is_never_re_extracted(client, stub_llm):
    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, field)
    report = submit(client, field, pid, "installed valve V-204")

    stub_llm({"description": "Installed valve V-204"})
    assert process(client, planner, report["id"]).status_code == 200

    db = SessionLocal()
    try:
        event = db.scalar(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id == report["id"])
        )
        event.review_status = "APPROVED"
        db.commit()
    finally:
        db.close()

    stub_llm({"description": "this would rewrite reviewed evidence"})
    resp = process(client, planner, report["id"])
    assert resp.status_code == 409

    db = SessionLocal()
    try:
        event = db.scalar(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id == report["id"])
        )
        assert event.description == "Installed valve V-204"
    finally:
        db.close()
