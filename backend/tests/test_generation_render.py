"""Phase 2 (rich-HTML) Wave 1 tests: HTML -> PDF/DOCX rendering.

The DOCX path (html4docx) is pure-python and runs everywhere. The PDF path needs
WeasyPrint's system libs, so it is probed and skipped when unavailable (it runs here,
where pango/cairo/gdk-pixbuf are present).
"""

import pytest

from app.pipeline.generation import render_docx, render_pdf


def _weasyprint_available() -> bool:
    """True when WeasyPrint imports and its system libraries load."""
    try:
        import weasyprint  # noqa: F401

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:  # noqa: BLE001 — any import/OSError means unavailable
        return False


@pytest.mark.skipif(
    not _weasyprint_available(), reason="WeasyPrint system libraries not present"
)
def test_render_pdf_returns_pdf_bytes():
    data = render_pdf("<p>Hello</p>", "")
    assert isinstance(data, bytes)
    assert data.startswith(b"%PDF")


def test_render_docx_returns_docx_bytes():
    data = render_docx("<h1>Hello</h1><p>body</p>", "")
    assert isinstance(data, bytes)
    assert data[:2] == b"PK"  # zip magic (a .docx is a zip container)
    assert len(data) > 0


def test_render_docx_strips_signature_anchor():
    """The hidden signature anchor (a transparent token, invisible in the PDF) must not
    leak into the DOCX, where html4docx ignores the color style and would show it."""
    import io

    import docx as _docx
    import pytest

    from app.pipeline.generation.binder import bind_html
    from app.pipeline.generation.render import render_docx
    from app.pipeline.signing.base import SIGNATURE_ANCHOR_TOKEN

    bound = bind_html("<p>Vendor: X</p><div><img data-signature></div>", {}, None)
    assert SIGNATURE_ANCHOR_TOKEN in bound.html  # present in the bound HTML (for the PDF)

    docx_bytes = render_docx(bound.html, "")
    text = "\n".join(p.text for p in _docx.Document(io.BytesIO(docx_bytes)).paragraphs)
    assert SIGNATURE_ANCHOR_TOKEN not in text  # ...but stripped from the Word output
