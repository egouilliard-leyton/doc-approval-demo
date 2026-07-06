"""Phase 1 (form-fill) Wave 4: turn a structured document into a filled PDF.

``generate_pdf`` joins a template's ``form_field_map`` (pdf field -> binding) with its
enumerated ``form_fields`` (kind/rect/options) and a document's flattened structured
values, coercing each value to what its PDF field kind expects: text as a string, a
checkbox to its on-state, a choice only when the value matches an option. Radio groups
are skipped (a scalar can't pick an option in Phase 1); a missing/None value is skipped
too, never guessed. Signature fields become stamp targets. The heavy pypdf write lives
in :func:`app.pipeline.generation.forms.fill_form`.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from io import BytesIO

from pypdf import PdfReader

from app import models, storage
from app.pipeline.generation.binder import bind_html
from app.pipeline.generation.forms import fill_form
from app.pipeline.generation.render import (
    RenderUnavailableError,
    render_docx,
    render_pdf,
)
from app.pipeline.generation.values import flatten_field_values


@dataclass
class GenerateOutcome:
    """Result of :func:`generate_pdf`: the saved output id + fill/stamp trace."""

    output_id: str
    filled: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)
    signature_stamped: bool = False
    warnings: list[str] = dc_field(default_factory=list)


@dataclass
class RenderedFile:
    """One rendered output of :func:`generate_rich`: its format, id, and bytes."""

    format: str  # "pdf" | "docx"
    output_id: str
    content: bytes


@dataclass
class GenerateRichOutcome:
    """Result of :func:`generate_rich`: every rendered file + the bind trace."""

    rendered: list[RenderedFile] = dc_field(default_factory=list)
    filled: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)
    signature_stamped: bool = False
    warnings: list[str] = dc_field(default_factory=list)


def _truthy(value: object) -> bool:
    """Coerce an extracted scalar to a checkbox on/off decision."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "no", "off", "0", "n")
    return value is not None


def _checkbox_on_state(states: object) -> str:
    """The first non-Off appearance state of a checkbox (defaults to ``/Yes``)."""
    for state in states or []:
        text = str(state)
        if text not in ("/Off", "Off"):
            return text if text.startswith("/") else f"/{text}"
    return "/Yes"


def generate_pdf(
    template,
    structured_fields: dict,
    signature_image_bytes: bytes | None,
    flatten: bool,
) -> GenerateOutcome:
    """Fill ``template``'s source PDF from a document's structured fields.

    ``template`` is the ORM row (its ``form_field_map`` + ``form_fields`` drive the
    binding); ``structured_fields`` is a dumped structuring ``fields`` blob.
    """
    output_id = models._new_id()
    flat = flatten_field_values(structured_fields)

    fields_by_name = {f.get("name"): f for f in (template.form_fields or [])}
    source_path = storage.template_source_path(template.id)
    # Checkbox on-states live only in the PDF (form_fields carries options for choices,
    # not button states), so read them straight from the source's AcroForm.
    pdf_fields = PdfReader(source_path).get_fields() or {}

    text_values: dict[str, str] = {}
    signature_rects: list[tuple[int, list[float]]] = []
    skipped: list[str] = []
    warnings: list[str] = []

    for pdf_field, binding in (template.form_field_map or {}).items():
        binding = binding if isinstance(binding, dict) else {}
        ff = fields_by_name.get(pdf_field, {})
        kind = ff.get("kind", "text")
        is_signature = bool(binding.get("is_signature")) or kind == "signature"

        if is_signature:
            rect = ff.get("rect")
            if rect is None:
                skipped.append(pdf_field)
                warnings.append(f"{pdf_field}: signature field has no located rect; not stamped")
                continue
            signature_rects.append((int(ff.get("page", 1)) - 1, [float(x) for x in rect]))
            continue

        field_path = binding.get("field_path")
        if not field_path:
            skipped.append(pdf_field)
            warnings.append(f"{pdf_field}: no field_path bound")
            continue

        value = flat.get(field_path)
        if value is None:
            skipped.append(pdf_field)
            warnings.append(f"{pdf_field}: no value at '{field_path}'")
            continue

        if kind == "radio":
            skipped.append(pdf_field)
            warnings.append(f"{pdf_field}: radio groups are not mapped in Phase 1")
            continue
        if kind == "checkbox":
            states = pdf_fields.get(pdf_field, {}).get("/_States_")
            text_values[pdf_field] = _checkbox_on_state(states) if _truthy(value) else "/Off"
            continue
        if kind == "choice":
            svalue = str(value)
            options = ff.get("options") or []
            if svalue not in options:
                skipped.append(pdf_field)
                warnings.append(
                    f"{pdf_field}: '{svalue}' is not one of the choice options {options}"
                )
                continue
            text_values[pdf_field] = svalue
            continue
        # text (and any unknown kind) -> stringified value.
        text_values[pdf_field] = str(value)

    if signature_rects and signature_image_bytes is None:
        warnings.append("signature field(s) bound but no signature image supplied; not stamped")

    buf = BytesIO()
    fill = fill_form(
        source_path, text_values, signature_rects, signature_image_bytes, buf, flatten
    )

    storage.save_template_output(template.id, output_id, buf.getvalue())

    return GenerateOutcome(
        output_id=output_id,
        filled=fill.filled,
        skipped=skipped + fill.skipped,
        signature_stamped=fill.signature_stamped,
        warnings=warnings + fill.warnings,
    )


# --- Phase 2 (rich-HTML): bind a template's HTML body + render to PDF/DOCX -----

# Each requested format maps to its renderer; both raise on an unavailable engine.
_RENDERERS = {"pdf": render_pdf, "docx": render_docx}


def generate_rich(
    template,
    structured_fields: dict,
    signature_image_bytes: bytes | None,
    formats: list[str],
) -> GenerateRichOutcome:
    """Bind ``template``'s HTML body from a document's fields, render to each format.

    ``template`` is the ORM row (its ``html_body`` + ``css`` drive the render); the body's
    ``span[data-field]`` / ``img[data-signature]`` markers are filled from the flattened
    structured values. Each requested format is rendered independently: a failed render
    (missing engine or otherwise) is folded into a warning and skipped rather than aborting
    the whole call, so ``rendered`` may be empty if every format failed.
    """
    flat = flatten_field_values(structured_fields)
    bound = bind_html(template.html_body or "", flat, signature_image_bytes)

    outcome = GenerateRichOutcome(
        filled=bound.filled,
        skipped=bound.skipped,
        signature_stamped=bound.signature_stamped,
        warnings=list(bound.warnings),
    )

    # De-dup while preserving order; empty request defaults to a single PDF.
    wanted = list(dict.fromkeys(formats)) or ["pdf"]
    css = template.css or ""
    for fmt in wanted:
        renderer = _RENDERERS.get(fmt)
        if renderer is None:
            outcome.warnings.append(f"{fmt}: unsupported output format; skipped")
            continue
        try:
            content = renderer(bound.html, css)
        except RenderUnavailableError as exc:
            outcome.warnings.append(f"{fmt}: renderer unavailable; skipped ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001 — one bad format must not fail the rest
            outcome.warnings.append(f"{fmt}: rendering failed; skipped ({exc})")
            continue
        outcome.rendered.append(
            RenderedFile(format=fmt, output_id=models._new_id(), content=content)
        )

    return outcome
