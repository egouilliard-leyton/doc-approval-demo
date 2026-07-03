"""Template registry endpoints (Phase 0) + source upload / field catalogue (Phase 1).

Phase 1 Waves 3+4 add ``POST /suggest-mapping`` (AI/heuristic field binding, not
persisted) and ``POST /generate`` (fill the source PDF from a document's structured
extraction, optionally stamping a signature).
"""

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlmodel import Session, delete, select

from app import storage
from app.db import get_session
from app.models import (
    DocType,
    PipelineRun,
    Template,
    TemplateMode,
    TemplateRevision,
    _utcnow,
)
from app.pipeline.generation import (
    enumerate_form_fields,
    field_catalogue,
    generate_pdf,
    suggest_mapping,
)
from app.schemas import (
    FieldCatalogueEntry,
    GenerateResult,
    MappingSuggestResponse,
    TemplateCreate,
    TemplateDetail,
    TemplateFormField,
    TemplateSummary,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _to_detail(t: Template) -> TemplateDetail:
    source_url = storage.template_source_url(t.id) if t.source_file_id else None
    return TemplateDetail(**t.model_dump(), source_url=source_url)


@router.post("", response_model=TemplateDetail, status_code=201)
def create_template(
    body: TemplateCreate, session: Session = Depends(get_session)
) -> TemplateDetail:
    """Create a template in ``draft`` status."""
    tmpl = Template(**body.model_dump())
    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return _to_detail(tmpl)


@router.get("", response_model=list[TemplateSummary])
def list_templates(
    doc_type: DocType | None = Query(default=None),
    session: Session = Depends(get_session),
) -> list[Template]:
    """List templates, newest first; optionally filtered by document type."""
    query = select(Template)
    if doc_type is not None:
        query = query.where(Template.doc_type == doc_type)
    return session.exec(query.order_by(Template.updated_at.desc())).all()


@router.get("/{template_id}", response_model=TemplateDetail)
def get_template(template_id: str, session: Session = Depends(get_session)) -> TemplateDetail:
    """Template detail with its body, styles, and field/placeholder maps."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return _to_detail(tmpl)


@router.put("/{template_id}", response_model=TemplateDetail)
def update_template(
    template_id: str, body: TemplateUpdate, session: Session = Depends(get_session)
) -> TemplateDetail:
    """Partially update a template, snapshotting html/css before an edit that touches them."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    # Snapshot the PRE-update html/css so edits to the body/styles are revertible.
    if body.html_body is not None or body.css is not None:
        session.add(
            TemplateRevision(
                template_id=tmpl.id, html=tmpl.html_body, css=tmpl.css, note=body.revision_note
            )
        )

    # Wholesale replacement per field; JSON columns must be reassigned (SQLAlchemy
    # doesn't detect in-place mutation of a dict/list).
    for attr in ("name", "html_body", "css", "form_field_map", "placeholder_map",
                 "output_formats", "status"):
        value = getattr(body, attr)
        if value is not None:
            setattr(tmpl, attr, value)
    tmpl.updated_at = _utcnow()

    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return _to_detail(tmpl)


@router.delete("/{template_id}", status_code=204)
def delete_template(template_id: str, session: Session = Depends(get_session)) -> None:
    """Permanently remove a template, its revision history, and on-disk files.

    The TemplateRevision -> Template foreign key has no DB cascade configured, so
    the revisions are deleted explicitly before the template.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    session.exec(delete(TemplateRevision).where(TemplateRevision.template_id == template_id))
    session.delete(tmpl)
    session.commit()

    storage.delete_template_dir(template_id)


@router.post("/{template_id}/source", response_model=TemplateDetail)
async def upload_template_source(
    template_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
) -> TemplateDetail:
    """Attach a source PDF, enumerate its AcroForm, and set the template's mode.

    A PDF carrying an AcroForm switches the template to ``form_fill`` (its fields are
    persisted for the mapper); one without stays ``rich_html``. A non-PDF is a 415;
    an unreadable PDF is a 422 (mirroring the document upload path).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    try:
        ext, mime = storage.detect_type(file.filename or "")
    except storage.UnsupportedFileType:
        ext, mime = "", ""
    if mime != "application/pdf":
        raise HTTPException(status_code=415, detail="Template source must be a PDF.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    source = storage.save_template_source(tmpl.id, ext, content)
    try:
        has_acroform, fields = enumerate_form_fields(source)
    except Exception as exc:  # corrupt/unreadable PDF
        raise HTTPException(
            status_code=422, detail="Could not read the PDF; it may be corrupt or unsupported."
        ) from exc

    tmpl.source_file_id = tmpl.id
    tmpl.mode = TemplateMode.form_fill if has_acroform else TemplateMode.rich_html
    tmpl.form_fields = [f.model_dump() for f in fields]
    tmpl.form_field_map = {}  # a new source invalidates any prior binding
    tmpl.updated_at = _utcnow()

    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return _to_detail(tmpl)


@router.get("/{template_id}/catalogue", response_model=list[FieldCatalogueEntry])
def get_template_catalogue(
    template_id: str, session: Session = Depends(get_session)
) -> list[FieldCatalogueEntry]:
    """The bindable field catalogue for the template's document type."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return field_catalogue(tmpl.doc_type)


@router.post("/{template_id}/suggest-mapping", response_model=MappingSuggestResponse)
async def suggest_template_mapping(
    template_id: str,
    provider: str = Query(default=""),
    session: Session = Depends(get_session),
) -> MappingSuggestResponse:
    """Suggest a catalogue binding per PDF form field (AI, degrading to a heuristic).

    Not persisted — the frontend merges the picks it accepts and saves them via
    ``PUT /templates/{id}`` (``form_field_map``). 404 if the template is missing or
    carries no enumerated form fields.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if not tmpl.form_fields:
        raise HTTPException(status_code=404, detail="Template has no form fields to map.")

    form_fields = [TemplateFormField(**f) for f in tmpl.form_fields]
    catalogue = field_catalogue(tmpl.doc_type)
    try:
        suggestions = await asyncio.to_thread(
            suggest_mapping, tmpl.doc_type, form_fields, catalogue, provider
        )
    except ValueError as exc:
        # An unknown ``provider`` query value — surface as a clean 400 rather than
        # letting it escape as an unhandled 500 (mirrors pipeline._run_stage).
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Reflect the provider that actually produced the picks: any "ai" source means the
    # LLM ran; otherwise every field came from the offline heuristic (the mock fallback).
    provider_used = "llm" if any(s.source == "ai" for s in suggestions.values()) else "mock"
    return MappingSuggestResponse(suggestions=suggestions, provider_used=provider_used)


@router.post("/{template_id}/generate", response_model=GenerateResult, status_code=201)
async def generate_template_output(
    template_id: str,
    document_id: str = Query(...),
    flatten: bool = Query(default=True),
    signature_image: UploadFile | None = File(default=None),
    session: Session = Depends(get_session),
) -> GenerateResult:
    """Fill the template's source PDF from a document's structured extraction.

    Requires a ``form_fill`` template with an uploaded source, and a document whose
    latest pipeline run holds a ``structure`` stage result. An optional
    ``signature_image`` is stamped onto any bound signature fields.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if tmpl.mode != TemplateMode.form_fill or not tmpl.source_file_id:
        raise HTTPException(
            status_code=400, detail="Template is not a form-fill template with a source PDF."
        )

    run = session.exec(
        select(PipelineRun)
        .where(PipelineRun.document_id == document_id)
        .order_by(PipelineRun.created_at.desc())
    ).first()
    structure = (run.stage_results.get("structure") if run else None) or None
    fields = structure.get("fields") if isinstance(structure, dict) else None
    if not fields:
        raise HTTPException(
            status_code=400, detail="Document has no structured extraction yet."
        )

    signature_bytes = await signature_image.read() if signature_image is not None else None

    outcome = await asyncio.to_thread(generate_pdf, tmpl, fields, signature_bytes, flatten)

    return GenerateResult(
        output_url=storage.template_output_url(tmpl.id, outcome.output_id),
        output_id=outcome.output_id,
        filled_fields=outcome.filled,
        skipped_fields=outcome.skipped,
        signature_stamped=outcome.signature_stamped,
        warnings=outcome.warnings,
    )
