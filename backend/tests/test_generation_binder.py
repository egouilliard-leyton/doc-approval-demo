"""Phase 2 (rich-HTML) Wave 1 tests: placeholder binding. Fully offline."""

from app.pipeline.generation import bind_html

from .generation_fixtures import RICH_HTML_FIXTURE


def test_bind_html_fills_present_paths_and_skips_missing():
    outcome = bind_html(
        RICH_HTML_FIXTURE,
        {"vendor": "Acme", "line_items.0.amount": 125.0},
        None,
    )
    assert set(outcome.filled) == {"vendor", "line_items.0.amount"}
    assert "po_number" in outcome.skipped

    # Present values are stamped into their spans; the missing path renders empty.
    assert "Acme" in outcome.html
    assert "125.0" in outcome.html
    assert ">PO<" not in outcome.html  # placeholder text cleared, not left in place


def test_bind_html_removes_signature_when_no_bytes():
    outcome = bind_html(RICH_HTML_FIXTURE, {}, None)
    assert outcome.signature_stamped is False
    assert "data-signature" not in outcome.html  # <img> dropped entirely


def test_bind_html_stamps_signature_as_data_uri():
    outcome = bind_html(RICH_HTML_FIXTURE, {"vendor": "Acme"}, b"\x89PNG-fake-bytes")
    assert outcome.signature_stamped is True
    assert "data:image/png;base64," in outcome.html
