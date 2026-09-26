"""Multilingual intake: detect -> translate -> English extraction.

Everything here runs offline: `translate._post` (the one HTTP seam) is
stubbed, `settings.sarvam_api_key` is set per test, and the autouse
`_offline` fixture keeps the real key out of the suite entirely.
"""
from __future__ import annotations

import json

import pytest

from app.config import settings
from app.services import extraction, translate
from app.services.translate import TranslationError, chunks

from conftest import auth, first_project_id, login

HINDI = "एरिया बी में केबल ट्रे इंस्टॉलेशन 60 प्रतिशत पूर्ण है।"
ENGLISH_OUT = "Cable tray installation in Area B is 60 percent complete."


def _fake_post(calls):
    def fake_post(client, path, payload):
        calls.append((path, payload))
        if path == "/text-lid":
            return {"language_code": "hi-IN", "script_code": "Deva"}
        return {
            "request_id": "test",
            "translated_text": ENGLISH_OUT,
            "source_language_code": payload["source_language_code"],
        }

    return fake_post


def _text(client, token, project_id, text=HINDI, **extra):
    resp = client.post(
        "/api/reports/text",
        json={"project_id": project_id, "raw_text": text, **extra},
        headers=auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "sarvam_api_key", "test-key")
    monkeypatch.setattr(settings, "translate_on_intake", True)


def test_translated_report_is_extracted_from_the_english_text(
    client, monkeypatch, keys
):
    """Detected Hindi -> stored English -> extraction reads the English one."""
    calls: list = []
    monkeypatch.setattr(translate, "_post", _fake_post(calls))
    seen: dict = {}

    def fake_chat_json(system, user):
        seen["user"] = user
        return json.dumps({"description": "Cable tray installation", "progress": 60})

    monkeypatch.setattr(extraction, "chat_json", fake_chat_json)

    token = login(client, "field")["access_token"]
    body = _text(client, token, first_project_id(client, token))

    assert body["translation_status"] == "translated"
    assert body["language_code"] == "hi-IN"
    assert body["translated_text"] == ENGLISH_OUT
    assert body["raw_text"] == HINDI  # evidence never edited
    assert seen["user"] == ENGLISH_OUT  # the model saw English
    assert body["extraction_status"] == "extracted"
    assert [path for path, _ in calls] == ["/text-lid", "/translate"]


def test_english_submission_is_not_translated(client, monkeypatch, keys):
    calls: list = []

    def fake_post(client_, path, payload):
        calls.append(path)
        return {"language_code": "en-IN", "script_code": "Latn"}

    monkeypatch.setattr(translate, "_post", fake_post)

    token = login(client, "field")["access_token"]
    body = _text(
        client, token, first_project_id(client, token),
        text="Area B cable tray installation is 60 percent complete.",
    )

    assert body["translation_status"] == "skipped"
    assert body["language_code"] == "en-IN"
    assert body["translated_text"] is None
    assert calls == ["/text-lid"]


def test_declared_language_skips_detection(client, monkeypatch, keys):
    calls: list = []
    monkeypatch.setattr(translate, "_post", _fake_post(calls))

    token = login(client, "field")["access_token"]
    body = _text(
        client, token, first_project_id(client, token),
        language="ta-IN",
    )

    assert body["language_code"] == "ta-IN"
    assert body["translation_status"] == "translated"
    assert [path for path, _ in calls] == ["/translate"]
    assert calls[0][1]["source_language_code"] == "ta-IN"


def test_translation_failure_never_blocks_the_submission(
    client, monkeypatch, keys
):
    """A dead translation endpoint still yields a 201 and an extraction."""
    def boom(client_, path, payload):
        raise TranslationError(f"{path} returned 429: quota exceeded")

    monkeypatch.setattr(translate, "_post", boom)

    token = login(client, "field")["access_token"]
    body = _text(client, token, first_project_id(client, token))

    assert body["translation_status"] == "failed"
    assert "429" in body["translation_error"]
    assert body["raw_text"] == HINDI
    assert body["translated_text"] is None
    # extraction still ran (Phase 11 heuristic rung — LLM key is cleared)
    assert body["extraction_status"] == "extracted"


def test_without_a_key_translation_is_disabled_not_attempted(client):
    """The suite default: no SARVAM_API_KEY -> recorded as disabled."""
    token = login(client, "field")["access_token"]
    body = _text(client, token, first_project_id(client, token))

    assert body["translation_status"] == "disabled"
    assert body["translated_text"] is None
    assert body["extraction_status"] == "extracted"


def test_chunks_respect_the_api_limit():
    text = " ".join(f"Work item {i} is complete." for i in range(400))
    limit = 200
    parts = chunks(text, limit)
    assert parts and all(len(part) <= limit for part in parts)
    # nothing is lost, nothing is duplicated
    assert " ".join(" ".join(parts).split()) == " ".join(text.split())
    assert chunks("", limit) == []
    assert chunks("short", limit) == ["short"]


def test_status_reports_the_translation_rung(client, monkeypatch):
    token = login(client, "planner")["access_token"]
    body = client.get("/api/status", headers=auth(token)).json()
    assert body["translation"] == {
        "on_intake": True,
        "configured": False,  # `_offline` cleared the key
        "model": settings.sarvam_translate_model,
        "target_language": settings.sarvam_target_language,
    }
    assert any("SARVAM_API_KEY" in note for note in body["degraded"])
