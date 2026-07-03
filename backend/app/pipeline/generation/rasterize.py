"""Phase 4 (Vision QA) Wave 1: rasterize a PDF into per-page PNG bytes.

The vision judge needs page images, so :func:`render_pdf_to_pngs` turns a rendered
preview PDF (WeasyPrint bytes) into a list of PNGs — one per page, up to ``max_pages``.
Rendering uses ``pypdfium2`` (BSD/Apache, no system binary, non-AGPL) rather than the
PyMuPDF path in :mod:`app.storage`, so this new rasterization stays permissively licensed.
The heavy import is lazy so the app boots without the optional ``docgen`` extra.
"""

from __future__ import annotations

import io


def render_pdf_to_pngs(
    pdf_bytes: bytes, dpi: int, max_pages: int | None = None
) -> tuple[list[bytes], bool]:
    """Rasterize ``pdf_bytes`` to a list of per-page PNG bytes at ``dpi``.

    Renders each page (up to ``max_pages`` when given) at ``scale = dpi / 72`` — PDF user
    space is 72 DPI — and encodes it as PNG. Returns ``(pngs, truncated)`` where ``truncated``
    is True when ``max_pages`` was set and the document has more pages than that. Empty or
    invalid ``pdf_bytes`` raises :class:`ValueError` for the caller to handle.
    """
    if not pdf_bytes:
        raise ValueError("render_pdf_to_pngs: empty PDF bytes")

    import pypdfium2 as pdfium  # lazy: optional docgen dep

    try:
        doc = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:  # noqa: BLE001 — surface a clear error, not a raw pdfium fault
        raise ValueError(f"render_pdf_to_pngs: invalid PDF bytes: {exc}") from exc

    try:
        page_count = len(doc)
        limit = page_count if max_pages is None else min(page_count, max_pages)
        scale = dpi / 72.0

        pngs: list[bytes] = []
        for index in range(limit):
            page = doc[index]
            image = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            image.save(buf, "PNG")
            pngs.append(buf.getvalue())

        truncated = max_pages is not None and page_count > max_pages
        return pngs, truncated
    finally:
        doc.close()
