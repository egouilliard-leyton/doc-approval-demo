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
from app.config import settings
from app.db import get_session
from app.models import (
    DocType,
    PipelineRun,
    Template,
    TemplateMode,
    TemplateRevision,
    _new_id,
    _utcnow,
)
from app.pipeline.generation import (
    AUTHORING_PROVIDERS,
    QA_PROVIDERS,
    RenderUnavailableError,
    apply_template_update,
    convert_docx,
    convert_pdf,
    convert_to_pdf,
    enumerate_form_fields,
    enumerate_workbook_sheets,
    field_catalogue,
    fill_spreadsheet,
    generate_pdf,
    generate_rich,
    lint_template,
    list_field_catalogue,
    read_computed_grid,
    read_template_grid,
    recompute_workbook,
    run_authoring_agent,
    run_template_qa,
    suggest_mapping,
)
from app.pipeline.signing import sign_pdf_bytes
from app.pipeline.signing.base import resolve_provider, signing_meta_from_settings
from app.schemas import (
    AgentEvent,
    AgentRequest,
    FieldCatalogueEntry,
    FieldListCatalogueEntry,
    GeneratedSignResult,
    GenerateOutputFile,
    GenerateResult,
    MappingSuggestResponse,
    QaReport,
    QaRequest,
    SpreadsheetGrid,
    SpreadsheetPreviewResponse,
    SpreadsheetSheetMeta,
    TemplateCreate,
    TemplateDetail,
    TemplateFormField,
    TemplateLint,
    TemplateRevisionInfo,
    TemplateSummary,
    TemplateUpdate,
)

router = APIRouter(prefix="/templates", tags=["templates"])


def _to_detail(t: Template) -> TemplateDetail:
    source_url = (
        storage.template_source_url(t.id, t.source_ext or ".pdf") if t.source_file_id else None
    )
    # Advisory: which referenced field paths the doc type's catalogue no longer offers.
    result = lint_template(
        t.mode, t.doc_type, t.html_body, t.form_field_map, cell_map=t.cell_map
    )
    lint = TemplateLint(
        orphaned_paths=result.orphaned_paths,
        bound_count=result.bound_count,
        total_count=result.total_count,
    )
    return TemplateDetail(**t.model_dump(), source_url=source_url, lint=lint)


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


@router.post("/{template_id}/revisions/{revision_id}/restore", response_model=TemplateDetail)
def restore_template_revision(
    template_id: str, revision_id: str, session: Session = Depends(get_session)
) -> TemplateDetail:
    """Roll a template's html/css back to a past snapshot.

    The restore itself goes through ``apply_template_update``, so the *current* state is
    snapshotted first — a restore is always undoable. Revisions carry ``None`` html/css
    for the template's original blank state; those are coerced to ``""`` so restoring the
    blank original clears the body rather than being a no-op (``apply_template_update``
    skips ``None`` fields).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    rev = session.get(TemplateRevision, revision_id)
    if rev is None or rev.template_id != template_id:
        raise HTTPException(status_code=404, detail="Revision not found.")

    body = TemplateUpdate(
        html_body=rev.html if rev.html is not None else "",
        css=rev.css if rev.css is not None else "",
        revision_note=f"restore: {rev.id}",
    )
    tmpl = apply_template_update(session, tmpl, body)
    return _to_detail(tmpl)


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


@router.post("/{template_id}/qa", response_model=QaReport, status_code=201)
async def run_template_qa_endpoint(
    template_id: str, body: QaRequest, session: Session = Depends(get_session)
) -> QaReport:
    """Render the template and return a vision-based visual-fidelity critique.

    Only rich-HTML templates with a body can be QA'd (400 otherwise). An unknown ``provider``
    is a 400 up front (mirroring the agent route). With a ``document_id`` the preview is
    filled from that document's structured extraction (400 if it has none); without one, a
    ``[Label]`` placeholder preview is judged. The render + rasterize + judge runs in a
    threadpool with a timeout (504); a missing renderer maps to 503.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if tmpl.mode != TemplateMode.rich_html or not tmpl.html_body:
        raise HTTPException(
            status_code=400,
            detail="QA is only available for rich-HTML templates with a body.",
        )
    if body.provider and body.provider not in QA_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown qa vision provider '{body.provider}'. "
                f"Available: {', '.join(sorted(QA_PROVIDERS))}"
            ),
        )

    structured_fields = (
        _load_structured_fields(session, body.document_id) if body.document_id else None
    )

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                run_template_qa,
                tmpl,
                body.document_id,
                structured_fields,
                body.provider,
                body.instructions,
            ),
            timeout=settings.qa_timeout_s,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504, detail=f"QA timed out after {settings.qa_timeout_s:.0f}s."
        ) from None
    except RenderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    """Attach a source (PDF, DOCX, or XLSX) and set the template's mode from what it holds.

    A PDF carrying an AcroForm switches the template to ``form_fill`` (its fields are
    persisted for the mapper). A PDF without a form, or any DOCX, becomes ``rich_html``
    and is converted to an editable HTML body + baseline stylesheet. An XLSX becomes
    ``spreadsheet``: its per-sheet layout is enumerated for the cell-mapping UI. A
    non-PDF/DOCX/XLSX is a 415; an unreadable source is a 422 (mirroring the document
    upload path).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    try:
        ext, mime = storage.detect_template_source_type(file.filename or "")
    except storage.UnsupportedFileType:
        raise HTTPException(
            status_code=415, detail="Template source must be a PDF, DOCX, or XLSX."
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    source = storage.save_template_source(tmpl.id, ext, content)

    mode = TemplateMode.rich_html
    form_fields: list = []
    html_body: str | None = None
    css: str | None = None
    spreadsheet_sheets: list = []
    try:
        if mime == storage.XLSX_MIME:
            mode = TemplateMode.spreadsheet
            spreadsheet_sheets = [
                m.model_dump() for m in enumerate_workbook_sheets(source)
            ]
        elif mime == "application/pdf":
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
    elif mode == TemplateMode.spreadsheet:
        tmpl.spreadsheet_sheets = spreadsheet_sheets
        tmpl.cell_map = {}  # a new source invalidates any prior binding
        tmpl.output_formats = ["xlsx"]
    tmpl.updated_at = _utcnow()

    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return _to_detail(tmpl)


@router.get("/{template_id}/catalogue", response_model=list[FieldCatalogueEntry])
def get_template_catalogue(
    template_id: str, session: Session = Depends(get_session)
) -> list[FieldCatalogueEntry]:
    """The bindable field catalogue for the template's document type.

    A spreadsheet template binds scalars into single cells, so its catalogue is
    scalar-only (``list_repeat=0`` drops the synthetic ``line_items.N.*`` slots — list
    fields become table bindings via the list-catalogue endpoint instead).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if tmpl.mode == TemplateMode.spreadsheet:
        return field_catalogue(tmpl.doc_type, list_repeat=0)
    return field_catalogue(tmpl.doc_type)


@router.get(
    "/{template_id}/spreadsheet/sheets", response_model=list[SpreadsheetSheetMeta]
)
def get_spreadsheet_sheets(
    template_id: str, session: Session = Depends(get_session)
) -> list[SpreadsheetSheetMeta]:
    """The per-sheet layout enumerated from the uploaded workbook at source-upload time."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return [SpreadsheetSheetMeta(**m) for m in tmpl.spreadsheet_sheets or []]


@router.get("/{template_id}/spreadsheet/cells", response_model=SpreadsheetGrid)
def get_spreadsheet_cells(
    template_id: str,
    sheet: str = Query(...),
    session: Session = Depends(get_session),
) -> SpreadsheetGrid:
    """A (capped) grid of one sheet's non-empty cells for the click-to-bind mapping UI."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if tmpl.mode != TemplateMode.spreadsheet or not tmpl.source_file_id:
        raise HTTPException(
            status_code=400, detail="Template is not a spreadsheet template with a source."
        )
    source = storage.template_source_path(tmpl.id, tmpl.source_ext or ".xlsx")
    return read_template_grid(source, sheet)


@router.get(
    "/{template_id}/spreadsheet/list-catalogue",
    response_model=list[FieldListCatalogueEntry],
)
def get_spreadsheet_list_catalogue(
    template_id: str, session: Session = Depends(get_session)
) -> list[FieldListCatalogueEntry]:
    """The top-level list fields a spreadsheet table binding can expand down rows."""
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return list_field_catalogue(tmpl.doc_type)


@router.post(
    "/{template_id}/spreadsheet/preview", response_model=SpreadsheetPreviewResponse
)
async def preview_spreadsheet(
    template_id: str,
    document_id: str = Query(...),
    session: Session = Depends(get_session),
) -> SpreadsheetPreviewResponse:
    """A formula-computed preview of the filled workbook for a document.

    Fills the template from the document's structured extraction, recomputes formulas via
    LibreOffice (disk-cached by content hash), and returns the per-sheet computed grid.
    Never hard-fails on a LibreOffice failure: the raw formula strings are shown with
    ``computed=False`` instead (mirroring the fallback ladder).
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    if tmpl.mode != TemplateMode.spreadsheet or not tmpl.source_file_id:
        raise HTTPException(
            status_code=400, detail="Template is not a spreadsheet template with a source."
        )

    fields = _load_structured_fields(session, document_id)

    def _build() -> SpreadsheetPreviewResponse:
        outcome = fill_spreadsheet(tmpl, fields)
        recomputed = recompute_workbook(tmpl.id, outcome.content)
        sheets = read_computed_grid(recomputed.xlsx_bytes)
        return SpreadsheetPreviewResponse(
            sheets=sheets,
            computed=recomputed.computed,
            warnings=[*outcome.warnings, *recomputed.warnings],
        )

    return await asyncio.to_thread(_build)


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

    if tmpl.mode == TemplateMode.spreadsheet:
        if not tmpl.source_file_id:
            raise HTTPException(
                status_code=400,
                detail="Template is not a spreadsheet template with a source.",
            )

        def _generate_spreadsheet() -> GenerateResult:
            outcome = fill_spreadsheet(tmpl, fields)
            warnings = list(outcome.warnings)
            outputs: list[GenerateOutputFile] = []

            xlsx_id = _new_id()
            storage.save_template_output(tmpl.id, xlsx_id, outcome.content, ext=".xlsx")
            outputs.append(
                GenerateOutputFile(
                    format="xlsx",
                    output_id=xlsx_id,
                    output_url=storage.template_output_url(tmpl.id, xlsx_id, ext=".xlsx"),
                )
            )

            if "pdf" in (tmpl.output_formats or []):
                pdf_bytes = convert_to_pdf(outcome.content)
                if pdf_bytes:
                    pdf_id = _new_id()
                    storage.save_template_output(tmpl.id, pdf_id, pdf_bytes, ext=".pdf")
                    outputs.append(
                        GenerateOutputFile(
                            format="pdf",
                            output_id=pdf_id,
                            output_url=storage.template_output_url(tmpl.id, pdf_id),
                        )
                    )
                else:
                    warnings.append(
                        "PDF export unavailable (LibreOffice); returning the xlsx only."
                    )

            primary = outputs[0]
            return GenerateResult(
                output_url=primary.output_url,
                output_id=primary.output_id,
                filled_fields=outcome.filled,
                skipped_fields=outcome.skipped,
                signature_stamped=False,
                warnings=warnings,
                outputs=outputs,
            )

        return await asyncio.to_thread(_generate_spreadsheet)

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


@router.post(
    "/{template_id}/outputs/{output_id}/sign",
    response_model=GeneratedSignResult,
    status_code=201,
)
async def sign_template_output(
    template_id: str,
    output_id: str,
    provider: str = Query(default=""),
    session: Session = Depends(get_session),
) -> GeneratedSignResult:
    """Seal a GENERATED output PDF with a real PAdES signature (the outbound flow).

    Unlike the stamped ``signature_image`` on ``/generate`` (a legally-worthless
    picture), this applies a cryptographic signature whose embedded CMS validates
    against a trust chain — the document you actually transmit. The signed file is
    written beside the output as ``<output_id>-signed.pdf`` and self-validated.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    source = storage.template_output_path(template_id, output_id, ".pdf")
    if not source.is_file():
        raise HTTPException(
            status_code=404,
            detail="No generated PDF output with that id — generate a PDF first.",
        )

    try:
        signed_bytes, validation, engine_version, latency_ms = await asyncio.to_thread(
            sign_pdf_bytes, source.read_bytes(), provider
        )
    except ValueError as exc:  # unknown provider / missing optional dep
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    signed_id = f"{output_id}-signed"
    storage.save_template_output(template_id, signed_id, signed_bytes, ".pdf")

    return GeneratedSignResult(
        template_id=template_id,
        output_id=output_id,
        signed_output_id=signed_id,
        provider=resolve_provider(provider),
        engine_version=engine_version,
        level=validation.level,
        field_name=signing_meta_from_settings().field_name,
        signed_output_url=storage.template_output_url(template_id, signed_id, ".pdf"),
        validation=validation,
        latency_ms=latency_ms,
        warnings=list(validation.warnings),
    )
