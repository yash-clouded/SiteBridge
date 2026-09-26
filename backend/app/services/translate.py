"""Multilingual intake: detect -> translate -> hand English to the pipeline.

A field report can arrive in any supported Indian language. Before extraction
runs, the text is detected and translated to English so that the LLM prompt,
the knowledge-graph rules and the review queue all read one language — while
`field_reports.raw_text` stays the verbatim evidence it always was, with the
English rendering stored beside it.

Contracts (Phase 11 discipline):
  * Never raises out of `translate_report`. A submission is never lost because
    a translation call failed — the report keeps its raw text, the outcome is
    recorded (`failed` / `disabled`), and extraction falls back to the raw text.
  * Never logs or stores the API key: errors carry the API's message only.
  * Detection (`/text-lid`) has a 1000-char limit; `sarvam-translate:v1`
    accepts 2000 chars per call, so long reports are chunked on sentence
    boundaries and reassembled.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import FieldReport

logger = logging.getLogger(__name__)

# `/text-lid` caps its input; detection on the head of the report is enough.
DETECT_LIMIT = 1000
# Per-model input caps (see the Sarvam translate docs).
MODEL_LIMITS = {"sarvam-translate:v1": 2000, "mayura:v1": 1000}

# statuses written onto field_reports.translation_status
STATUS_NONE = "none"
STATUS_SKIPPED = "skipped"  # source is already the target language
STATUS_TRANSLATED = "translated"
STATUS_FAILED = "failed"
STATUS_DISABLED = "disabled"  # translation not configured


class TranslationError(Exception):
    """The translation service could not produce English text."""


@dataclass
class Translation:
    """Outcome of one translation attempt."""

    status: str
    language_code: str | None = None
    text: str | None = None  # English rendering; None when skipped/failed
    model: str | None = None
    error: str | None = None


def configured() -> bool:
    return bool(settings.sarvam_api_key.strip())


def _model_limit(model: str) -> int:
    return MODEL_LIMITS.get(model, 2000)


def _post(client: httpx.Client, path: str, payload: dict) -> dict:
    url = settings.sarvam_base_url.rstrip("/") + path
    try:
        response = client.post(
            url,
            json=payload,
            headers={"api-subscription-key": settings.sarvam_api_key.strip()},
        )
    except httpx.HTTPError as exc:
        raise TranslationError(f"{path} unreachable: {exc}") from exc
    if response.status_code >= 400:
        message = response.text[:300]
        try:
            body = response.json()
            err = body.get("error") or {}
            message = err.get("message") or message
        except ValueError:
            pass
        raise TranslationError(f"{path} returned {response.status_code}: {message}")
    try:
        return response.json()
    except ValueError as exc:
        raise TranslationError(f"{path} returned a non-JSON body") from exc


def _client(timeout: float | None = None) -> httpx.Client:
    return httpx.Client(timeout=timeout or settings.translate_timeout_seconds)


def detect(text: str) -> str | None:
    """Identify the source language (`en-IN`, `ta-IN`, ...). None when unsure."""
    head = text.strip()[:DETECT_LIMIT]
    if not head:
        return None
    with _client() as client:
        data = _post(client, "/text-lid", {"input": head})
    code = (data.get("language_code") or "").strip() or None
    return code


def chunks(text: str, limit: int) -> list[str]:
    """Split `text` into pieces of at most `limit` characters.

    Sentence boundaries are preferred so no clause is cut in half; a sentence
    longer than the limit is hard-split. Whitespace is not reflowed — the
    pieces are joined back with a newline.
    """
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= limit:
        return [clean]
    out: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            out.append(buf)
            buf = ""

    for sentence in re.split(r"(?<=[।.!?])\s+|\n+", clean):
        sentence = sentence.strip()
        if not sentence:
            continue
        while len(sentence) > limit:  # one sentence longer than the cap
            flush()
            out.append(sentence[:limit])
            sentence = sentence[limit:].strip()
        if not sentence:
            continue
        candidate = f"{buf}\n{sentence}" if buf else sentence
        if len(candidate) <= limit:
            buf = candidate
        else:
            flush()
            buf = sentence
    flush()
    return out


def _translate_chunks(text: str, source: str, target: str, model: str) -> str:
    limit = _model_limit(model)
    parts: list[str] = []
    with _client() as client:
        for piece in chunks(text, limit):
            data = _post(
                client,
                "/translate",
                {
                    "input": piece,
                    "source_language_code": source,
                    "target_language_code": target,
                    "model": model,
                },
            )
            translated = (data.get("translated_text") or "").strip()
            if not translated:
                raise TranslationError("translate returned an empty translation")
            parts.append(translated)
    return "\n".join(parts)


def translate_text(text: str, language: str | None = None) -> Translation:
    """Translate `text` to the target language and describe the outcome.

    `language` is an explicit source code the submitter declared (None or
    "auto" means detect). Detection failure falls back to a single `auto`
    call so a report is never left untranslated for lack of detection.
    """
    target = settings.sarvam_target_language
    model = settings.sarvam_translate_model
    declared = (language or "").strip()
    if declared.lower() in {"", "auto", "auto-detect"}:
        declared = ""
    source = declared or None
    if source is None:
        try:
            source = detect(text)
        except TranslationError as exc:
            logger.warning("Language detection failed: %s", exc)
            source = None
        if source is None:
            # last resort: mayura translates with built-in auto-detection
            with _client() as client:
                data = _post(
                    client,
                    "/translate",
                    {
                        "input": text[: _model_limit("mayura:v1")],
                        "source_language_code": "auto",
                        "target_language_code": target,
                        "model": "mayura:v1",
                    },
                )
            translated = (data.get("translated_text") or "").strip()
            if not translated:
                raise TranslationError("auto translation returned empty text")
            return Translation(
                status=STATUS_TRANSLATED,
                language_code=data.get("source_language_code") or None,
                text=translated,
                model="mayura:v1",
            )
    if source == target:
        return Translation(status=STATUS_SKIPPED, language_code=source, model=None)
    return Translation(
        status=STATUS_TRANSLATED,
        language_code=source,
        text=_translate_chunks(text, source, target, model),
        model=model,
    )


def translate_report(
    db: Session, report: FieldReport, language: str | None = None
) -> None:
    """Record the translation outcome on the report. Commits; never raises.

    Called after the raw evidence is committed and before extraction, so
    extraction reads `report.input_text` (the English rendering when one
    exists) while `raw_text` keeps the original wording.
    """
    if not settings.translate_on_intake:
        return
    if not configured():
        if report.translation_status != STATUS_DISABLED:
            report.translation_status = STATUS_DISABLED
            report.translation_error = (
                "SARVAM_API_KEY is not set — the report is extracted as submitted."
            )
            db.commit()
        return
    try:
        result = translate_text(report.raw_text, language=language)
    except TranslationError as exc:
        report.translation_status = STATUS_FAILED
        report.translation_error = str(exc)[:2000]
        report.translated_text = None
        report.language_code = None
        db.commit()
        logger.warning("Report %s: translation failed — %s", report.id, exc)
        return
    except Exception as exc:  # noqa: BLE001 — translation must never break intake
        report.translation_status = STATUS_FAILED
        report.translation_error = f"Unexpected translation failure: {exc}"[:2000]
        db.commit()
        logger.warning("Report %s: translation failed unexpectedly — %s", report.id, exc)
        return

    report.translation_status = result.status
    report.language_code = result.language_code
    report.translated_text = result.text
    report.translation_model = result.model
    report.translation_error = None
    report.translated_at = datetime.now(timezone.utc) if result.text else None
    db.commit()
