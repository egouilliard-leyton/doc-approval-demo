"""Phase 2 (rich-HTML) Wave 1 tests: source -> HTML conversion. Offline.

The docx path (mammoth) and the PDF PyMuPDF-fallback path are always available and run
unconditionally; the docling primary PDF path is exercised only when docling is installed.
"""

import pytest

from app.pipeline.generation import convert_docx, convert_pdf
from app.pipeline.generation.convert import _convert_pdf_pymupdf

from .generation_fixtures import DOCX_HEADING, make_docx_bytes, make_plain_pdf


def test_convert_docx_returns_html_with_heading():
    result = convert_docx(make_docx_bytes())
    assert result.html.strip(), "expected a non-empty converted body"
    assert DOCX_HEADING in result.html
    # The 2-cell table survives as a real <table>.
    assert "<table" in result.html
    assert result.css  # baseline stylesheet always present


def test_convert_pdf_returns_non_empty_html(tmp_path):
    """``convert_pdf`` yields a non-empty body via whichever path is available."""
    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(make_plain_pdf())

    result = convert_pdf(pdf)
    assert result.html.strip(), "expected a non-empty converted body"
    assert result.css
    assert result.warnings  # every path notes which converter it used


def test_convert_pdf_pymupdf_fallback_is_unconditional(tmp_path):
    """The PyMuPDF fallback works with no docling and captures the page text as <p>."""
    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(make_plain_pdf())

    result = _convert_pdf_pymupdf(pdf)
    assert "<p>" in result.html
    assert "prose" in result.html  # text from make_plain_pdf survives
    assert any("PyMuPDF" in w for w in result.warnings)


def test_convert_pdf_docling_path_when_available(tmp_path):
    """When docling is installed, the primary path returns a non-empty body."""
    pytest.importorskip("docling")
    from app.pipeline.generation.convert import _convert_pdf_docling

    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(make_plain_pdf())

    result = _convert_pdf_docling(pdf)
    assert result.html.strip()
    assert any("docling" in w for w in result.warnings)
