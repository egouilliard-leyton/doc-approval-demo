"""Phase 4 (Vision QA) Wave 2: orchestrate render -> rasterize -> judge for a template.

:func:`run_template_qa` ties the Wave-1 leaves together: render the template's HTML body to
a preview PDF (:mod:`preview`), rasterize it to per-page PNGs (:mod:`rasterize`), rasterize
the source PDF as the reference when the template has one, hand both to the vision judge
(:mod:`qa_vision`), and persist every page image so the UI can show the compared pages.

The reference decides the ``mode``: a ``.pdf`` source that exists on disk is rasterized as
the ground truth (``source_pdf``); otherwise there is nothing to compare against and the
judge critiques the render on its own (``self_review``). Rendering degrades loudly — a
missing renderer raises :class:`RenderUnavailableError` for the route to map to 503 — while
the vision leg degrades quietly to the mock outcome (see :func:`qa_vision.run_qa`).
"""

from __future__ import annotations

from app import storage
from app.config import settings
from app.models import Template, _new_id
from app.schemas import QaFinding, QaReport

from .preview import render_template_preview
from .qa_vision import run_qa
from .rasterize import render_pdf_to_pngs


def run_template_qa(
    template: Template,
    document_id: str | None,
    structured_fields: dict | None,
    provider: str,
    instructions: str | None,
) -> QaReport:
    """Render ``template``, judge it against its source (or itself), and return the report.

    With ``structured_fields`` the preview is filled from a real document; without it, a
    ``[Label]`` placeholder preview is rendered. Both the rendered and (when present) the
    reference pages are persisted under this run's id and returned as ``/files`` URLs. Render
    or rasterize failures propagate (notably :class:`RenderUnavailableError` -> route 503);
    the vision call never raises (it degrades to the mock outcome with a warning).
    """
    run_id = _new_id()
    warnings: list[str] = []

    pdf = render_template_preview(template, structured_fields)
    rendered_pngs, r_trunc = render_pdf_to_pngs(pdf, settings.qa_render_dpi, settings.qa_max_pages)
    if r_trunc:
        warnings.append(f"Rendered preview truncated to qa_max_pages={settings.qa_max_pages}.")

    reference_pngs: list[bytes] = []
    mode = "self_review"
    if template.source_ext == ".pdf":
        source_path = storage.template_source_path(template.id, ".pdf")
        if source_path.exists():
            reference_pngs, ref_trunc = render_pdf_to_pngs(
                source_path.read_bytes(), settings.qa_render_dpi, settings.qa_max_pages
            )
            mode = "source_pdf"
            if ref_trunc:
                warnings.append(
                    f"Reference source truncated to qa_max_pages={settings.qa_max_pages}."
                )

    outcome = run_qa(
        rendered_pngs,
        reference_pngs,
        template.doc_type,
        (template.html_body or "")[:4000],
        instructions,
        provider,
    )

    rendered_urls: list[str] = []
    for page_no, png in enumerate(rendered_pngs, start=1):
        storage.save_qa_page(template.id, run_id, "rendered", page_no, png)
        rendered_urls.append(storage.qa_page_url(template.id, run_id, "rendered", page_no))

    reference_urls: list[str] = []
    for page_no, png in enumerate(reference_pngs, start=1):
        storage.save_qa_page(template.id, run_id, "reference", page_no, png)
        reference_urls.append(storage.qa_page_url(template.id, run_id, "reference", page_no))

    findings = [
        QaFinding(
            severity=f.get("severity", "low"),
            category=f.get("category", "layout"),
            description=f.get("description", ""),
            suggested_fix=f.get("suggested_fix") or None,
            page=f.get("page"),
        )
        for f in outcome.findings
    ]

    return QaReport(
        template_id=template.id,
        document_id=document_id,
        mode=mode,
        ok=outcome.ok,
        summary=outcome.summary,
        findings=findings,
        rendered_image_urls=rendered_urls,
        reference_image_urls=reference_urls,
        provider_used=outcome.provider_used,
        model=outcome.model,
        warnings=[*warnings, *outcome.warnings],
    )
