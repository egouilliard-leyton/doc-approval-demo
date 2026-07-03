"""Phase 5 (polish): placeholder<->doc-type consistency lint.

A template references catalogue paths in two places — ``span[data-field]`` markers in a
rich-HTML body and ``field_path`` bindings in a form-fill map. :func:`lint_template` reports
which of those references point at a path the document type's field catalogue doesn't offer
(an *orphan*, e.g. a placeholder left behind after the doc type's fields changed), alongside
how many references resolve to a known path. Pure and offline — it reads the catalogue and
parses the body only, never any extracted data, and never raises on malformed HTML.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import DocType, TemplateMode

from .catalogue import field_catalogue


@dataclass
class TemplateLintResult:
    """Result of :func:`lint_template`: orphaned catalogue paths + bound/total counts."""

    orphaned_paths: list[str]  # sorted, deduped unknown paths referenced by the template
    bound_count: int  # occurrences resolving to a known catalogue path
    total_count: int  # total placeholder/mapping occurrences referencing any path


def lint_template(
    mode: TemplateMode,
    doc_type: DocType,
    html_body: str | None,
    form_field_map: dict,
) -> TemplateLintResult:
    """Check a template's field references against its doc type's catalogue.

    For a ``rich_html`` template, every non-empty ``data-field`` attribute in the body is a
    reference; for a ``form_fill`` template, every non-signature binding with a truthy
    ``field_path`` is (an unmapped field with ``field_path is None`` is not a reference).
    Any referenced path outside the catalogue is orphaned; ``bound_count`` is the count that
    resolves, ``total_count`` the total. Pure/offline and lenient on malformed HTML.
    """
    catalogue_paths = {e.path for e in field_catalogue(doc_type)}

    if mode == TemplateMode.rich_html:
        from bs4 import BeautifulSoup  # lazy: optional docgen dep

        soup = BeautifulSoup(html_body or "", "html.parser")
        referenced = [
            span.get("data-field")
            for span in soup.select("span[data-field]")
            if span.get("data-field")
        ]
    else:  # form_fill
        referenced = [
            binding.get("field_path")
            for binding in (form_field_map or {}).values()
            if not binding.get("is_signature") and binding.get("field_path")
        ]

    orphaned = sorted({p for p in referenced if p not in catalogue_paths})
    total_count = len(referenced)
    bound_count = total_count - len([p for p in referenced if p not in catalogue_paths])
    return TemplateLintResult(
        orphaned_paths=orphaned, bound_count=bound_count, total_count=total_count
    )
