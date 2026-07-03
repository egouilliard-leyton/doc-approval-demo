"""Phase 4 (Vision QA) Wave 1: render a template to a preview PDF for the vision judge.

:func:`render_template_preview` binds a template's HTML body to a set of flat values —
either a real document's structured fields or, when none is given, a ``[Label]`` preview
drawn from the field catalogue — and renders it to PDF bytes with WeasyPrint. This is the
single preview builder reused by the QA orchestrator (next wave) and, later, the
``render_preview`` authoring-agent tool. The heavy imports live in the callees.
"""

from __future__ import annotations

from app.models import Template

from .binder import bind_html
from .catalogue import field_catalogue
from .render import render_pdf
from .values import flatten_field_values


def render_template_preview(template: Template, structured_fields: dict | None) -> bytes:
    """Render ``template`` to preview PDF bytes.

    With ``structured_fields`` the template is filled from a real document's values
    (flattened to dotted paths); without it, each catalogue slot is filled with a
    ``[Label]`` placeholder so the layout can be reviewed with no live document. The
    signature stamp is dropped (``signature_bytes=None``).
    """
    if structured_fields is not None:
        flat_values: dict[str, object] = flatten_field_values(structured_fields)
    else:
        flat_values = {
            entry.path: f"[{entry.label}]" for entry in field_catalogue(template.doc_type)
        }

    bound = bind_html(template.html_body or "", flat_values, signature_bytes=None)
    return render_pdf(bound.html, template.css or "")
