"""Phase 2 (rich-HTML) Wave 1: render a bound HTML body to PDF or DOCX bytes.

:func:`render_pdf` wraps the body + css into a full HTML document and rasterizes it with
WeasyPrint (needs the pango/cairo/gdk-pixbuf system libs — a missing lib surfaces as
:class:`RenderUnavailableError` rather than a bare ``OSError``). :func:`render_docx` runs
the same HTML through html4docx (pure-python, always available) into a Word document.
Both heavy imports are lazy so the app boots without the optional ``docgen`` extra.
"""

from __future__ import annotations

from io import BytesIO


class RenderUnavailableError(Exception):
    """Raised when a renderer's engine/system libraries are not importable/usable."""


def _wrap(html_body: str, css: str) -> str:
    """Assemble a full standalone HTML document around a body fragment + stylesheet."""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<style>{css or ''}</style></head><body>{html_body}</body></html>"
    )


def render_pdf(html_body: str, css: str) -> bytes:
    """Render a bound HTML body to PDF bytes via WeasyPrint.

    A missing WeasyPrint install or one of its system libraries (pango/cairo/…) raises
    :class:`RenderUnavailableError` so the caller can degrade instead of 500-ing.
    """
    try:
        import weasyprint  # lazy: optional docgen dep + system libs

        return weasyprint.HTML(string=_wrap(html_body, css)).write_pdf()
    except (ImportError, OSError) as exc:
        raise RenderUnavailableError(f"WeasyPrint unavailable: {exc}") from exc


def render_docx(html_body: str, css: str) -> bytes:
    """Render a bound HTML body to DOCX bytes via html4docx (pure-python).

    ``css`` is accepted for signature parity with :func:`render_pdf`; html4docx applies
    inline styles only, so the wrapper's ``<style>`` block is largely advisory here.
    """
    try:
        from html4docx import HtmlToDocx  # lazy: optional docgen dep

        document = HtmlToDocx().parse_html_string(_wrap(html_body, css))
        buf = BytesIO()
        document.save(buf)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001 — surface any html4docx failure clearly
        raise RuntimeError(f"DOCX rendering failed: {exc}") from exc
