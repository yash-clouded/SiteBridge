"""Phase 3: field intake — accept text and file uploads, store raw input
plus a pointer to its origin as evidence.

Voice is transcribed upstream (speech-to-text) and submitted through the
text endpoint with source_type="voice" and a timestamp pointer — this
service never sees audio.

Every submission is stored verbatim in `field_reports`; downstream
records (Phase 4+ execution events) reference it, so the whole chain
traces back to the original raw input and its pointer.

Multilingual intake: when the submitter declares a language (or we detect
one), the English rendering is stored beside `raw_text` and it — not the
raw text — is what extraction reads. Translation never blocks a submission.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import ExecutionEvent, FieldReport, MatchCandidate, Project, Role, User, WbsNode
from ..schemas import ReportListOut, ReportOut, TextReportRequest
from ..security import get_current_user, require_roles, roles_for
from ..services.pipeline import auto_process
from ..services.translate import translate_report

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["intake"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
TEXT_EXTENSIONS = {".txt", ".csv", ".log"}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}
PDF_EXTENSIONS = {".pdf"}
SUBMIT_SOURCES = {"text", "voice", "dpr"}


def _require_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found.")
    return project


def _store(
    db: Session,
    *,
    project_id: int,
    user_id: int,
    source_type: str,
    raw_text: str,
    filename: str | None,
    pointer: dict,
) -> FieldReport:
    report = FieldReport(
        project_id=project_id,
        user_id=user_id,
        source_type=source_type,
        raw_text=raw_text,
        filename=filename,
        pointer=pointer,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _finish(db: Session, report: FieldReport, language: str | None = None) -> FieldReport:
    """After the raw evidence is committed: translate (if configured), then
    kick off Phases 4-6.

    The submission itself must never fail because the AI layer is
    unavailable: `translate_report` and `auto_process` both swallow their
    errors and only record them on the report.
    """
    # Multilingual intake: English text for the pipeline, raw text untouched.
    translate_report(db, report, language=language)
    db.refresh(report)
    if settings.auto_extract_on_intake:
        auto_process(db, report)
        db.refresh(report)
    return report


@router.post("/reports/text", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def submit_text_report(
    payload: TextReportRequest,
    db: Session = Depends(get_db),
    user: User = Depends(roles_for("submit")),
) -> FieldReport:
    """Accept a typed report, a voice transcript, or a DPR note."""
    raw = payload.raw_text.strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Report text is empty.")
    if payload.source_type not in SUBMIT_SOURCES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"source_type must be one of {sorted(SUBMIT_SOURCES)}.",
        )
    _require_project(db, payload.project_id)
    return _finish(
        db,
        _store(
            db,
            project_id=payload.project_id,
            user_id=user.id,
            source_type=payload.source_type,
            raw_text=raw,
            filename=None,
            pointer=payload.pointer or {},
        ),
        language=payload.language,
    )


def _extract_pdf(content: bytes) -> tuple[str, dict]:
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise ValueError("encrypted")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF is encrypted.") from exc
    parts: list[str] = []
    offsets: list[dict] = []
    pos = 0
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if parts:
            pos += 2  # "\n\n" join separator
        offsets.append({"page": i, "start": pos, "end": pos + len(text)})
        parts.append(text)
        pos += len(text)
    raw = "\n\n".join(parts)
    if not raw.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No extractable text in the PDF (scanned images need OCR upstream).",
        )
    return raw, {"pages": [o["page"] for o in offsets], "page_offsets": offsets}


def _extract_excel(content: bytes) -> tuple[str, dict]:
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=str)
    if not sheets:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Workbook has no sheets.")
    multi = len(sheets) > 1
    parts: list[str] = []
    sheet_rows: list[dict] = []
    for sheet_name, df in sheets.items():
        lines: list[str] = []
        for idx, row in df.iterrows():
            cells = [str(v)[:200] for v in row.tolist() if v is not None and str(v) != "nan"]
            if cells:
                # row number in the original sheet (1-based, header included)
                row_no = int(idx) + 1
                prefix = f"{sheet_name}!R{row_no}: " if multi else f"R{row_no}: "
                lines.append(prefix + " | ".join(cells[:20]))
        if not lines:
            continue
        # every tab is evidence — a multi-tab DPR must not lose its sheets
        sheet_rows.append({"sheet": str(sheet_name), "start": 1, "end": int(len(df))})
        parts.extend(lines)
    if not parts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Spreadsheet contains no values.")
    raw = "\n".join(parts)
    if multi:
        return raw, {"sheets": sheet_rows}
    only = sheet_rows[0]
    return raw, {"sheet": only["sheet"], "rows": {"start": only["start"], "end": only["end"]}}


def _extract_text_file(content: bytes) -> tuple[str, dict]:
    raw = content.decode("utf-8", errors="replace")
    if not raw.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty.")
    return raw, {"chars": len(raw)}


@router.post("/reports/file", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def submit_file_report(
    file: UploadFile = File(...),
    project_id: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(roles_for("submit")),
) -> FieldReport:
    """Accept a PDF / Excel / text file and store it with a pointer
    (page / sheet+rows / char count) as evidence."""
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (10 MB max).")
    _require_project(db, project_id)

    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext in PDF_EXTENSIONS:
        raw_text, pointer = _extract_pdf(content)
        source_type = "pdf"
    elif ext in EXCEL_EXTENSIONS:
        try:
            raw_text, pointer = _extract_excel(content)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 — corrupt workbook etc.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Could not read spreadsheet: {exc}"
            ) from exc
        source_type = "excel"
    elif ext in TEXT_EXTENSIONS:
        raw_text, pointer = _extract_text_file(content)
        source_type = "txt"
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported file type '{ext}'. Allowed: PDF, Excel, txt, csv.",
        )

    return _finish(
        db,
        _store(
            db,
            project_id=project_id,
            user_id=user.id,
            source_type=source_type,
            raw_text=raw_text,
            filename=filename,
            pointer=pointer,
        ),
    )


@router.get("/reports", response_model=list[ReportListOut])
def list_reports(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ReportListOut]:
    """Field users see their own submissions; planners/PM see all.

    Phase 10: each row carries the outcome — extraction rung (LLM model or
    heuristic), review status, and the approved activity when there is one —
    so a field user closes the loop on what happened to their report.
    """
    query = select(FieldReport).order_by(FieldReport.created_at.desc(), FieldReport.id.desc())
    if user.role == Role.FIELD.value:
        query = query.where(FieldReport.user_id == user.id)
    if project_id is not None:
        query = query.where(FieldReport.project_id == project_id)
    reports = list(db.scalars(query.limit(200)).all())
    if not reports:
        return []

    report_ids = [r.id for r in reports]
    events = {
        event.field_report_id: event
        for event in db.scalars(
            select(ExecutionEvent).where(ExecutionEvent.field_report_id.in_(report_ids))
        ).all()
    }
    mapped: dict[int, str] = {}
    for candidate, node in db.execute(
        select(MatchCandidate, WbsNode)
        .join(WbsNode, WbsNode.id == MatchCandidate.wbs_node_id)
        .where(
            MatchCandidate.field_report_id.in_(report_ids),
            MatchCandidate.approved_at.is_not(None),
        )
    ).all():
        mapped[candidate.field_report_id] = f"{node.code} — {node.name}"

    out: list[ReportListOut] = []
    for report in reports:
        event = events.get(report.id)
        out.append(
            ReportListOut(
                **ReportOut.model_validate(report).model_dump(),
                review_status=event.review_status if event else None,
                extracted_by=event.model if event else None,
                mapped_activity=mapped.get(report.id),
            )
        )
    return out
