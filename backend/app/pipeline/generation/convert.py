"""Phase 2 (rich-HTML) Wave 1: convert an uploaded source to an editable HTML body.

A ``.docx`` source is converted with mammoth (semantic HTML, inline data-URI images);
a ``.pdf`` source is converted with Docling as the primary path (layout-aware whole-PDF
HTML) and falls back to a plain PyMuPDF text extraction when Docling is unavailable or
errors. Every path returns a :class:`ConvertResult` carrying the ``<body>`` fragment,
a baseline stylesheet, and human-readable warnings — conversion never raises on a bad
document, it degrades to the simplest available representation.

The heavy docling import is lazy (mirrors ``app/pipeline/ocr/docling.py``) so the app
boots without the optional ``docgen``/``ocr`` extras.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field as dc_field
from pathlib import Path

logger = logging.getLogger(__name__)

# Baseline stylesheet shared by every converted body: an A4 print page, readable base
# typography, and bordered tables (docling/mammoth emit bare <table>s).
_DEFAULT_CSS = """\
@page { size: A4; margin: 2cm; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #222; }
h1, h2, h3, h4, h5, h6 { margin: 1.2em 0 0.5em; font-weight: 600; }
p { margin: 0.5em 0; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
td, th { border: 1px solid #999; padding: 4px 8px; text-align: left; }
img { max-width: 100%; height: auto; }
"""


@dataclass
class ConvertResult:
    """A source converted to an editable HTML body plus its baseline stylesheet."""

    html: str
    css: str = _DEFAULT_CSS
    warnings: list[str] = dc_field(default_factory=list)


def convert_docx(content: bytes) -> ConvertResult:
    """Convert a ``.docx``'s bytes to an HTML body fragment via mammoth.

    ``mammoth.convert_to_html`` returns a body fragment (no ``<html>``/``<body>`` wrapper)
    with images already inlined as data URIs; its messages become warnings.
    """
    import mammoth  # lazy: optional docgen dep

    result = mammoth.convert_to_html(io.BytesIO(content))
    warnings = [getattr(m, "message", str(m)) for m in result.messages]
    return ConvertResult(html=result.value or "", css=_DEFAULT_CSS, warnings=warnings)


def _convert_pdf_docling(path: str | Path) -> ConvertResult:
    """Primary PDF path: Docling whole-PDF -> HTML, body inner extracted, style hoisted.

    Builds a SECOND ``DocumentConverter`` (the one in ``ocr/docling.py`` is configured for
    per-page IMAGE input); its default PDF pipeline is what we want for whole-document HTML.
    """
    from bs4 import BeautifulSoup  # lazy: optional docgen dep
    from docling.document_converter import DocumentConverter  # lazy: heavy optional dep

    converter = DocumentConverter()
    html = converter.convert(str(path)).document.export_to_html()

    soup = BeautifulSoup(html, "html.parser")
    css = _DEFAULT_CSS
    for style in soup.find_all("style"):
        css += "\n" + style.get_text()
        style.decompose()  # pulled into css; don't leave it inline in the body
    body = soup.body
    body_html = body.decode_contents() if body is not None else html

    return ConvertResult(
        html=body_html,
        css=css,
        warnings=["converted via docling (whole-PDF HTML export)"],
    )


def _convert_pdf_pymupdf(path: str | Path) -> ConvertResult:
    """Fallback PDF path: PyMuPDF text blocks wrapped in <p> (always available)."""
    import fitz  # PyMuPDF (already a core dep)

    from html import escape

    parts: list[str] = []
    with fitz.open(path) as pdf:
        for page in pdf:
            for block in page.get_text("blocks"):
                text = str(block[4]).strip()
                if text:
                    parts.append(f"<p>{escape(text)}</p>")
    return ConvertResult(
        html="\n".join(parts),
        css=_DEFAULT_CSS,
        warnings=["converted via PyMuPDF fallback (plain text blocks)"],
    )


def convert_pdf(path: str | Path) -> ConvertResult:
    """Convert a PDF to an HTML body: Docling primary, PyMuPDF fallback.

    Any docling import/convert failure is logged and folded into a warning on the
    fallback result — conversion never raises for a rendering-only document.
    """
    try:
        return _convert_pdf_docling(path)
    except Exception as exc:  # noqa: BLE001 — docling is optional/best-effort; fall back
        logger.warning("docling PDF conversion failed, falling back to PyMuPDF: %s", exc)
        result = _convert_pdf_pymupdf(path)
        result.warnings.insert(0, f"docling unavailable/failed ({exc}); used PyMuPDF fallback")
        return result
