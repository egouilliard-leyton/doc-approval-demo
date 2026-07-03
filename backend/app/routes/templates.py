"""Template registry endpoints (Phase 0)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, delete, select

from app.db import get_session
from app.models import DocType, Template, TemplateRevision, _utcnow
from app.schemas import TemplateCreate, TemplateDetail, TemplateSummary, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"])


def _to_detail(t: Template) -> TemplateDetail:
    return TemplateDetail(**t.model_dump())


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
    """Permanently remove a template and its revision history.

    The TemplateRevision -> Template foreign key has no DB cascade configured, so
    the revisions are deleted explicitly before the template.
    """
    tmpl = session.get(Template, template_id)
    if tmpl is None:
        raise HTTPException(status_code=404, detail="Template not found.")

    session.exec(delete(TemplateRevision).where(TemplateRevision.template_id == template_id))
    session.delete(tmpl)
    session.commit()
