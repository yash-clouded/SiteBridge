"""Phase 11: what is running — and what is running as a fallback.

Degradation must be visible, not silent: the UI reads `degraded` and says so
in plain words instead of letting a demo quietly become a different product.
Only configuration and resolved providers are reported — never a key — and a
host is exposed only as a hostname.
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..security import get_current_user
from ..services import embeddings, llm
from ..services.extraction import _enabled as heuristic_enabled

router = APIRouter(prefix="/api", tags=["status"])


class LlmStatus(BaseModel):
    configured: bool
    model: str
    endpoint: str  # primary hostname — never a key
    fallback_configured: bool
    fallback_model: str | None = None
    rungs: list[str] = []  # the ladder in order: ["primary", "fallback"]


class EmbeddingStatus(BaseModel):
    provider: str  # resolved: local | openai (never "auto")
    model: str
    dim: int
    input_type: bool
    fallback_local: bool


class ExtractionStatus(BaseModel):
    mode: str  # llm | heuristic | disabled — what a NEW report is extracted by
    fallback: str  # the configured ladder policy: heuristic | off
    auto_on_intake: bool


class SystemStatus(BaseModel):
    llm: LlmStatus
    embeddings: EmbeddingStatus
    extraction: ExtractionStatus
    database: bool
    degraded: list[str] = []


def _host(url: str) -> str:
    return (urlparse(url).hostname or url or "").lower()


def _mode(rungs: list[llm.Endpoint]) -> str:
    if rungs:
        return "llm"
    return "heuristic" if heuristic_enabled() else "disabled"


def _degraded(rungs: list[llm.Endpoint], embed_provider: str, mode: str) -> list[str]:
    notes: list[str] = []
    if not rungs:
        if mode == "heuristic":
            notes.append(
                "No LLM endpoint is configured — reports are extracted by pattern "
                "matching (heuristic), so values the report does not state stay null."
            )
        else:
            notes.append(
                "No LLM endpoint is configured and EXTRACTION_FALLBACK=off — reports "
                "are stored verbatim and no execution event is created."
            )
    if embed_provider == embeddings.LOCAL_PROVIDER:
        notes.append(
            "Embeddings run locally (deterministic hash vectors) — retrieval works "
            "offline but is lexical, not semantic."
        )
    if len(rungs) > 1:
        notes.append(
            f"LLM fallback endpoint in the ladder: {_host(rungs[1].base_url)} "
            f"(model {rungs[1].model})."
        )
    return notes


@router.get("/status", response_model=SystemStatus)
def system_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SystemStatus:
    """Resolved runtime mode, so the UI can say when it is running degraded."""
    rungs = llm.endpoints()
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:  # noqa: BLE001 — status must not explode when the DB is down
        database_ok = False

    embed_provider = embeddings.provider()
    mode = _mode(rungs)
    return SystemStatus(
        llm=LlmStatus(
            configured=bool(rungs),
            model=settings.llm_model,
            endpoint=_host(rungs[0].base_url if rungs else settings.llm_base_url),
            fallback_configured=len(rungs) > 1,
            fallback_model=rungs[1].model if len(rungs) > 1 else None,
            rungs=[r.label for r in rungs],
        ),
        embeddings=EmbeddingStatus(
            provider=embed_provider,
            model=embeddings.model_name(embed_provider),
            dim=settings.embedding_dim,
            input_type=settings.embedding_input_type,
            fallback_local=settings.embedding_fallback_local,
        ),
        extraction=ExtractionStatus(
            mode=mode,
            fallback=settings.extraction_fallback,
            auto_on_intake=settings.auto_extract_on_intake,
        ),
        database=database_ok,
        degraded=_degraded(rungs, embed_provider, mode),
    )
