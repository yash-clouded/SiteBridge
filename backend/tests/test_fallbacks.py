"""Phase 11 tests: fallbacks — the ladder, and never guessing when one runs.

Three invariants:
  * a healthy primary endpoint is never bypassed, a failing one falls
    through to the next rung, and a model that ANSWERS badly is failed —
    not silently downgraded;
  * the heuristic rung reads only what the text states (everything else is
    null), so "no LLM" never becomes "invented data";
  * embeddings never mix two vector spaces: a query is embedded in the
    space its index lives in, and a remote failure degrades to local only
    while that is still coherent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import app.services.extraction as extraction
import app.services.retrieval as retrieval
from conftest import auth, login
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import ActivityEmbedding, WbsNode
from app.services import heuristic, llm
from app.services.embeddings import EmbeddingError, LOCAL_PROVIDER, OPENAI_PROVIDER
from app.services.importer import import_schedule

SAMPLE_CSV = Path(__file__).resolve().parent.parent.parent / "demo" / "schedule_sample.csv"


@pytest.fixture
def project_id(client):
    db = SessionLocal()
    try:
        project = import_schedule(
            db, SAMPLE_CSV.read_bytes(), "schedule_sample.csv", "TESTFALL", "Test Fallback Project"
        )
        db.commit()
        return project.id
    finally:
        db.close()


# --- the LLM ladder ---------------------------------------------------------

def test_a_failing_primary_falls_through_to_the_configured_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "primary-key")
    monkeypatch.setattr(settings, "llm_fallback_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "llm_fallback_api_key", "")
    monkeypatch.setattr(settings, "llm_fallback_model", "local-model")

    seen: list[str] = []

    def fake_call(rung, system, user):
        seen.append(rung.label)
        if rung.label == "primary":
            raise llm.LlmError("LLM returned HTTP 503")
        return '{"description": "via the fallback endpoint"}'

    monkeypatch.setattr(llm, "_call", fake_call)
    assert llm.chat_json("system", "user") == '{"description": "via the fallback endpoint"}'
    assert seen == ["primary", "fallback"], "the fallback runs only after the primary fails"


def test_the_whole_ladder_is_reported_when_every_endpoint_fails(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "primary-key")
    monkeypatch.setattr(settings, "llm_fallback_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(settings, "llm_fallback_model", "local-model")

    monkeypatch.setattr(llm, "_call", lambda rung, s, u: (_ for _ in ()).throw(
        llm.LlmError("boom")
    ))
    with pytest.raises(llm.LlmError) as excinfo:
        llm.chat_json("system", "user")
    message = str(excinfo.value)
    assert "primary" in message and "fallback" in message


def test_no_endpoint_is_reported_as_not_configured(monkeypatch):
    assert llm.configured() is False  # the _offline fixture clears the key
    with pytest.raises(llm.LlmNotConfigured):
        llm.chat_json("system", "user")


def test_a_transport_failure_drops_to_the_heuristic_rung(client, monkeypatch):
    """Primary down, no fallback -> the text is still read, never guessed."""
    def boom(system, user):
        raise llm.LlmError("LLM returned HTTP 503")

    monkeypatch.setattr(extraction, "chat_json", boom)

    field = login(client, "field")["access_token"]
    planner = login(client, "planner")["access_token"]
    projects = client.get("/api/projects", headers=auth(field)).json()
    resp = client.post(
        "/api/reports/text",
        headers=auth(field),
        json={"project_id": projects[0]["id"], "raw_text": "Pipework in Area A 60% complete"},
    )
    assert resp.status_code == 201, resp.text
    report = resp.json()

    assert report["extraction_status"] == "extracted"
    processed = client.post(f"/api/reports/{report['id']}/process", headers=auth(planner))
    assert processed.status_code == 200, processed.text
    event = processed.json()["event"]
    assert event["model"] == heuristic.MODEL
    assert event["location"] == "Area A"
    assert event["progress"] == 60.0


# --- the heuristic rung: only what the text says ----------------------------

def test_heuristic_reads_stated_values_and_leaves_the_rest_null():
    fields = heuristic.extract(
        "On 2026-03-04 the crew installed 3 beams in Area B. P-101 piping is 45% complete."
    )
    assert fields["event_date"].isoformat() == "2026-03-04"
    assert fields["quantity"] == 3.0
    assert fields["location"] == "Area B"
    assert fields["tag"] == "P-101"
    assert fields["progress"] == 45.0
    assert fields["status"] == "complete"
    assert fields["discipline"] == "Piping"
    assert fields["description"].startswith("On 2026-03-04")


def test_heuristic_invents_nothing_for_text_without_patterns():
    fields = heuristic.extract("the crew worked hard all day")
    assert fields["event_date"] is None
    assert fields["progress"] is None
    assert fields["quantity"] is None
    assert fields["location"] is None
    assert fields["tag"] is None
    assert fields["status"] is None


def test_a_size_is_not_a_quantity_and_a_negation_is_not_a_status():
    fields = heuristic.extract("Installed 24-inch spool pieces, work not complete")
    assert fields["quantity"] is None, "'24-inch' is a size, not a count"
    assert fields["status"] is None, "'not complete' must not read as complete"
    assert fields["progress"] is None

    positive = heuristic.extract("Installed 24-inch spool pieces, work is complete")
    assert positive["status"] == "complete"


def test_impossible_dates_are_not_read():
    assert heuristic.extract("work done on 2026-02-30")["event_date"] is None
    assert heuristic.extract("on 2026-13-45")["event_date"] is None


# --- embeddings: one vector space, ever -------------------------------------

def test_query_embedding_follows_the_index_not_the_configuration(monkeypatch, project_id):
    """Configured for the cloud, index is local -> the query stays local."""
    monkeypatch.setattr(settings, "embedding_provider", OPENAI_PROVIDER)
    monkeypatch.setattr(settings, "embedding_api_key", "cloud-key")

    db = SessionLocal()
    try:
        node = db.scalar(select(WbsNode).where(WbsNode.project_id == project_id, WbsNode.is_leaf))
        row = db.scalar(
            select(ActivityEmbedding).where(ActivityEmbedding.wbs_node_id == node.id)
        )
        assert row is not None, "the fixture embeds the schedule on import"
        row.provider = LOCAL_PROVIDER
        row.model = "hash-1536"
        db.commit()

        def no_cloud(texts, *, role, provider_name=None):
            assert provider_name == LOCAL_PROVIDER, "a cloud call here would mix spaces"
            return [[0.2] * settings.embedding_dim for _ in texts]

        monkeypatch.setattr(retrieval, "embed_texts", no_cloud)
        vectors, used = retrieval.embed_for_project(db, node.project_id, ["query"], role="query")
        assert used == LOCAL_PROVIDER
        assert len(vectors) == 1
    finally:
        db.close()


def test_remote_failure_never_rewrites_a_remote_index(monkeypatch, project_id):
    """A remote index + a dead provider is an error, never a mixed space."""
    monkeypatch.setattr(settings, "embedding_provider", OPENAI_PROVIDER)
    monkeypatch.setattr(settings, "embedding_api_key", "cloud-key")

    db = SessionLocal()
    try:
        node = db.scalar(select(WbsNode).where(WbsNode.project_id == project_id, WbsNode.is_leaf))
        row = db.scalar(
            select(ActivityEmbedding).where(ActivityEmbedding.wbs_node_id == node.id)
        )
        assert row is not None, "the fixture embeds the schedule on import"
        row.provider = OPENAI_PROVIDER
        row.model = "text-embedding-3-small"
        db.commit()

        def dead(texts, *, role, provider_name=None):
            raise EmbeddingError("Embedding endpoint HTTP 503")

        monkeypatch.setattr(retrieval, "embed_texts", dead)
        with pytest.raises(EmbeddingError):
            retrieval.embed_for_project(db, node.project_id, ["query"], role="query")
    finally:
        db.close()


def test_remote_failure_degrades_to_local_while_the_index_is_empty(monkeypatch, project_id):
    monkeypatch.setattr(settings, "embedding_provider", OPENAI_PROVIDER)
    monkeypatch.setattr(settings, "embedding_api_key", "cloud-key")

    db = SessionLocal()
    try:
        def dead(texts, *, role, provider_name=None):
            if provider_name == OPENAI_PROVIDER:
                raise EmbeddingError("Embedding endpoint HTTP 503")
            return [[0.3] * settings.embedding_dim for _ in texts]

        monkeypatch.setattr(retrieval, "embed_texts", dead)
        vectors, used = retrieval.embed_for_project(db, project_id, ["text"], role="index")
        assert used == LOCAL_PROVIDER
        assert len(vectors) == 1
    finally:
        db.close()


# --- visibility -------------------------------------------------------------

def test_status_endpoint_reports_the_degraded_mode(client):
    planner = login(client, "planner")["access_token"]
    resp = client.get("/api/status", headers=auth(planner))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["llm"]["configured"] is False
    assert body["extraction"]["mode"] == "heuristic"
    assert body["embeddings"]["provider"] == LOCAL_PROVIDER
    assert body["database"] is True
    assert any("pattern matching" in note for note in body["degraded"])
    assert not body["llm"]["rungs"]


def test_status_endpoint_requires_a_session(client):
    assert client.get("/api/status").status_code == 401
    field = login(client, "field")["access_token"]
    assert client.get("/api/status", headers=auth(field)).status_code == 200
