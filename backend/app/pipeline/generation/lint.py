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

from .catalogue import field_catalogue, list_field_catalogue


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
    cell_map: dict | None = None,
) -> TemplateLintResult:
    """Check a template's field references against its doc type's catalogue.

    For a ``rich_html`` template, every non-empty ``data-field`` attribute in the body is a
    reference; for a ``form_fill`` template, every non-signature binding with a truthy
    ``field_path`` is (an unmapped field with ``field_path is None`` is not a reference); for
    a ``spreadsheet`` template (``cell_map``), every scalar ``field_path`` plus each table
    column expressed as ``{list_path}.{field_path}`` (or the bare ``list_path`` for the ``""``
    sentinel) is a reference. Any referenced path outside the catalogue is orphaned;
    ``bound_count`` is the count that resolves, ``total_count`` the total. Pure/offline and
    lenient on malformed HTML.
    """
    if mode == TemplateMode.spreadsheet:
        # A spreadsheet template binds against the list_repeat=0 scalar catalogue plus the
        # valid table paths ({list_path} and {list_path}.{column}) from the list catalogue.
        catalogue_paths = {e.path for e in field_catalogue(doc_type, list_repeat=0)}
        for entry in list_field_catalogue(doc_type):
            catalogue_paths.add(entry.list_path)
            for col in entry.columns:
                catalogue_paths.add(
                    f"{entry.list_path}.{col.path}" if col.path else entry.list_path
                )

        referenced: list[str] = []
        cmap = cell_map or {}
        for scalar in cmap.get("scalars", []) or []:
            if scalar.get("is_signature") or not scalar.get("field_path"):
                continue
            referenced.append(scalar["field_path"])
        for table in cmap.get("tables", []) or []:
            list_path = table.get("list_path")
            if not list_path:
                continue
            for col in table.get("columns", []) or []:
                field_path = col.get("field_path")
                referenced.append(f"{list_path}.{field_path}" if field_path else list_path)

        orphaned = sorted({p for p in referenced if p not in catalogue_paths})
        total_count = len(referenced)
        bound_count = total_count - len([p for p in referenced if p not in catalogue_paths])
        return TemplateLintResult(
            orphaned_paths=orphaned, bound_count=bound_count, total_count=total_count
        )

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
