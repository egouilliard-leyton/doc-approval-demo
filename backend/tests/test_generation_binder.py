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


def test_bind_html_leaves_hidden_anchor_when_no_bytes():
    """No stamp image: the <img> is replaced by an INVISIBLE signature anchor so a later
    digital signature can be placed exactly where the author marked it."""
    from app.pipeline.signing.base import SIGNATURE_ANCHOR_TOKEN

    outcome = bind_html(RICH_HTML_FIXTURE, {}, None)
    assert outcome.signature_stamped is False  # no visible stamp image
    assert "<img" not in outcome.html  # the placeholder image is gone
    assert 'data-sig-anchor="true"' in outcome.html  # ...replaced by the hidden anchor
    assert SIGNATURE_ANCHOR_TOKEN in outcome.html


def test_bind_html_stamps_signature_as_data_uri():
    outcome = bind_html(RICH_HTML_FIXTURE, {"vendor": "Acme"}, b"\x89PNG-fake-bytes")
    assert outcome.signature_stamped is True
    assert "data:image/png;base64," in outcome.html
