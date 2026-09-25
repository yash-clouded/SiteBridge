"""Phase 5: text -> vector.

Two providers behind one function so the pgvector tables, the retrieval
query and the UI never care which one is active:

  * ``openai``  — an OpenAI-compatible ``/embeddings`` endpoint (semantic).
  * ``local``   — deterministic feature hashing. Not a language model, but
                  it is reproducible, offline and free, so the whole
                  pipeline (and the tests) run with no API key. Selected
                  automatically when no embedding key is configured.

Both produce ``settings.embedding_dim``-wide, L2-normalised vectors.
"""
from __future__ import annotations

import hashlib
import logging
import re

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_TOKEN_RE = re.compile(r"[a-z0-9]+")

LOCAL_PROVIDER = "local"
OPENAI_PROVIDER = "openai"


class EmbeddingError(Exception):
    """The embedding provider failed or returned the wrong vector width."""


def provider() -> str:
    """Resolve the configured provider ('auto' -> openai when a key exists)."""
    configured = settings.embedding_provider.strip().lower()
    if configured in {LOCAL_PROVIDER, OPENAI_PROVIDER}:
        return configured
    if configured != "auto":
        raise EmbeddingError(f"Unknown embedding provider '{settings.embedding_provider}'.")
    if settings.embedding_api_key.strip() or settings.llm_api_key.strip():
        return OPENAI_PROVIDER
    return LOCAL_PROVIDER


def _base_url() -> str:
    custom = settings.embedding_base_url.strip()
    if custom:
        return custom.rstrip("/")
    return settings.llm_base_url.rstrip("/")


def _api_key() -> str:
    return settings.embedding_api_key.strip() or settings.llm_api_key.strip()


def _openai_embeddings(texts: list[str]) -> list[list[float]]:
    payload: dict = {"model": settings.embedding_model, "input": texts}
    if settings.embedding_model.startswith("text-embedding-3"):
        payload["dimensions"] = settings.embedding_dim

    headers = {}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = _base_url() + "/embeddings"
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise EmbeddingError(f"Embedding request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise EmbeddingError(f"Embedding endpoint HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        rows = sorted(resp.json()["data"], key=lambda item: item["index"])
        vectors = [row["embedding"] for row in rows]
    except (ValueError, KeyError, TypeError) as exc:
        raise EmbeddingError(f"Malformed embedding response: {resp.text[:300]}") from exc
    return vectors


def _features(text: str) -> dict[str, float]:
    """Token + adjacent-token-bigram features, weighted for rare tokens."""
    tokens = _TOKEN_RE.findall(text.lower())
    weights: dict[str, float] = {}
    for token in tokens:
        weights[token] = weights.get(token, 0.0) + 1.0
    for left, right in zip(tokens, tokens[1:]):
        gram = f"{left}_{right}"
        weights[gram] = weights.get(gram, 0.0) + 0.5
    return weights


def _hash_to_bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if value & (1 << 63) else -1.0


def _local_embeddings(texts: list[str]) -> list[list[float]]:
    dim = settings.embedding_dim
    vectors: list[list[float]] = []
    for text in texts:
        vector = [0.0] * dim
        for feature, weight in _features(text).items():
            bucket, sign = _hash_to_bucket(feature, dim)
            vector[bucket] += sign * weight
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]
        vectors.append(vector)
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch. Empty strings yield the zero vector, never an error."""
    if not texts:
        return []
    chosen = provider()
    vectors = (
        _openai_embeddings(texts) if chosen == OPENAI_PROVIDER else _local_embeddings(texts)
    )
    if len(vectors) != len(texts):
        raise EmbeddingError(f"Provider returned {len(vectors)} vectors for {len(texts)} inputs.")
    for i, vector in enumerate(vectors):
        if len(vector) != settings.embedding_dim:
            raise EmbeddingError(
                f"Vector {i} has width {len(vector)}, expected {settings.embedding_dim}."
            )
    return vectors


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]


def model_name() -> str:
    """Name stored alongside a vector so rebuilds are traceable."""
    if provider() == OPENAI_PROVIDER:
        return settings.embedding_model
    return f"hash-{settings.embedding_dim}"
