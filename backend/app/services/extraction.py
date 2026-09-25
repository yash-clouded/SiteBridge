"""Phase 4: extraction — one LLM call per report, one structured event.

Contract:
  * JSON only. The prompt demands a bare JSON object; the parser rejects
    anything it cannot read as JSON (code fences are tolerated, prose is not).
  * Missing field => null. The prompt forbids guessing and the parser turns
    anything absent, empty or unparseable into null. No value is ever
    substituted (no "today", no 0, no empty string).
  * One event per report (`field_reports.id` is unique on
    `execution_events`), so the evidence chain report -> event stays 1:1.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import PROMPT_VERSION, ExecutionEvent, FieldReport
from .llm import LlmNotConfigured, chat_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""You extract execution events from construction site field reports.

Reply with ONLY a JSON object. No prose, no markdown, no code fences.

JSON schema (all keys are optional):
{{
  "description": string | null,
  "discipline": string | null,
  "location": string | null,
  "tag": string | null,
  "date": "YYYY-MM-DD" | null,
  "status": string | null,
  "quantity": number | null,
  "progress": number | null
}}

Rules — follow them exactly:
1. Report ONLY what the field report explicitly states. Do not infer,
   do not extrapolate, do not apply domain knowledge to fill gaps.
2. If a value is not stated in the text, either omit the key or set it to
   null. NEVER guess. NEVER substitute a default (no today's date, no zero,
   no empty string, no "unknown").
3. "date" is the calendar date the work happened on, as stated. If the text
   only gives a relative expression ("yesterday", "last week") without an
   absolute date, use null.
4. "progress" is the percentage as stated, without the % sign
   ("60% complete" -> 60). "quantity" is the plain number as stated
   ("installed 24 spools" -> 24). Both are null when not stated.
5. "status" is the execution status word(s) actually used in the text
   (e.g. "complete", "in progress", "on hold"). null when not stated.
6. "description" is a faithful, concise restatement of the work performed.
7. "location" is the area/zone/position named in the text, "tag" is the
   equipment or line tag exactly as written, "discipline" is the trade or
   discipline named (or clearly spelled out) in the text.

This is prompt version {PROMPT_VERSION}."""


class ExtractionError(Exception):
    """The model returned something we refuse to store."""


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_payload(raw: str) -> dict[str, Any]:
    """Parse the model reply into the event field dict.

    Only JSON objects are accepted. Every field is coerced to its type or
    null — never to a substitute value.
    """
    text = _strip_fences(raw)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"Model reply is not JSON: {text[:300]}") from exc
    if not isinstance(obj, dict):
        raise ExtractionError("Model reply is JSON but not an object.")
    return obj


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return None  # a number is not a description/tag — do not invent text
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(parts) or None
    return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        result = float(match.group(0))
    else:
        return None
    return result if result == result and result not in (float("inf"), float("-inf")) else None


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    ts = pd.to_datetime(value.strip(), errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def coerce_event_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Map a parsed model object onto ExecutionEvent columns (null when absent)."""
    return {
        "description": _as_str(payload.get("description")),
        "discipline": _as_str(payload.get("discipline")),
        "location": _as_str(payload.get("location")),
        "tag": _as_str(payload.get("tag")),
        "event_date": _as_date(payload.get("date")),
        "status": _as_str(payload.get("status")),
        "quantity": _as_float(payload.get("quantity")),
        "progress": _as_float(payload.get("progress")),
    }


def extract_fields(report: FieldReport) -> dict[str, Any]:
    """Run the single LLM call for this report and return coerced fields.

    Raises LlmNotConfigured / LlmError / ExtractionError on failure —
    nothing is written in that case.
    """
    raw = chat_json(SYSTEM_PROMPT, report.raw_text)
    fields = coerce_event_fields(parse_payload(raw))
    fields["_raw"] = raw
    return fields


def get_event(db: Session, report: FieldReport) -> ExecutionEvent | None:
    return db.scalar(select(ExecutionEvent).where(ExecutionEvent.field_report_id == report.id))


def extract_event(db: Session, report: FieldReport) -> ExecutionEvent:
    """Create (or update) the execution event for a report. Commits on success.

    On failure the report is marked `failed` with the reason, and the
    exception is re-raised so callers can report it — no partial event.
    """
    existing = get_event(db, report)
    if existing is not None and existing.review_status in {"APPROVED", "REJECTED"}:
        raise ExtractionError(
            f"Report {report.id} was already reviewed ({existing.review_status}) — "
            "re-extraction would rewrite reviewed evidence."
        )

    try:
        fields = extract_fields(report)
    except LlmNotConfigured as exc:
        report.extraction_status = "disabled"
        report.extraction_error = str(exc)
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001 — any transport/parse failure
        report.extraction_status = "failed"
        report.extraction_error = str(exc)[:2000]
        db.commit()
        raise

    if existing is None:
        existing = ExecutionEvent(
            project_id=report.project_id, field_report_id=report.id
        )
        db.add(existing)

    raw = fields.pop("_raw")
    for key, value in fields.items():
        setattr(existing, key, value)
    existing.project_id = report.project_id
    existing.model = settings.llm_model
    existing.prompt_version = PROMPT_VERSION
    existing.raw_model_response = raw
    existing.extracted_at = datetime.now(timezone.utc)
    if existing.review_status in {"NEEDS_MANUAL", "REJECTED"}:
        existing.review_status = "PENDING"

    report.extraction_status = "extracted"
    report.extraction_error = None
    db.commit()
    db.refresh(existing)
    logger.info("Extracted execution event %s from report %s", existing.id, report.id)
    return existing
