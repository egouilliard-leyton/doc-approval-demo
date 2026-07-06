"""Phase 3 (authoring-agent) Wave 1: the revision-safe persist helper + HTML sanitizer.

Both pieces are shared by the human PUT-template route and (in later waves) the authoring
agent that writes a template's HTML/CSS directly. :func:`apply_template_update` is the single
place that snapshots the pre-update html/css into a :class:`TemplateRevision` and reassigns the
provided fields; :func:`sanitize_template_html` is defence-in-depth over any raw HTML that will
be rendered by WeasyPrint and shown in the UI (strip ``<script>``/``<iframe>``, event handlers,
and ``javascript:`` URLs).
"""

from __future__ import annotations

from sqlmodel import Session

from app.models import Template, TemplateRevision, _utcnow
from app.schemas import TemplateUpdate


def sanitize_template_html(html: str | None) -> str | None:
    """Strip active content from raw template HTML before it is stored/rendered.

    Removes ``<script>`` and ``<iframe>`` elements entirely, drops any ``on*`` event-handler
    attribute (onclick, onload, …), and clears any ``javascript:`` ``href``/``src``. Returns the
    serialized cleaned HTML; ``None`` passes straight through. Pure and best-effort — the agent
    writes raw HTML that WeasyPrint renders and the UI displays, so this is defence-in-depth.
    """
    if html is None:
        return None

    from bs4 import BeautifulSoup  # lazy: optional docgen dep

    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.select("script, iframe"):
        tag.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs):
            value = tag.attrs[attr]
            if attr.lower().startswith("on"):
                del tag.attrs[attr]
            elif attr.lower() in ("href", "src") and isinstance(value, str) and (
                value.strip().lower().startswith("javascript:")
            ):
                del tag.attrs[attr]

    return str(soup)


def apply_template_update(session: Session, tmpl: Template, body: TemplateUpdate) -> Template:
    """Apply a partial update to ``tmpl``, snapshotting html/css before an edit that touches them.

    If the update sets ``html_body`` or ``css``, the PRE-update html/css are first captured as a
    :class:`TemplateRevision` so the edit is revertible. A new ``html_body`` is sanitized before it
    is stored. Only non-``None`` fields are reassigned (JSON columns wholesale, since SQLAlchemy
    doesn't detect in-place mutation of a dict/list). Commits and returns the refreshed template.
    """
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
            if attr == "html_body":
                value = sanitize_template_html(value)  # never store active content
            setattr(tmpl, attr, value)
    tmpl.updated_at = _utcnow()

    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return tmpl
