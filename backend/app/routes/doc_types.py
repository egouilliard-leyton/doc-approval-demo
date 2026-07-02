"""Configurable doc-type CRUD + preview endpoints (Phase 3 Wave 2).

The document-type registry lives in :mod:`app.doc_types` and serves both built-in
types (invoice, contract — resolved from code, read-only here) and custom types
(authored through these endpoints and rebuilt from their stored JSON definitions).

Custom types NEVER carry code: every create/update runs the pure validators in
:mod:`app.serialization`, which reject any non-serializable rule kind. The build step
(``register_from_row``) re-raises any failure as ``ValueError`` so it maps to a 422
rather than a 500 — the CRUD and preview paths only ever surface 4xx errors.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app import doc_types
from app.db import get_session
from app.models import Document, DocTypeDefinitionRow, _utcnow
from app.schemas import (
    Check,
    DocTypeCreate,
    DocTypePreviewRequest,
    DocTypePreviewResponse,
    DocTypeResponse,
    DocTypeUpdate,
)
from app.serialization import (
    validate_custom_extraction_dict,
    validate_custom_rule_dict,
)

router = APIRouter(prefix="/doc-types", tags=["doc-types"])


def _declared_field_names(extraction_definition: dict) -> set[str]:
    """Top-level field names declared in an extraction definition."""
    return {
        f["name"]
        for f in extraction_definition.get("fields", [])
        if isinstance(f, dict) and isinstance(f.get("name"), str)
    }


def _validate_or_422(extraction_definition: dict, rule_definition: dict) -> None:
    """Run both pure validators; raise a 422 with the joined messages on any error."""
    errors = validate_custom_extraction_dict(extraction_definition)
    errors += validate_custom_rule_dict(
        rule_definition, declared_field_names=_declared_field_names(extraction_definition)
    )
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))


@router.get("", response_model=list[DocTypeResponse])
def list_doc_types(session: Session = Depends(get_session)) -> list[DocTypeDefinitionRow]:
    """List every document type (built-in + custom), oldest first."""
    return session.exec(
        select(DocTypeDefinitionRow).order_by(DocTypeDefinitionRow.created_at)
    ).all()


@router.get("/{name}", response_model=DocTypeResponse)
def get_doc_type(name: str, session: Session = Depends(get_session)) -> DocTypeDefinitionRow:
    """Return one document type's definition, or 404 if it doesn't exist."""
    row = session.get(DocTypeDefinitionRow, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Doc type '{name}' not found.")
    return row


@router.post("", response_model=DocTypeResponse, status_code=201)
def create_doc_type(
    body: DocTypeCreate, session: Session = Depends(get_session)
) -> DocTypeDefinitionRow:
    """Create a custom document type, validate it, persist it, and register it."""
    if session.get(DocTypeDefinitionRow, body.name) is not None:
        raise HTTPException(status_code=409, detail=f"Doc type '{body.name}' already exists.")

    _validate_or_422(body.extraction_definition, body.rule_definition)

    row = DocTypeDefinitionRow(
        name=body.name,
        # A missing label falls back to the name so a type never renders blank.
        label=body.label.strip() or body.name,
        icon=body.icon,
        extraction_definition=body.extraction_definition,
        rule_definition=body.rule_definition,
        citation_paths=list(body.citation_paths),
        builtin=False,
        version=1,
    )
    session.add(row)
    session.commit()
    session.refresh(row)

    try:
        doc_types.register_from_row(row)
    except ValueError as exc:
        # The stored definition is structurally valid but couldn't be built — roll the
        # row back so the registry and DB stay consistent, and surface a 422.
        session.delete(row)
        session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return row


@router.put("/{name}", response_model=DocTypeResponse)
def update_doc_type(
    name: str, body: DocTypeUpdate, session: Session = Depends(get_session)
) -> DocTypeDefinitionRow:
    """Full-replace a custom document type's definition (built-ins are read-only)."""
    row = session.get(DocTypeDefinitionRow, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Doc type '{name}' not found.")
    if row.builtin:
        raise HTTPException(status_code=403, detail="Built-in types are read-only.")

    _validate_or_422(body.extraction_definition, body.rule_definition)

    # Snapshot the prior definition so a failed rebuild can roll the row back.
    prior = row.model_dump()

    row.label = body.label.strip() or name
    row.icon = body.icon
    row.extraction_definition = body.extraction_definition
    row.rule_definition = body.rule_definition
    row.citation_paths = list(body.citation_paths)
    row.version += 1
    row.updated_at = _utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)

    doc_types.invalidate(name)
    try:
        doc_types.register_from_row(row)
    except ValueError as exc:
        # Restore the prior definition and re-register it so the live registry keeps
        # serving the last-known-good build.
        for key, value in prior.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()
        session.refresh(row)
        try:
            doc_types.register_from_row(row)
        except ValueError:
            pass
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return row


@router.delete("/{name}", status_code=204)
def delete_doc_type(name: str, session: Session = Depends(get_session)) -> None:
    """Delete a custom document type (built-ins read-only; 409 if still in use)."""
    row = session.get(DocTypeDefinitionRow, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Doc type '{name}' not found.")
    if row.builtin:
        raise HTTPException(status_code=403, detail="Built-in types are read-only.")

    in_use = session.exec(select(Document).where(Document.doc_type == name)).all()
    if in_use:
        raise HTTPException(
            status_code=409, detail=f"{len(in_use)} document(s) still use this type."
        )

    session.delete(row)
    session.commit()
    doc_types.invalidate(name)


@router.post("/{name}/preview", response_model=DocTypePreviewResponse)
def preview_doc_type(
    name: str, body: DocTypePreviewRequest, session: Session = Depends(get_session)
) -> DocTypePreviewResponse:
    """Run structuring + rules over ad-hoc sample text for a registered doc type.

    Builds a synthetic single-page OCR result from ``sample_text`` and a transient
    in-memory ``Document`` (never persisted), structures it, then runs the doc type's
    rule set over the extracted fields.

    NOTE on the mock provider: with ``provider="mock"`` the structurer only emits
    meaningful fields for the built-in ``invoice`` / ``contract`` types (its mock
    extractions are hard-coded for those). To preview a CUSTOM type's extraction you
    must pass a provider that hits the live extractor (``provider="langextract"``),
    which needs ``OPENROUTER_API_KEY``. The rule-evaluation half runs regardless.
    """
    if not doc_types.is_registered(name):
        raise HTTPException(status_code=404, detail=f"Doc type '{name}' is not registered.")

    # Local imports keep this module import-light and avoid pulling the pipeline in at
    # module load (mirrors the registry's lazy-import discipline).
    from app.models import DocumentStatus
    from app.pipeline.structuring import run_structuring
    from app.rules import DecisionContext
    from app.schemas import OCRPage, OCRResult

    try:
        ocr_result = OCRResult(
            document_id="preview",
            status=DocumentStatus.ocr_done,
            engine_name="preview",
            engine_version="1",
            device="cpu",
            full_text=body.sample_text,
            pages=[
                OCRPage(page=1, text=body.sample_text, blocks=[], tables=[])
            ],
        )
        doc = Document(id="preview", filename="preview", mime="text/plain")
        structured = run_structuring(doc, ocr_result, name, provider=body.provider)

        ruleset = doc_types.get_ruleset(name)
        ctx = DecisionContext(extraction_confidence=structured.extraction_confidence)
        checks: list[Check] = ruleset(structured.fields, ctx)
    except Exception as exc:  # noqa: BLE001 — never 500 from preview; map to 422
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return DocTypePreviewResponse(
        doc_type=name,
        fields=structured.fields,
        extraction_confidence=structured.extraction_confidence,
        checks=checks,
        warnings=list(structured.warnings),
    )
