"""Field-correction log endpoints.

Every reviewer edit to an extracted field is recorded (see the PATCH in
``routes.pipeline``). This read side lists those corrections so a future review UI
can surface fields the model got wrong — across all documents or one document.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models import FieldCorrectionRow
from app.schemas import FieldCorrection

router = APIRouter(prefix="/corrections", tags=["corrections"])


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
