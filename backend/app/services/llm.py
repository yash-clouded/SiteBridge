"""Phase 4 + Phase 11: the one LLM call behind "report -> execution event".

Everything here is transport only: build a chat-completions request, return
the raw assistant text. Parsing, validation and the no-invention rules live
in `services/extraction.py`.

Works against any OpenAI-compatible `/chat/completions` server (OpenAI,
Azure, vLLM, Ollama, ...).

Phase 11 — the endpoint ladder. With no usable endpoint at all the extractor
reports NOT configured and the caller drops to the heuristic extractor (or,
if `EXTRACTION_FALLBACK=off`, marks the report `disabled`). When a secondary
endpoint (`LLM_FALLBACK_*`) is configured it is tried only after the primary
FAILED — a healthy primary is never bypassed, and a keyless local server
(Ollama, vLLM, LAN NIM) is treated as reachable while a hosted URL without a
key is not (that would turn a missing key into a live 401).
"""
from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LlmNotConfigured(Exception):
    """No usable LLM endpoint (no API key and no reachable keyless server)."""


class LlmError(Exception):
    """Every endpoint answered with an error or an unusable body."""


@dataclass(frozen=True)
class Endpoint:
    """One rung of the ladder."""

    base_url: str
    api_key: str
    model: str
    label: str  # "primary" | "fallback"

    @property
    def host(self) -> str:
        return (urlparse(self.base_url).hostname or self.base_url).lower()


def _keyless(base_url: str) -> bool:
    """True for a server that does not need a key (Ollama, vLLM, LAN NIM).

    A hosted endpoint (build.nvidia.com, api.openai.com, ...) is never
    treated as reachable without a key — that would turn a missing key into
    a live 401 instead of a clear "not configured".
    """
    host = (urlparse(base_url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def _usable(base_url: str, api_key: str) -> bool:
    if api_key.strip():
        return True
    return _keyless(base_url)


def endpoints() -> list[Endpoint]:
    """The ladder, healthy-rung first: primary, then the configured fallback."""
    rungs: list[Endpoint] = []
    if _usable(settings.llm_base_url, settings.llm_api_key):
        rungs.append(
            Endpoint(settings.llm_base_url, settings.llm_api_key, settings.llm_model, "primary")
        )
    if settings.llm_fallback_base_url.strip() and _usable(
        settings.llm_fallback_base_url, settings.llm_fallback_api_key
    ):
        rungs.append(
            Endpoint(
                settings.llm_fallback_base_url,
                settings.llm_fallback_api_key,
                settings.llm_fallback_model or settings.llm_model,
                "fallback",
            )
        )
    return rungs


def configured() -> bool:
    """True when at least one endpoint can realistically be reached."""
    return bool(endpoints())


def chat_json(system: str, user: str) -> str:
    """Single chat completion. Returns the raw assistant message content.

    Walks the ladder: a failing rung is logged and the next one is tried;
    only when every rung fails does this raise. `LlmNotConfigured` means no
    rung exists — the caller decides between the heuristic and `disabled`.
    """
    rungs = endpoints()
    if not rungs:
        raise LlmNotConfigured(
            "No LLM configured — set LLM_API_KEY (or LLM_BASE_URL for a "
            "self-hosted server), or leave EXTRACTION_FALLBACK=heuristic to "
            "extract without a model. Nothing is guessed either way."
        )

    failures: list[str] = []
    for rung in rungs:
        try:
            return _call(rung, system, user)
        except LlmError as exc:
            failures.append(f"{rung.label} [{rung.host}]: {exc}")
            logger.warning("LLM %s endpoint failed: %s", rung.label, exc)
    raise LlmError("All LLM endpoints failed — " + " | ".join(failures))


def _call(rung: Endpoint, system: str, user: str) -> str:
    payload: dict = {
        "model": rung.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": settings.llm_temperature,
    }
    if settings.llm_json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {}
    key = rung.api_key.strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"

    url = rung.base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=settings.llm_timeout_seconds) as client:
            resp = client.post(url, json=payload, headers=headers)
            # Some OpenAI-compatible servers reject `response_format`. The
            # prompt already demands bare JSON and the parser enforces it, so
            # dropping the flag is safe and keeps the extractor working.
            if resp.status_code == 400 and "response_format" in resp.text:
                logger.warning("Endpoint rejected response_format — retrying without it.")
                payload.pop("response_format", None)
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
