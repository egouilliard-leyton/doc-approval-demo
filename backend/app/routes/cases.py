"""Case CRUD + document-association endpoints (Phase 1).

A case groups N documents for cross-document reasoning. This module owns the case
lifecycle (create / list / get / delete) and the association of documents with cases.
The read (``GET``) side delegates to :func:`app.case_assembly.assemble_case`, which
collates each member document's persisted structured result — no reasoning happens yet
(that lands in Phase 2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, delete, select

from app import case_types
from app.case_assembly import assemble_case
from app.db import get_session
from app.models import Case, CaseMembership, Document
from app.schemas import CaseCreate, CaseDetail, CaseSummary

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("", response_model=CaseDetail, status_code=201)
def create_case(body: CaseCreate, session: Session = Depends(get_session)) -> CaseDetail:
    """Create a case: an open pile, or one bound to a registered case type."""
    if body.case_type is not None and not case_types.is_registered(body.case_type):
        raise HTTPException(status_code=422, detail=f"Unknown case_type '{body.case_type}'")

    case = Case(case_type=body.case_type, label=body.label)
    session.add(case)
    session.commit()
    session.refresh(case)
    return assemble_case(session, case)


@router.get("", response_model=list[CaseSummary])
def list_cases(session: Session = Depends(get_session)) -> list[Case]:
    """List cases, newest first."""
    return session.exec(select(Case).order_by(Case.created_at.desc())).all()


@router.get("/{case_id}", response_model=CaseDetail)
def get_case(case_id: str, session: Session = Depends(get_session)) -> CaseDetail:
    """Return a case with its member documents + their grouped structured results."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    return assemble_case(session, case)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: str, session: Session = Depends(get_session)) -> None:
    """Delete a case. Its documents survive (become caseless); only links are removed."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")

    session.exec(delete(CaseMembership).where(CaseMembership.case_id == case_id))
    session.delete(case)
    session.commit()


@router.post("/{case_id}/documents/{doc_id}", response_model=CaseDetail)
def add_document_to_case(
    case_id: str, doc_id: str, session: Session = Depends(get_session)
) -> CaseDetail:
    """Associate a document with a case (silently reassigning it from any prior case)."""
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found.")
    if session.get(Document, doc_id) is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Upsert by document_id (the membership PK): a document belongs to at most one case,
    # so re-associating one already in another case silently reassigns it.
    membership = session.get(CaseMembership, doc_id)
    if membership is None:
        session.add(CaseMembership(document_id=doc_id, case_id=case_id))
    else:
        membership.case_id = case_id
        session.add(membership)
    session.commit()

    return assemble_case(session, case)


@router.delete("/{case_id}/documents/{doc_id}", status_code=204)
def remove_document_from_case(
    case_id: str, doc_id: str, session: Session = Depends(get_session)
) -> None:
    """Detach a document from a case (the document survives, becomes caseless)."""
    membership = session.get(CaseMembership, doc_id)
    if membership is None or membership.case_id != case_id:
        raise HTTPException(status_code=404, detail="Document is not a member of this case.")

    session.delete(membership)
    session.commit()
