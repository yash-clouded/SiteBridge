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

import ipaddress
import logging
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LlmNotConfigured(Exception):
    """No usable LLM endpoint (no API key and no reachable keyless server)."""


class LlmError(Exception):
    """The endpoint answered with an error or an unusable body."""


def _local_endpoint() -> bool:
    """True for a server that does not need a key (Ollama, vLLM, LAN NIM).

    A hosted endpoint (build.nvidia.com, api.openai.com, ...) is never
    treated as reachable without a key — that would turn a missing key into
    a live 401 instead of a clear "not configured".
    """
    host = (urlparse(settings.llm_base_url).hostname or "").lower()
    if host in LOCAL_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def configured() -> bool:
    """True when an endpoint can realistically be reached."""
    if settings.llm_api_key.strip():
        return True
    return _local_endpoint()


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
            resp = _post(client, url, payload, headers)
            # Some OpenAI-compatible servers reject `response_format`. The
            # prompt already demands bare JSON and the parser enforces it, so
            # dropping the flag is safe and keeps the extractor working.
            if resp.status_code == 400 and "response_format" in resp.text:
                logger.warning("Endpoint rejected response_format — retrying without it.")
                payload.pop("response_format", None)
                resp = _post(client, url, payload, headers)
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


def _post(client: httpx.Client, url: str, payload: dict, headers: dict) -> httpx.Response:
    return client.post(url, json=payload, headers=headers)
