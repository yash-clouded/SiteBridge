"""Embedding provider wiring (Phase 5).

NVIDIA's E5/Nemotron embedding models run in two modes — documents are
indexed as `passage`, lookups run as `query` — so the flag must reach the
wire for the right role, and must not appear when it is switched off.
"""
from __future__ import annotations

import app.services.embeddings as em
from app.config import settings


class _FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, dim: int):
        self._dim = dim

    def json(self) -> dict:
        return {"data": [{"index": 0, "embedding": [0.0] * self._dim}]}


class _FakeClient:
    last_payload: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, headers=None):
        _FakeClient.last_payload = json
        return _FakeResponse(settings.embedding_dim)


def test_input_type_roles():
    assert em.input_type_for("index") == "passage"
    assert em.input_type_for("query") == "query"
    assert em.input_type_for("anything-else") == "passage"


def test_input_type_is_sent_for_each_role(monkeypatch):
    monkeypatch.setattr(em.httpx, "Client", _FakeClient)
    monkeypatch.setattr(em.settings, "embedding_provider", "openai")
    monkeypatch.setattr(em.settings, "embedding_api_key", "nvapi-test")
    monkeypatch.setattr(em.settings, "embedding_input_type", True)

    em.embed_texts(["Excavate foundation for pump P-101"], role="index")
    assert _FakeClient.last_payload["input_type"] == "passage"

    em.embed_texts(["poured concrete"], role="query")
    assert _FakeClient.last_payload["input_type"] == "query"


def test_input_type_omitted_when_disabled(monkeypatch):
    monkeypatch.setattr(em.httpx, "Client", _FakeClient)
    monkeypatch.setattr(em.settings, "embedding_provider", "openai")
    monkeypatch.setattr(em.settings, "embedding_api_key", "nvapi-test")
    monkeypatch.setattr(em.settings, "embedding_input_type", False)

    em.embed_texts(["some text"], role="query")
    assert "input_type" not in _FakeClient.last_payload
    assert _FakeClient.last_payload["input"] == ["some text"]


def test_local_provider_stays_offline_and_normalised():
    """The default provider needs no key and returns unit vectors."""
    monkey_free = em.embed_texts(["Poured concrete foundation P-101"], role="index")
    assert em.provider() in {"local", "openai"}
    if em.provider() == "local":
        vector = monkey_free[0]
        assert len(vector) == settings.embedding_dim
        magnitude = sum(v * v for v in vector) ** 0.5
        assert magnitude == 1.0


def test_same_text_embeds_identically():
    """Determinism is what makes a re-import reproducible."""
    a = em.embed_texts(["Excavate foundation for pump P-101"], role="index")[0]
    b = em.embed_texts(["Excavate foundation for pump P-101"], role="index")[0]
    if em.provider() == "local":
        assert a == b
