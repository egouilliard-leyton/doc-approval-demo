"""Configurable case-type CRUD endpoints (Phase 1).

The case-type registry lives in :mod:`app.case_types` and serves both the built-in
``ap_match`` type (resolved from code, read-only here) and custom types (authored
through these endpoints and rebuilt from their stored JSON rows). Unlike doc types, a
case-type definition carries no code, so a custom type is persisted and re-registered
verbatim with no validation of embedded callables. No PUT/preview in Phase 1.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app import case_types
from app.db import get_session
from app.models import Case, CaseTypeDefinitionRow
from app.schemas import CaseTypeCreate, CaseTypeResponse

router = APIRouter(prefix="/case-types", tags=["case-types"])


@router.get("", response_model=list[CaseTypeResponse])
def list_case_types(session: Session = Depends(get_session)) -> list[CaseTypeDefinitionRow]:
    """List every case type (built-in + custom), oldest first."""
    return session.exec(
        select(CaseTypeDefinitionRow).order_by(CaseTypeDefinitionRow.created_at)
    ).all()


@router.get("/{name}", response_model=CaseTypeResponse)
def get_case_type(name: str, session: Session = Depends(get_session)) -> CaseTypeDefinitionRow:
    """Return one case type's definition, or 404 if it doesn't exist."""
    row = session.get(CaseTypeDefinitionRow, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case type '{name}' not found.")
    return row


@router.post("", response_model=CaseTypeResponse, status_code=201)
def create_case_type(
    body: CaseTypeCreate, session: Session = Depends(get_session)
) -> CaseTypeDefinitionRow:
    """Create a custom case type, persist it, and register it."""
    if session.get(CaseTypeDefinitionRow, body.name) is not None:
        raise HTTPException(status_code=409, detail=f"Case type '{body.name}' already exists.")

    row = CaseTypeDefinitionRow(
        name=body.name,
        # A missing label falls back to the name so a type never renders blank.
        label=body.label.strip() or body.name,
        icon=body.icon,
        members=[m.model_dump() for m in body.members],
        canonical_fields=dict(body.canonical_fields),
        builtin=False,
        version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    case_types.register_from_row(row)
    return row


@router.delete("/{name}", status_code=204)
def delete_case_type(name: str, session: Session = Depends(get_session)) -> None:
    """Delete a custom case type (built-ins read-only; 409 if still in use)."""
    row = session.get(CaseTypeDefinitionRow, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case type '{name}' not found.")
    if row.builtin:
        raise HTTPException(status_code=403, detail="Built-in types are read-only.")

    in_use = session.exec(select(Case).where(Case.case_type == name)).all()
    if in_use:
        raise HTTPException(
            status_code=409, detail=f"{len(in_use)} case(s) still use this type."
        )

    session.delete(row)
    session.commit()
    case_types.invalidate(name)
