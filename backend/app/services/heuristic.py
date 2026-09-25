"""Phase 11: the last rung of the extraction ladder — pattern extraction.

Used when no LLM endpoint answers (no key, offline demo, or every endpoint
on the ladder failed). It is NOT a language model and does not try to be one:
it reads values the report states in a form a regex can match unambiguously,
and leaves everything else null.

Contract (identical to the LLM rung, `services/extraction.py`):
  * missing / unstated  -> null, never a default. No clock dates, no zero,
    no empty string, no "unknown";
  * negated status ("not complete") is not a status;
  * quantity only for "<number> <counted noun>" — "24-inch spool" is a size,
    not a quantity, so it is never read as one;
  * description is the report's own first sentence, quoted, never rewritten.

What it cannot read (a named area that is not spelled "Area X", a progress
figure written as words, a quantity with no counted noun) stays null — the
planner sees `NEEDS_MANUAL` / low confidence instead of a guess.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import pandas as pd

MODEL = "heuristic-v1"
PROMPT_VERSION = "heuristic"
MAX_DESCRIPTION = 240

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?,?\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR = re.compile(
    r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
# `%` is a non-word char: a `\b` after it would only match when the percent
# sign is glued to the next word, so the boundary belongs to "percent" alone.
_PROGRESS = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)
_QUANTITY = re.compile(
    r"\b(\d+)\s+(spools?|joints?|pads?|beams?|lengths?|valves?|bolts?|supports?|"
    r"pieces?|items?|units?|scaffolds?|layers?|flanges?|elbows?|tees?)\b",
    re.IGNORECASE,
)
_STATUS = [
    r"\bnot\s+started\b",
    r"\bunder\s+construction\b",
    r"\bin\s+progress\b",
    r"\bon\s+hold\b",
    r"\bblock(?:ed|ing)\b",
    r"\bdelay(?:ed|ing)\b",
    r"\bpending\b",
    r"\bpause[d]?\b",
    r"\bresumed\b",
    r"\bongoing\b",
    r"\bstart(?:ed|ing)\b",
    r"\bcomplete[d]?\b",
]
_DISCIPLINES = [
    "instrumentation",
    "insulation",
    "scaffolding",
    "structural",
    "mechanical",
    "electrical",
    "piping",
    "welding",
    "painting",
    "telecom",
    "civil",
    "hvac",
]
_AREA = re.compile(r"\barea\s+([a-z]\d{0,2})\b", re.IGNORECASE)
_ZONE = re.compile(r"\bzone\s+([a-z0-9]{1,3})\b", re.IGNORECASE)
_BAY = re.compile(r"\bbays?\s+(?:no\.?\s*)?(\d+)\b", re.IGNORECASE)
_TAG = re.compile(r"\b([a-z]{1,4}-\d{1,4}[a-z]?)\b", re.IGNORECASE)
_NEGATION = re.compile(r"(?:^|[^a-z])(?:not|never|no|n't)\s+$", re.IGNORECASE)


def _to_date(value: str) -> date | None:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None  # e.g. 2026-02-30 — a stated-but-impossible date is not a date
    return ts.date()


def _first_date(text: str) -> date | None:
    for pattern, build in (
        (_ISO_DATE, lambda m: m.group(1)),
        (_DAY_MONTH_YEAR, lambda m: f"{m.group(3)}-{m.group(1)}-{m.group(2)}"),
        (_MONTH_DAY_YEAR, lambda m: f"{m.group(3)}-{m.group(2)}-{m.group(1)}"),
    ):
        match = pattern.search(text)
        if match:
            parsed = _to_date(build(match))
            if parsed is not None:
                return parsed
    return None


def _negated_before(text: str, start: int) -> bool:
    return bool(_NEGATION.search(text[max(0, start - 12) : start]))


def _first_status(text: str) -> str | None:
    """First non-negated status phrase, exactly as written (case preserved)."""
    best: tuple[int, str] | None = None
    for pattern in _STATUS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if _negated_before(text, match.start()):
                continue
            phrase = re.sub(r"\s+", " ", match.group(0)).strip()
            if best is None or match.start() < best[0]:
                best = (match.start(), phrase)
    return best[1] if best else None


def _first_discipline(text: str) -> str | None:
    best: tuple[int, str] | None = None
    for word in _DISCIPLINES:
        match = re.search(rf"\b{word}\b", text, re.IGNORECASE)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), word.capitalize())
    return best[1] if best else None


def _first_location(text: str) -> str | None:
    """Area beats zone beats bay: the schedule keys on `area`, and "rack bay 1"
    is a position inside an area, not the area itself."""
    area = _AREA.search(text)
    if area:
        return f"Area {area.group(1).upper()}"
    zone = _ZONE.search(text)
    if zone:
        return f"Zone {zone.group(1).upper()}"
    bay = _BAY.search(text)
    if bay:
        return f"Bay {bay.group(1)}"
    return None


def _first_tag(text: str) -> str | None:
    match = _TAG.search(text)
    if not match:
        return None
    tag = match.group(1).upper()
    return tag if len(tag) >= 3 else None


def _description(text: str) -> str | None:
    """The report's own first sentence, quoted — never rewritten."""
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return None
    sentence = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0].strip(" ,;:")
    if len(sentence) <= MAX_DESCRIPTION:
        return sentence or None
    cut = sentence[:MAX_DESCRIPTION].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut or None


def extract(raw_text: str) -> dict[str, Any]:
    """Pattern extraction. Same keys (and null rules) as the LLM rung."""
    text = raw_text or ""
    progress = _PROGRESS.search(text)
    progress_value: float | None = None
    if progress:
        candidate = float(progress.group(1))
        progress_value = candidate if 0 <= candidate <= 100 else None

    quantity = _QUANTITY.search(text)
    return {
        "description": _description(text),
        "discipline": _first_discipline(text),
        "location": _first_location(text),
        "tag": _first_tag(text),
        "event_date": _first_date(text),
        "status": _first_status(text),
        "quantity": float(quantity.group(1)) if quantity else None,
        "progress": progress_value,
    }


def raw_response(fields: dict[str, Any]) -> str:
    """What was read, stored as the evidence for this rung of the ladder."""
    return json.dumps(
        {
            "extractor": MODEL,
            "fields": {k: (v.isoformat() if isinstance(v, date) else v) for k, v in fields.items()},
        },
        ensure_ascii=False,
    )
