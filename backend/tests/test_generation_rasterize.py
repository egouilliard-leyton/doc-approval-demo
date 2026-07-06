"""Phase 4 (Vision QA) Wave 1 tests: rasterize a PDF into per-page PNG bytes.

Both WeasyPrint (PDF source) and pypdfium2 (rasterizer) are offline, so these run
without network. WeasyPrint needs its system libs, so the PDF build is probed and the
module skipped when unavailable (it runs here, where pango/cairo/gdk-pixbuf are present).
"""

import pytest

from app.pipeline.generation import render_pdf, render_pdf_to_pngs

_PNG_MAGIC = b"\x89PNG"


def _weasyprint_available() -> bool:
    """True when WeasyPrint imports and its system libraries load."""
    try:
        import weasyprint  # noqa: F401

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:  # noqa: BLE001 — any import/OSError means unavailable
        return False


pytestmark = pytest.mark.skipif(
    not _weasyprint_available(), reason="WeasyPrint system libraries not present"
)

# Two pages via a hard CSS page break.
_TWO_PAGE_HTML = "<p>page one</p><p style='page-break-before: always'>page two</p>"


def test_render_pdf_to_pngs_returns_png_per_page():
    pdf = render_pdf("<p>Hello</p>", "")
    pngs, truncated = render_pdf_to_pngs(pdf, dpi=100)
    assert len(pngs) >= 1
    assert all(png.startswith(_PNG_MAGIC) for png in pngs)
    assert truncated is False


def test_render_pdf_to_pngs_respects_max_pages():
    pdf = render_pdf(_TWO_PAGE_HTML, "")
    # Sanity: the source really has 2 pages.
    all_pngs, _ = render_pdf_to_pngs(pdf, dpi=72)
    assert len(all_pngs) == 2

    pngs, truncated = render_pdf_to_pngs(pdf, dpi=72, max_pages=1)
    assert len(pngs) == 1
    assert pngs[0].startswith(_PNG_MAGIC)
    assert truncated is True


def test_render_pdf_to_pngs_rejects_empty_bytes():
    with pytest.raises(ValueError):
        render_pdf_to_pngs(b"", dpi=100)
