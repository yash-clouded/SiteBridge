"""Phase 4: the one LLM call behind "report -> execution event".

Everything here is transport only: build a chat-completions request, return
the raw assistant text. Parsing, validation and the no-invention rules live
in `services/extraction.py`.

Works against any OpenAI-compatible `/chat/completions` server (OpenAI,
Azure, vLLM, Ollama, ...). With no API key and the default OpenAI base URL
the extractor is reported as NOT configured — the caller then skips
extraction instead of guessing.
"""
from __future__ import annotations

import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class LlmNotConfigured(Exception):
    """No usable LLM endpoint (no API key and default base URL)."""


class LlmError(Exception):
    """The endpoint answered with an error or an unusable body."""


def configured() -> bool:
    """True when an endpoint can realistically be reached."""
    if settings.llm_api_key.strip():
        return True
    # A non-default base URL is a self-hosted server that needs no key.
    return settings.llm_base_url.strip().rstrip("/") != DEFAULT_OPENAI_BASE_URL


def chat_json(system: str, user: str) -> str:
    """Single chat completion. Returns the raw assistant message content."""
    if not configured():
        raise LlmNotConfigured(
            "No LLM configured — set LLM_API_KEY (or LLM_BASE_URL for a "
            "self-hosted server). Extraction is skipped rather than guessed."
        )

    payload: dict = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": settings.llm_temperature,
    }
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {}
    key = settings.llm_api_key.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise LlmError(f"LLM request failed: {exc}") from exc

    if resp.status_code >= 400:
        raise LlmError(f"LLM returned HTTP {resp.status_code}: {resp.text[:400]}")
    try:
        body = resp.json()
        content = body["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"LLM response had no message content: {resp.text[:400]}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LlmError("LLM returned an empty message.")
    return content
