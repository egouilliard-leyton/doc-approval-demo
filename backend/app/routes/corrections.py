"""Field-correction log endpoints.

Every reviewer edit to an extracted field is recorded (see the PATCH in
``routes.pipeline``). This read side lists those corrections so a future review UI
can surface fields the model got wrong — across all documents or one document.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlmodel import Session, select

from app.db import get_session
from app.models import FieldCorrectionRow
from app.schemas import FieldCorrection

router = APIRouter(prefix="/corrections", tags=["corrections"])


def _ocr_text_for(session: Session, document_id: str) -> str | None:
    """Best-effort OCR full text a document's structure stage was built from.

    Joins latest run -> ``structure.ocr_engine`` -> ``ocr[engine].full_text``. Any
    missing/partial run yields ``None`` rather than raising, so export never 500s.
    """
    from app.routes.pipeline import _latest_run

    try:
        run = _latest_run(session, document_id)
        if run is None:
            return None
        structure = run.stage_results.get("structure") or {}
        engine = structure.get("ocr_engine")
        ocr = (run.stage_results.get("ocr") or {}).get(engine) or {}
        return ocr.get("full_text")
    except Exception:  # noqa: BLE001 — never fail the export over one document's OCR
        return None


@router.get("", response_model=list[FieldCorrection])
def list_corrections(
    document_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[FieldCorrectionRow]:
    """All logged field corrections, newest first; optionally scoped to one document."""
    stmt = select(FieldCorrectionRow)
    if document_id:
        stmt = stmt.where(FieldCorrectionRow.document_id == document_id)
    stmt = stmt.order_by(FieldCorrectionRow.updated_at.desc())
    return session.exec(stmt).all()


@router.get("/export")
def export_corrections(
    doc_type: str | None = Query(default=None),
    shape: Literal["raw", "examples"] = Query(default="raw"),
    include_text: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> Response:
    """Export the correction log as newline-delimited JSON (JSONL).

    ``shape="raw"`` emits one line per correction (newest first). ``shape="examples"``
    groups by document into one training-style row each, with the reviewer-approved
    ``fields`` and (when ``include_text``) the OCR text they were read from.
    """
    stmt = select(FieldCorrectionRow)
    if doc_type:
        stmt = stmt.where(FieldCorrectionRow.doc_type == doc_type)
    stmt = stmt.order_by(FieldCorrectionRow.updated_at.desc())
    corrections = session.exec(stmt).all()

    records: list[dict] = []
    if shape == "raw":
        for c in corrections:
            records.append(
                {
                    "document_id": c.document_id,
                    "doc_type": c.doc_type,
                    "field_path": c.field_path,
                    "original_value": c.original_value,
                    "new_value": c.new_value,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                }
            )
    else:  # examples: one row per document (newest-first order preserved)
        docs: dict[str, dict] = {}
        for c in corrections:
            entry = docs.get(c.document_id)
            if entry is None:
                entry = {
                    "document_id": c.document_id,
                    "doc_type": c.doc_type,
                    "fields": {},
                    "corrected_at": c.updated_at,
                }
                docs[c.document_id] = entry
            entry["fields"].setdefault(c.field_path, c.new_value)
            if c.updated_at > entry["corrected_at"]:
                entry["corrected_at"] = c.updated_at
        for entry in docs.values():
            if include_text:
                entry["ocr_text"] = _ocr_text_for(session, entry["document_id"])
            records.append(entry)

    body = "\n".join(json.dumps(rec, default=str) for rec in records)
    suffix = f"-{doc_type}" if doc_type else ""
    filename = f"corrections-{shape}{suffix}.jsonl"
    return Response(
        content=body.encode(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
