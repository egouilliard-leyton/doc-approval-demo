"""AcroForm enumeration: read a fillable PDF's form fields (Wave 2, no fill yet).

``enumerate_form_fields`` opens a PDF with pypdf and returns whether it carries an
AcroForm plus one :class:`TemplateFormField` per field — its kind (text/checkbox/
radio/choice/signature), the page + rectangle of its widget, choice options, and a
best-effort nearby text label (via the already-installed PyMuPDF). This is the raw
material the form-fill mapper (next wave) binds catalogue paths onto; nothing here
writes to the PDF.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from io import BytesIO
from pathlib import Path
from typing import IO

from pypdf import PdfReader, PdfWriter

from app.schemas import TemplateFormField

# Field name matching this is forced to kind "signature" regardless of its /FT.
_SIGNATURE_RE = re.compile(r"signat", re.I)


def _widget_locations(reader: PdfReader) -> dict[str, tuple[int, list[float]]]:
    """Map each field's fully-qualified name to its ``(page_index, rect)`` widget.

    Walks every page's ``/Annots`` and derives the field name from the widget's own
    ``/T`` plus its ``/Parent`` chain (radio kids carry the name on the parent). Only
    the first widget found for a name is kept.
    """
    locations: dict[str, tuple[int, list[float]]] = {}
    for page_index, page in enumerate(reader.pages):
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            annot = ref.get_object()
            rect = annot.get("/Rect")
            if rect is None:
                continue
            parts: list[str] = []
            node: object | None = annot
            while isinstance(node, dict):
                title = node.get("/T")
                if title is not None:
                    parts.append(str(title))
                parent = node.get("/Parent")
                node = parent.get_object() if parent is not None else None
            if not parts:
                continue
            name = ".".join(reversed(parts))
            locations.setdefault(name, (page_index, [float(x) for x in rect]))
    return locations


def _choice_options(field: dict) -> list[str] | None:
    """Extract a choice field's option labels from ``/Opt`` (or ``/_States_``)."""
    raw = field.get("/Opt") or field.get("/_States_")
    if not raw:
        return None
    options: list[str] = []
    for entry in raw:
        # Each /Opt entry is either a display string or an [export, display] pair.
        if isinstance(entry, (list, tuple)):
            options.append(str(entry[-1]))
        else:
            options.append(str(entry))
    return options


def _kind_for(name: str, field: dict) -> str:
    """Derive a field kind from its ``/FT`` (name-based signature override wins)."""
    if _SIGNATURE_RE.search(name):
        return "signature"
    ft = field.get("/FT")
    if ft == "/Sig":
        return "signature"
    if ft == "/Ch":
        return "choice"
    if ft == "/Btn":
        # A radio group has kids with more than one distinct "on" state; a plain
        # checkbox has a single on-state (e.g. /Off + /Yes).
        states = field.get("/_States_") or []
        on_states = {str(s) for s in states if str(s) not in ("/Off", "Off")}
        if field.get("/Kids") and len(on_states) > 1:
            return "radio"
        return "checkbox"
    return "text"


def _nearby_label(pdf_path: str | Path, page_index: int, rect: list[float]) -> str | None:
    """Best-effort text just left of / around a widget, via PyMuPDF. None on failure."""
    try:
        import fitz  # PyMuPDF (already a core dep)

        with fitz.open(pdf_path) as doc:
            page = doc[page_index]
            height = page.rect.height
            x0, y0, x1, y1 = rect
            # PDF user space is bottom-left origin; fitz is top-left. Flip y and widen
            # the clip to the left to capture a preceding label.
            clip = fitz.Rect(max(x0 - 200.0, 0.0), height - y1 - 2.0, x1, height - y0 + 2.0)
            text = page.get_text("text", clip=clip)
        text = " ".join(text.split())
        return text or None
    except Exception:  # noqa: BLE001 — labels are best-effort; never fail enumeration
        return None


def enumerate_form_fields(pdf_path: str | Path) -> tuple[bool, list[TemplateFormField]]:
    """Read a PDF's AcroForm fields. Returns ``(has_acroform, fields)``.

    ``has_acroform`` is ``False`` (with an empty list) for a PDF with no form; a PDF
    with an AcroForm but no locatable widgets still yields fields with ``rect=None``.
    """
    reader = PdfReader(pdf_path)
    has_acroform = "/AcroForm" in reader.trailer["/Root"]
    if not has_acroform:
        return False, []

    fields = reader.get_fields() or {}
    locations = _widget_locations(reader)

    out: list[TemplateFormField] = []
    for name, field in fields.items():
        kind = _kind_for(name, field)
        page_index, rect = locations.get(name, (0, None))
        options = _choice_options(field) if kind == "choice" else None
        label = _nearby_label(pdf_path, page_index, rect) if rect is not None else None
        out.append(
            TemplateFormField(
                name=str(name),
                kind=kind,
                page=page_index + 1,  # 1-based, matching the rest of the pipeline
                rect=rect,
                options=options,
                nearby_label=label,
            )
        )
    return True, out


# --- Wave 4: fill + signature stamp + optional flatten -----------------------


@dataclass
class FillOutcome:
    """Result of :func:`fill_form`: which fields took, plus stamping/flatten notes."""

    filled: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)
    signature_stamped: bool = False
    warnings: list[str] = dc_field(default_factory=list)


def _signature_overlay_page(reader: PdfReader, page_index: int, rect: list[float], image_bytes: bytes):
    """Render a reportlab overlay (page-sized) with the signature image in ``rect``."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    page = reader.pages[page_index]
    box = page.mediabox
    page_w, page_h = float(box.width), float(box.height)
    x0, y0, x1, y1 = rect

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))
    c.drawImage(
        ImageReader(BytesIO(image_bytes)),
        x0,
        y0,
        width=x1 - x0,
        height=y1 - y0,
        mask="auto",
        preserveAspectRatio=True,
    )
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def fill_form(
    source_path: str | Path,
    text_values: dict[str, str],
    signature_rects: list[tuple[int, list[float]]],
    signature_image_bytes: bytes | None,
    out_path: str | Path | IO[bytes],
    flatten: bool,
) -> FillOutcome:
    """Fill a fillable PDF's text/checkbox/choice values, stamp signatures, write it out.

    ``text_values`` maps PDF field name -> its coerced string (checkbox on-state and
    choice option values included). ``signature_rects`` are ``(page_index, rect)`` targets
    stamped with ``signature_image_bytes`` when supplied. ``out_path`` accepts a path or a
    writable stream (e.g. ``BytesIO``). Everything degrades to a warning rather than
    aborting the write — a failed stamp or flatten still yields a usable PDF.
    """
    outcome = FillOutcome()

    reader = PdfReader(source_path)
    writer = PdfWriter()
    writer.append(reader)

    # Split requested values into ones that name a real field vs ones that don't.
    existing = set((reader.get_fields() or {}).keys())
    outcome.filled = [name for name in text_values if name in existing]
    outcome.skipped = [name for name in text_values if name not in existing]

    if text_values:
        # NB: pass ``list(writer.pages)`` — ``writer.pages`` is a lazy VirtualList that
        # fails pypdf's ``isinstance(page, list)`` check and silently updates nothing.
        try:
            writer.update_page_form_field_values(
                list(writer.pages), text_values, auto_regenerate=False, flatten=flatten
            )
        except Exception as exc:  # noqa: BLE001 — flatten can misbehave; keep the form live
            outcome.warnings.append(f"flatten failed; left form fields live: {exc}")
            writer.update_page_form_field_values(
                list(writer.pages), text_values, auto_regenerate=False
            )

    if signature_image_bytes is not None:
        for page_index, rect in signature_rects:
            try:
                overlay = _signature_overlay_page(reader, page_index, rect, signature_image_bytes)
                writer.pages[page_index].merge_page(overlay)
                outcome.signature_stamped = True
            except Exception as exc:  # noqa: BLE001 — one bad rect can't abort the whole gen
                outcome.warnings.append(f"signature stamp failed on page {page_index + 1}: {exc}")

    writer.write(out_path)
    return outcome
