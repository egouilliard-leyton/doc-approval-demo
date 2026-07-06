"""Phase 4 (Vision QA) Wave 1 tests: the offline vision judge + preview builder.

The ``mock`` QA provider needs no network and does not inspect the image bytes, so tiny
fake PNGs suffice. The preview builder's PDF path uses WeasyPrint, so it is probed and
skipped when the system libs are absent (they are present here).
"""

import pytest

from app.models import DocType, Template
from app.pipeline.generation import render_template_preview, run_qa

_FAKE_PNG = b"\x89PNG\r\n\x1a\n-not-a-real-image"


def _weasyprint_available() -> bool:
    """True when WeasyPrint imports and its system libraries load."""
    try:
        import weasyprint  # noqa: F401

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:  # noqa: BLE001 — any import/OSError means unavailable
        return False


def test_run_qa_mock_returns_fixed_outcome():
    outcome = run_qa([_FAKE_PNG], [], "invoice", "<p>x</p>", None, provider="mock")
    assert outcome.provider_used == "mock"
    assert outcome.model == "mock"
    assert outcome.ok is False
    assert len(outcome.findings) == 2
    assert outcome.summary == "2 potential issues found."
    # Each finding carries the documented shape.
    for finding in outcome.findings:
        assert {"severity", "category", "description", "suggested_fix", "page"} <= finding.keys()
    assert outcome.findings[0]["severity"] == "medium"
    assert outcome.findings[0]["category"] == "spacing"


def test_run_qa_unknown_provider_raises():
    with pytest.raises(ValueError):
        run_qa([_FAKE_PNG], [], "invoice", "<p>x</p>", None, provider="bogus")


@pytest.mark.skipif(
    not _weasyprint_available(), reason="WeasyPrint system libraries not present"
)
def test_render_template_preview_label_path_returns_pdf():
    template = Template(
        name="Invoice tmpl",
        doc_type=DocType.invoice,
        html_body='<h1>Invoice</h1><p>Vendor: <span data-field="vendor">Vendor</span></p>',
        css="h1 { color: navy; }",
    )
    pdf = render_template_preview(template, structured_fields=None)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")


@pytest.mark.skipif(
    not _weasyprint_available(), reason="WeasyPrint system libraries not present"
)
def test_render_template_preview_document_bound_returns_pdf():
    template = Template(
        name="Invoice tmpl",
        doc_type=DocType.invoice,
        html_body='<p>Vendor: <span data-field="vendor">Vendor</span></p>',
        css="",
    )
    structured_fields = {"vendor": {"value": "Acme Supplies Inc.", "confidence": 0.9}}
    pdf = render_template_preview(template, structured_fields=structured_fields)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
