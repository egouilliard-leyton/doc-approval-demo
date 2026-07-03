"""Template registry endpoints (Phase 0) + source upload / field catalogue (Phase 1).

Phase 1 Waves 3+4 add ``POST /suggest-mapping`` (AI/heuristic field binding, not
persisted) and ``POST /generate`` (fill the source PDF from a document's structured
extraction, optionally stamping a signature).
"""

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session, delete, select
from starlette.concurrency import iterate_in_threadpool

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
    AUTHORING_PROVIDERS,
    apply_template_update,
    convert_docx,
    convert_pdf,
    enumerate_form_fields,
    field_catalogue,
    generate_pdf,
    generate_rich,
    run_authoring_agent,
    suggest_mapping,
)
from app.schemas import (
    AgentEvent,
    AgentRequest,
    FieldCatalogueEntry,
    GenerateOutputFile,
    GenerateResult,
    MappingSuggestResponse,
    TemplateCreate,
    TemplateDetail,
    TemplateFormField,
    TemplateRevisionInfo,
    TemplateSummary,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _to_detail(t: Template) -> TemplateDetail:
    source_url = (
        storage.template_source_url(t.id, t.source_ext or ".pdf") if t.source_file_id else None
    )
    return TemplateDetail(**t.model_dump(), source_url=source_url)


def _load_structured_fields(session: Session, document_id: str) -> dict:
    """Return a document's latest ``structure`` stage ``fields`` blob, or 400 if absent.

    Shared by both generation modes: the newest pipeline run must carry a structuring
    result, otherwise there is nothing to bind/fill from.
    """
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
    return fields


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

    tmpl = apply_template_update(session, tmpl, body)
    return _to_detail(tmpl)


@router.get("/{template_id}/revisions", response_model=list[TemplateRevisionInfo])
def list_template_revisions(
    template_id: str, session: Session = Depends(get_session)
) -> list[TemplateRevision]:
    """The template's pre-update html/css snapshots, newest first. 404 if it's missing."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return session.exec(
        select(TemplateRevision)
        .where(TemplateRevision.template_id == template_id)
        .order_by(TemplateRevision.created_at.desc())
    ).all()


@router.post("/{template_id}/agent")
async def run_template_agent(
    template_id: str, body: AgentRequest, session: Session = Depends(get_session)
) -> StreamingResponse:
    """Stream the authoring agent editing the template's HTML/CSS (Server-Sent Events).

    Validates the template exists (404) and the provider up front (400 on an unknown one,
    mirroring the mapper route), then hands off to the engine in a threadpool. The request
    session is only used for that validation — the engine opens its own sessions, because
    FastAPI tears this one down before the stream drains. Each ``data:`` line is one
    :class:`AgentEvent`; the stream always ends with a ``done`` event.
    """
    if session.get(Template, template_id) is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if body.provider and body.provider not in AUTHORING_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown authoring provider '{body.provider}'. "
                f"Available: {', '.join(sorted(AUTHORING_PROVIDERS))}"
            ),
        )

    async def _stream():
        try:
            async for event in iterate_in_threadpool(
                run_authoring_agent(template_id, body, body.provider)
            ):
                yield f"data: {event.model_dump_json()}\n\n".encode()
        except ValueError as exc:  # unknown provider slipped through -> emit + close cleanly
            yield f"data: {AgentEvent(type='error', message=str(exc)).model_dump_json()}\n\n".encode()
            yield f"data: {AgentEvent(type='done').model_dump_json()}\n\n".encode()

    return StreamingResponse(_stream(), media_type="text/event-stream")


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
    """Attach a source (PDF or DOCX) and set the template's mode from what it holds.

    A PDF carrying an AcroForm switches the template to ``form_fill`` (its fields are
    persisted for the mapper). A PDF without a form, or any DOCX, becomes ``rich_html``
    and is converted to an editable HTML body + baseline stylesheet. A non-PDF/DOCX is a
    415; an unreadable source is a 422 (mirroring the document upload path).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    try:
        ext, mime = storage.detect_template_source_type(file.filename or "")
    except storage.UnsupportedFileType:
        raise HTTPException(
            status_code=415, detail="Template source must be a PDF or DOCX."
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    source = storage.save_template_source(tmpl.id, ext, content)

    mode = TemplateMode.rich_html
    form_fields: list = []
    html_body: str | None = None
    css: str | None = None
    try:
        if mime == "application/pdf":
            has_acroform, fields = enumerate_form_fields(source)
            if has_acroform:
                mode = TemplateMode.form_fill
                form_fields = [f.model_dump() for f in fields]
            else:
                converted = await asyncio.to_thread(convert_pdf, source)
                html_body, css = converted.html, converted.css
        else:  # DOCX
            converted = await asyncio.to_thread(convert_docx, content)
            html_body, css = converted.html, converted.css
    except Exception as exc:  # corrupt/unreadable source or conversion failure
        raise HTTPException(
            status_code=422,
            detail="Could not read the source; it may be corrupt or unsupported.",
        ) from exc

    tmpl.source_file_id = tmpl.id
    tmpl.source_ext = ext
    tmpl.mode = mode
    tmpl.form_fields = form_fields
    tmpl.form_field_map = {}  # a new source invalidates any prior binding
    if mode == TemplateMode.rich_html:
        tmpl.html_body = html_body
        tmpl.css = css
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
    """Generate the template's output from a document's structured extraction.

    A ``form_fill`` template fills its source PDF's AcroForm; a ``rich_html`` template
    binds its HTML body and renders it to each configured output format. Both require a
    document whose latest pipeline run holds a ``structure`` stage result. An optional
    ``signature_image`` is stamped onto any bound signature field/placeholder.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    fields = _load_structured_fields(session, document_id)
    signature_bytes = await signature_image.read() if signature_image is not None else None

    if tmpl.mode == TemplateMode.form_fill:
        if not tmpl.source_file_id:
            raise HTTPException(
                status_code=400,
                detail="Template is not a form-fill template with a source PDF.",
            )
        outcome = await asyncio.to_thread(generate_pdf, tmpl, fields, signature_bytes, flatten)
        output_url = storage.template_output_url(tmpl.id, outcome.output_id)
        return GenerateResult(
            output_url=output_url,
            output_id=outcome.output_id,
            filled_fields=outcome.filled,
            skipped_fields=outcome.skipped,
            signature_stamped=outcome.signature_stamped,
            warnings=outcome.warnings,
            outputs=[
                GenerateOutputFile(format="pdf", output_id=outcome.output_id, output_url=output_url)
            ],
        )

    # rich_html: bind the HTML body, render every configured format, persist each.
    if not tmpl.html_body:
        raise HTTPException(status_code=400, detail="Template has no HTML body yet.")

    rich = await asyncio.to_thread(
        generate_rich, tmpl, fields, signature_bytes, tmpl.output_formats or ["pdf"]
    )
    if not rich.rendered:
        # Every format failed (e.g. no renderer available) — nothing to return.
        raise HTTPException(status_code=503, detail="; ".join(rich.warnings))

    outputs: list[GenerateOutputFile] = []
    for rf in rich.rendered:
        storage.save_template_output(tmpl.id, rf.output_id, rf.content, ext=f".{rf.format}")
        outputs.append(
            GenerateOutputFile(
                format=rf.format,
                output_id=rf.output_id,
                output_url=storage.template_output_url(tmpl.id, rf.output_id, ext=f".{rf.format}"),
            )
        )

    # The PDF is the primary output when present, else the first rendered file.
    primary = next((o for o in outputs if o.format == "pdf"), outputs[0])
    return GenerateResult(
        output_url=primary.output_url,
        output_id=primary.output_id,
        filled_fields=rich.filled,
        skipped_fields=rich.skipped,
        signature_stamped=rich.signature_stamped,
        warnings=rich.warnings,
        outputs=outputs,
    )
