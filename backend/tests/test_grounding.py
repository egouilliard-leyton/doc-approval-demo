"""Unit tests for span grounding — proximity-aware re-anchoring in ``_ground``.

These exercise the grounding helpers directly (offline, no langextract, no network).
LangExtract reports ``char_start``/``char_end`` as full-document-global offsets, so a
repeated token in a long doc must re-anchor to the occurrence nearest that hint rather
than the first ``str.find`` match. The mock provider supplies no offsets, so the no-hint
path must degrade to today's first-match behavior with alignment ``"exact"``.
"""

from __future__ import annotations

from app.extraction.base import (
    FlatExtraction,
    GroundingCtx,
    _find_nearest,
    _ground,
    ground_field,
)
from app.models import DocumentStatus
from app.schemas import OCRPage, OCRResult

# "Total is" recurs on page 1 and page 3; page 2 keeps the token off those pages.
PAGE_1 = "Total is 100"
PAGE_2 = "nothing here now"
PAGE_3 = "Total is 300"
FULL_TEXT = f"{PAGE_1}\n\n{PAGE_2}\n\n{PAGE_3}"
# Verbatim offsets of "Total" within FULL_TEXT: page 1 at 0, page 3 re-anchored below.
P1_TOTAL = FULL_TEXT.find("Total")
P3_TOTAL = FULL_TEXT.find("Total", P1_TOTAL + 1)


def _ctx(pages: list[OCRPage], full_text: str) -> GroundingCtx:
    """A GroundingCtx over a mock OCR result (per-page confidence as supplied)."""
    ocr = OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="mock",
        engine_version="1",
        device="cpu",
        full_text=full_text,
        pages=pages,
    )
    return GroundingCtx(full_text=full_text, ocr_result=ocr)


def test_proximity_prefers_occurrence_nearest_hint():
    """Hint near the page-3 occurrence (not exactly quoting) resolves to page 3."""
    pages = [
        OCRPage(page=1, text=PAGE_1, blocks=[], tables=[]),
        OCRPage(page=2, text=PAGE_2, blocks=[], tables=[]),
        OCRPage(page=3, text=PAGE_3, blocks=[], tables=[]),
    ]
    ctx = _ctx(pages, FULL_TEXT)
    # Hint sits just past the page-3 occurrence, so [char_start:char_end] != "Total".
    flat = FlatExtraction(
        cls="total", text="Total", char_start=P3_TOTAL + 2, char_end=P3_TOTAL + 7
    )
    grounding, _confidence = ground_field(flat, ctx)
    assert grounding.char_start == P3_TOTAL  # not the page-1 occurrence at P1_TOTAL
    assert grounding.char_start != P1_TOTAL
    assert grounding.page == 3
    assert grounding.alignment == "partial"


def test_tie_break_prefers_earlier_offset():
    """Hint equidistant between two occurrences -> the earlier (smaller) offset wins."""
    # "Total" at offset 0 and at offset 20; a hint at 10 is equidistant from both.
    full_text = "Total" + "x" * 15 + "Total"
    assert full_text.find("Total", 1) == 20
    assert _find_nearest("Total", full_text, 10) == 0


def test_no_hint_returns_first_occurrence_exact():
    """No provider offset (mock) with a repeated token -> first match, exact."""
    cs, ce, alignment = _ground("Total", FULL_TEXT, None, None)
    assert (cs, ce) == (P1_TOTAL, P1_TOTAL + len("Total"))
    assert alignment == "exact"


def test_exact_quote_fast_path_unchanged():
    """Provider offsets that actually quote the span are trusted as exact."""
    cs, ce, alignment = _ground("Total", FULL_TEXT, P3_TOTAL, P3_TOTAL + len("Total"))
    assert (cs, ce) == (P3_TOTAL, P3_TOTAL + len("Total"))
    assert alignment == "exact"


def test_hint_not_exact_unique_token_is_partial():
    """A near-miss hint on a unique token still grounds, reported as partial."""
    idx = FULL_TEXT.find("nothing")
    cs, ce, alignment = _ground("nothing", FULL_TEXT, idx + 3, idx + 10)
    assert (cs, ce) == (idx, idx + len("nothing"))
    assert alignment == "partial"


def test_absent_and_empty_text_are_ungrounded():
    """Text not present -> ungrounded; empty text -> ungrounded (find convention)."""
    assert _ground("zzz", FULL_TEXT, None, None) == (None, None, "ungrounded")
    assert _ground("", FULL_TEXT, None, None) == (None, None, "ungrounded")


def test_page_confidence_follows_reanchored_page():
    """Confidence reflects the re-anchored page's OCR confidence, not page 1's."""
    p1 = "Total is 100"
    p2 = "Total is 300"
    full_text = f"{p1}\n\n{p2}"
    p2_total = full_text.find("Total", 1)
    pages = [
        OCRPage(page=1, text=p1, blocks=[], tables=[], avg_confidence=0.9),
        OCRPage(page=2, text=p2, blocks=[], tables=[], avg_confidence=0.5),
    ]
    ctx = _ctx(pages, full_text)
    # Hint near the page-2 occurrence, not exactly quoting -> re-anchors to page 2.
    flat = FlatExtraction(
        cls="total", text="Total", char_start=p2_total + 2, char_end=p2_total + 7
    )
    grounding, confidence = ground_field(flat, ctx)
    assert grounding.page == 2
    # partial base (0.7) * page-2 confidence (0.5) = 0.35, not page-1's 0.7 * 0.9.
    assert confidence == 0.35
