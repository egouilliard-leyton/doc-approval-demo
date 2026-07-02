"""Offline tests for section-aware structuring (no langextract, no network).

These construct synthetic ``OCRResult``s and call the structuring internals directly —
mirroring ``test_extraction_definition.py``'s style — to cover heading detection, the
single-vs-multi section gates, the per-section field merge, and one end-to-end
``run_structuring`` pass with a canned extractor. The single-section / mock / spreadsheet
paths are proven byte-identical by the pre-existing suite; here we exercise the new split
+ merge behaviour that suite never reaches.
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.extraction import get_spec
from app.extraction.base import FlatExtraction, GroundingCtx
from app.models import Document, DocumentStatus
from app.pipeline import structuring
from app.pipeline.structuring import (
    _apply_grounding_fallback,
    _build_sections,
    _build_structuring_text,
    _detect_docling_headings,
    _detect_markdown_headings,
    _merge_section_fields,
    _normalize_for_dedup,
    run_structuring,
)
from app.schemas import FieldValue, OCRBlock, OCRPage, OCRResult


# --- synthetic OCRResult builders ---------------------------------------------


def _docling_ocr(pages_blocks: list[list[tuple[str, str]]]) -> OCRResult:
    """A Docling OCRResult from ``[[(label, text), ...], ...]`` (one list per page)."""
    pages: list[OCRPage] = []
    for page_no, blocks in enumerate(pages_blocks, start=1):
        ocr_blocks = [
            OCRBlock(page=page_no, text=text, bbox=(0.0, 0.0, 1.0, 1.0), label=label)
            for label, text in blocks
        ]
        pages.append(
            OCRPage(
                page=page_no,
                text="\n".join(b.text for b in ocr_blocks),
                blocks=ocr_blocks,
                tables=[],
            )
        )
    return OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="docling",
        engine_version="1",
        device="cpu",
        full_text="\n\n".join(p.text for p in pages),
        pages=pages,
    )


def _markdown_ocr(page_texts: list[str], engine: str = "qwen-vl") -> OCRResult:
    """A VLM-style OCRResult: one block-less page per raw-markdown text blob."""
    pages = [
        OCRPage(page=i, text=text, blocks=[], tables=[])
        for i, text in enumerate(page_texts, start=1)
    ]
    return OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name=engine,
        engine_version="1",
        device="cpu",
        full_text="\n\n".join(page_texts),
        pages=pages,
    )


def _mock_ctx(text: str) -> GroundingCtx:
    """A one-page GroundingCtx (no OCR confidence -> alignment-only 1.0 multiplier)."""
    ocr = OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="mock",
        engine_version="1",
        device="cpu",
        full_text=text,
        pages=[OCRPage(page=1, text=text, blocks=[], tables=[])],
    )
    return GroundingCtx(full_text=text, ocr_result=ocr)


def _invoice_model(flats: list[FlatExtraction], text: str):
    return get_spec("invoice").assemble(flats, _mock_ctx(text))


def _contract_model(flats: list[FlatExtraction], text: str):
    return get_spec("contract").assemble(flats, _mock_ctx(text))


# --- 1. Docling heading detection ---------------------------------------------


def test_detect_docling_headings_two_headings_across_pages():
    ocr = _docling_ocr(
        [
            [("text", "Intro line one"), ("section_header", "Overview"), ("text", "body a")],
            [("text", "more body")],
            [("section_header", "Details"), ("text", "body b")],
        ]
    )
    # Doc starts with non-heading content -> implicit preamble boundary, then each heading.
    assert _detect_docling_headings(ocr) == [
        (1, 0, None),
        (1, 1, "Overview"),
        (3, 0, "Details"),
    ]


def test_detect_docling_headings_no_headings_is_under_two():
    ocr = _docling_ocr([[("text", "a"), ("text", "b")], [("text", "c")]])
    boundaries = _detect_docling_headings(ocr)
    assert len(boundaries) < 2
    assert [b[2] for b in boundaries] == [None]  # only the doc-start preamble


# --- 2. Markdown heading detection --------------------------------------------


def test_detect_markdown_headings():
    ocr = _markdown_ocr(
        ["Preamble text\n# Section One\nbody a", "## Section Two\nbody b"]
    )
    assert _detect_markdown_headings(ocr) == [
        (1, 0, None),
        (1, 1, "Section One"),
        (2, 0, "Section Two"),
    ]


# --- 3. _build_sections gates -------------------------------------------------


def test_build_sections_no_headings_is_single_and_byte_identical():
    ocr = _docling_ocr([[("text", "just prose, no headings here at all")]])
    struct_text, page_offsets = _build_structuring_text(ocr)
    sections, warning = _build_sections(ocr, struct_text, page_offsets)
    assert warning is None
    assert len(sections) == 1
    assert sections[0].text == struct_text
    assert sections[0].page_offsets == page_offsets


def test_build_sections_spreadsheet_never_splits():
    ocr = OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="spreadsheet",
        engine_version="1",
        device="cpu",
        full_text="",
        pages=[OCRPage(page=1, text="", blocks=[], tables=[])],
    )
    struct_text, page_offsets = _build_structuring_text(ocr)
    sections, warning = _build_sections(ocr, struct_text, page_offsets)
    assert warning is None
    assert len(sections) == 1


def test_build_sections_small_doc_stays_single_even_with_headings():
    # Two real headings but the whole doc easily fits one window -> no split.
    ocr = _docling_ocr(
        [
            [("section_header", "One"), ("text", "alpha")],
            [("section_header", "Two"), ("text", "beta")],
        ]
    )
    struct_text, page_offsets = _build_structuring_text(ocr)
    assert len(struct_text) <= settings.structuring_max_char_buffer
    sections, warning = _build_sections(ocr, struct_text, page_offsets)
    assert warning is None
    assert len(sections) == 1


def test_build_sections_circuit_breaker_over_max(monkeypatch):
    monkeypatch.setattr(settings, "structuring_max_char_buffer", 5)
    monkeypatch.setattr(settings, "structuring_section_min_chars", 1)
    monkeypatch.setattr(settings, "structuring_max_sections", 2)
    ocr = _docling_ocr(
        [
            [("section_header", "H1"), ("text", "alpha alpha")],
            [("section_header", "H2"), ("text", "beta beta")],
            [("section_header", "H3"), ("text", "gamma gamma")],
        ]
    )
    struct_text, page_offsets = _build_structuring_text(ocr)
    sections, warning = _build_sections(ocr, struct_text, page_offsets)
    assert len(sections) == 1  # circuit breaker -> whole-document fallback
    assert warning is not None
    assert "candidate sections" in warning
    assert "> 2" in warning


def test_build_sections_short_section_coalesces_forward(monkeypatch):
    monkeypatch.setattr(settings, "structuring_max_char_buffer", 5)
    monkeypatch.setattr(settings, "structuring_section_min_chars", 5)
    monkeypatch.setattr(settings, "structuring_max_sections", 40)
    ocr = _docling_ocr(
        [
            [("section_header", "A"), ("text", "xxxxxxxxxxxxxxxxxxxx")],
            [("section_header", "B")],  # tiny: text is just "B" -> below min_chars
            [("section_header", "C"), ("text", "yyyyyyyyyyyyyyyyyyyy")],
        ]
    )
    struct_text, page_offsets = _build_structuring_text(ocr)
    sections, warning = _build_sections(ocr, struct_text, page_offsets)
    assert warning is None
    assert len(sections) == 2  # B folded forward into C
    merged = sections[1]
    assert merged.text.startswith("B")
    assert "yyyyyyyyyyyyyyyyyyyy" in merged.text
    # Real page numbers survive the merge, offsets stay ascending.
    assert [pno for pno, _ in merged.page_offsets] == [2, 3]
    assert merged.page_offsets[0][1] < merged.page_offsets[1][1]


# --- 4. _merge_section_fields tie-breaks --------------------------------------


def test_merge_scalar_prefers_first_grounded_section():
    m1 = _invoice_model([], "nothing relevant here")  # vendor missing (grounding None)
    m2 = _invoice_model([FlatExtraction(cls="vendor", text="Acme Corp Ltd")], "Acme Corp Ltd")
    merged = _merge_section_fields([m1, m2])
    assert merged.vendor.value == "Acme Corp Ltd"
    assert merged.vendor.grounding is not None


def test_merge_presence_grounding_predicate_not_value():
    """Regression guard: absent presence is value=False (non-null) but grounding=None."""
    m1 = _invoice_model([], "no bank info in this section")
    m2 = _invoice_model(
        [FlatExtraction(cls="bank_details", text="Remit to IBAN GB29 NWBK 1234")],
        "Remit to IBAN GB29 NWBK 1234",
    )
    # Section 1 already has a non-null value (False); only `grounding is None` reveals it
    # as "found nothing", so the later grounded True must win.
    assert m1.bank_details_present.value is False
    assert m1.bank_details_present.grounding is None
    merged = _merge_section_fields([m1, m2])
    assert merged.bank_details_present.value is True
    assert merged.bank_details_present.grounding is not None


def test_merge_list_items_concatenate_in_order():
    m1 = _invoice_model(
        [
            FlatExtraction(
                cls="line_item",
                text="10 x Widget @ 12.50 = 125.00",
                attributes={"desc": "Widget", "qty": "10", "unit_price": "12.50", "amount": "125.00"},
            )
        ],
        "10 x Widget @ 12.50 = 125.00",
    )
    m2 = _invoice_model(
        [
            FlatExtraction(
                cls="line_item",
                text="2 x Gadget @ 5.00 = 10.00",
                attributes={"desc": "Gadget", "qty": "2", "unit_price": "5.00", "amount": "10.00"},
            )
        ],
        "2 x Gadget @ 5.00 = 10.00",
    )
    merged = _merge_section_fields([m1, m2])
    assert [row.desc.value for row in merged.line_items] == ["Widget", "Gadget"]


def test_merge_composite_is_atomic_first_grounded_wins():
    t1 = "Either party may terminate on 30 days written notice"
    t2 = "Company may terminate on 60 days written notice"
    m1 = _contract_model(
        [FlatExtraction(cls="termination_clause", text=t1, attributes={"notice_period": "30 days"})],
        t1,
    )
    m2 = _contract_model(
        [FlatExtraction(cls="termination_clause", text=t2, attributes={"notice_period": "60 days"})],
        t2,
    )
    merged = _merge_section_fields([m1, m2])
    # Both sub-fields come from section 1 (first grounded) — never text from one section
    # and notice_period from another.
    assert merged.termination_clause.text.value == t1
    assert merged.termination_clause.notice_period.value == "30 days"


def test_merge_composite_absent_then_present():
    t2 = "Company may terminate on 60 days written notice"
    m1 = _contract_model([], "no termination clause in this section at all")
    m2 = _contract_model(
        [FlatExtraction(cls="termination_clause", text=t2, attributes={"notice_period": "60 days"})],
        t2,
    )
    merged = _merge_section_fields([m1, m2])
    assert merged.termination_clause.text.value == t2
    assert merged.termination_clause.notice_period.value == "60 days"


def test_merge_composite_missing_attribute_stays_atomic():
    # Section 1 has the clause but the model OMITTED notice_period (attribute ->
    # missing_field, grounding=None); section 2 has a different clause WITH a notice
    # period. The whole composite must come from section 1 (first grounded) — the
    # merge must NOT graft section 2's notice_period onto section 1's text. This is the
    # per-sub-field-recursion "Frankenstein" regression.
    t1 = "Either party may terminate for cause"
    t2 = "Company may terminate on 60 days written notice"
    m1 = _contract_model(
        [FlatExtraction(cls="termination_clause", text=t1, attributes={})],
        t1,
    )
    m2 = _contract_model(
        [FlatExtraction(cls="termination_clause", text=t2, attributes={"notice_period": "60 days"})],
        t2,
    )
    merged = _merge_section_fields([m1, m2])
    assert merged.termination_clause.text.value == t1
    # notice_period stays absent — NOT grafted from section 2.
    assert merged.termination_clause.notice_period.value is None


# --- 5. run_structuring end-to-end (langextract path, canned extractor) --------


def test_run_structuring_splits_merges_and_maps_real_pages(monkeypatch):
    monkeypatch.setattr(settings, "structuring_max_char_buffer", 5)
    monkeypatch.setattr(settings, "structuring_section_min_chars", 1)
    monkeypatch.setattr(settings, "structuring_max_sections", 40)
    # Keep the artifact save fully in-memory / offline.
    monkeypatch.setattr(structuring.storage, "save_structure_artifact", lambda *a, **k: None)
    monkeypatch.setattr(structuring.storage, "structure_artifact_url", lambda *a, **k: None)

    ocr = _docling_ocr(
        [
            [
                ("section_header", "Billing"),
                ("text", "Vendor: Acme Corp"),
                ("text", "invoice ref 1"),
            ],
            [("section_header", "Summary"), ("text", "Total due 999.00")],
        ]
    )

    def _fake_langextract(spec, text: str):
        if "Acme" in text:
            return [FlatExtraction(cls="vendor", text="Acme Corp")], "artifact-vendor"
        if "999" in text:
            return [FlatExtraction(cls="total", text="999.00")], "artifact-total"
        return [], ""

    monkeypatch.setattr(structuring, "_structure_langextract", _fake_langextract)

    doc = Document(id="doc-1", filename="f.pdf", mime="application/pdf")
    result = run_structuring(doc, ocr, "invoice", provider="langextract")

    # Merged fields drawn from their respective sections.
    assert result.fields["vendor"]["value"] == "Acme Corp"
    assert result.fields["total"]["value"] == 999.0
    # Grounding reflects the REAL page each span lives on (page 1 vendor, page 2 total).
    assert result.grounding_map["vendor"].page == 1
    assert result.grounding_map["total"].page == 2
    # The demo-visible split signal is present.
    assert any("split into 2 sections" in w for w in result.warnings)


def test_run_structuring_kill_switch_single_section(monkeypatch):
    monkeypatch.setattr(settings, "structuring_max_char_buffer", 5)
    monkeypatch.setattr(settings, "structuring_sectioning", False)
    monkeypatch.setattr(structuring.storage, "save_structure_artifact", lambda *a, **k: None)
    monkeypatch.setattr(structuring.storage, "structure_artifact_url", lambda *a, **k: None)

    ocr = _docling_ocr(
        [
            [("section_header", "Billing"), ("text", "Vendor: Acme Corp")],
            [("section_header", "Summary"), ("text", "Total due 999.00")],
        ]
    )
    calls: list[str] = []

    def _fake_langextract(spec, text: str):
        calls.append(text)
        return [FlatExtraction(cls="vendor", text="Acme Corp")], "artifact"

    monkeypatch.setattr(structuring, "_structure_langextract", _fake_langextract)

    doc = Document(id="doc-2", filename="f.pdf", mime="application/pdf")
    result = run_structuring(doc, ocr, "invoice", provider="langextract")

    # Kill switch -> one whole-document extraction call, no split warning.
    assert len(calls) == 1
    assert not any("split into" in w for w in result.warnings)


# --- 6. cross-section list dedup (opt-in per FieldDef.dedup) -------------------


def _two_party_contract_sections():
    """Two contract section models: same Acme + same Beta party in each, Acme role-tagged.

    ``"Acme Robotics Inc."`` (section 1) and ``"ACME ROBOTICS INC. (Provider)"`` (section
    2) normalize to the same dedup key; ``"Beta LLC"`` appears verbatim in both. So the
    concatenation is 4 parties spanning 2 distinct normalized keys.
    """
    m1 = _contract_model(
        [
            FlatExtraction(cls="party", text="Acme Robotics Inc."),
            FlatExtraction(cls="party", text="Beta LLC"),
        ],
        "Acme Robotics Inc. and Beta LLC entered this agreement",
    )
    m2 = _contract_model(
        [
            FlatExtraction(cls="party", text="ACME ROBOTICS INC. (Provider)"),
            FlatExtraction(cls="party", text="Beta LLC"),
        ],
        "ACME ROBOTICS INC. (Provider) and Beta LLC are bound hereby",
    )
    return m1, m2


def test_merge_dedup_collapses_normalized_duplicates_keeping_first():
    m1, m2 = _two_party_contract_sections()
    merged = _merge_section_fields([m1, m2], dedup_fields={"parties"})
    # Two normalized keys survive; the kept items are section 1's (document-order first).
    assert [p.value for p in merged.parties] == ["Acme Robotics Inc.", "Beta LLC"]
    assert merged.parties[0].grounding is not None
    assert merged.parties[0].grounding.char_start is not None  # grounded in section 1
    assert merged.parties[1].grounding is not None


def test_merge_without_dedup_keeps_all_items():
    m1, m2 = _two_party_contract_sections()
    merged = _merge_section_fields([m1, m2])  # dedup opt-in, off by default
    assert [p.value for p in merged.parties] == [
        "Acme Robotics Inc.",
        "Beta LLC",
        "ACME ROBOTICS INC. (Provider)",
        "Beta LLC",
    ]


def test_merge_dedup_composite_list_is_defensive_noop():
    """A list of composite rows (not text FieldValues) opted into dedup passes through."""
    attrs = {"desc": "Widget", "qty": "1", "unit_price": "12.50", "amount": "12.50"}
    span = "1 x Widget @ 12.50 = 12.50"
    m1 = _invoice_model([FlatExtraction(cls="line_item", text=span, attributes=attrs)], span)
    m2 = _invoice_model([FlatExtraction(cls="line_item", text=span, attributes=attrs)], span)
    merged = _merge_section_fields([m1, m2], dedup_fields={"line_items"})
    # Identical rows across sections both survive — the guard never dedups non-text leaves.
    assert len(merged.line_items) == 2


def test_normalize_for_dedup_keys_and_negative_no_fuzzy_match():
    assert _normalize_for_dedup("Acme Robotics Inc.") == "acme robotics inc"
    assert _normalize_for_dedup("ACME ROBOTICS INC. (Provider)") == "acme robotics inc"
    assert _normalize_for_dedup("Acme Robotics Inc.") == _normalize_for_dedup(
        "ACME ROBOTICS INC. (Provider)"
    )
    # NEGATIVE: a shorter prefix is a DIFFERENT key — exact-match only, never fuzzy/substring.
    assert _normalize_for_dedup("Acme Robotics") != _normalize_for_dedup("Acme Robotics Inc")


# --- 7. whole-document grounding fallback -------------------------------------


def test_grounding_fallback_regrounds_spilled_text_leaf():
    # The REAL section-spill state, produced by assembly (not hand-built): governing_law
    # WAS extracted, but its verbatim span is absent from THIS section's text, so
    # ground_field returns a Grounding object with char_start=None / alignment="ungrounded"
    # (NOT grounding=None). This is exactly the state the old `grounding is not None` guard
    # skipped. The whole-document ctx DOES contain the span, so the fallback re-grounds it.
    span = "Delaware Superior Court"
    model = _contract_model(
        [FlatExtraction(cls="governing_law", text=span)],
        "a section that does not mention the clause at all",  # span absent -> unanchored
    )
    assert model.governing_law.value == span
    assert model.governing_law.grounding is not None  # a Grounding object exists...
    assert model.governing_law.grounding.char_start is None  # ...but it is UNANCHORED
    whole_ctx = _mock_ctx("Disputes are resolved in Delaware Superior Court under seal")
    _apply_grounding_fallback(model, whole_ctx)
    assert model.governing_law.grounding.char_start is not None  # recovered
    assert model.governing_law.confidence > 0


def test_grounding_fallback_leaves_already_grounded_field_untouched():
    model = _contract_model(
        [FlatExtraction(cls="governing_law", text="Delaware")],
        "governed by the laws of Delaware",
    )
    before = model.governing_law
    assert before.grounding is not None and before.grounding.char_start is not None
    # A whole-doc ctx that does NOT contain the span: an already-grounded leaf must stay put.
    _apply_grounding_fallback(model, _mock_ctx("totally unrelated whole-document text"))
    assert model.governing_law is before  # returned unchanged (same object)


def test_grounding_fallback_skips_presence_and_numeric_leaves():
    inv = _invoice_model([], "no bank details in this section")
    assert inv.bank_details_present.value is False
    assert inv.bank_details_present.grounding is None
    # A numeric leaf with a value but grounding=None must also be left alone.
    inv.total = FieldValue(value=1234.56, confidence=0.4, grounding=None)
    _apply_grounding_fallback(inv, _mock_ctx("bank details 1234.56 False appear here"))
    # Presence (bool) and numeric (float) values are never re-grounded (spurious matches).
    assert inv.bank_details_present.grounding is None
    assert inv.total.grounding is None


def test_grounding_fallback_skips_missing_field_none_value():
    inv = _invoice_model([], "nothing to see")
    inv.due_date = FieldValue(value=None, confidence=0.0, grounding=None)  # missing_field-like
    _apply_grounding_fallback(inv, _mock_ctx("due date 2024-01-01 is here"))
    assert inv.due_date.value is None
    assert inv.due_date.grounding is None
