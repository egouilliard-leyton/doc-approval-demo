"""Pure unit tests for correction -> few-shot example synthesis (Wave 2).

Fully offline: no DB, no network, no langextract (build_correction_examples is pure).
"""

from datetime import datetime, timedelta

from app import doc_types
from app.extraction.definition import (
    _augment_examples_factory,
    build_correction_examples,
)
from app.schemas import FieldCorrection

_T0 = datetime(2026, 1, 1, 12, 0, 0)


def _correction(field_path: str, new_value, *, minutes: int = 0) -> FieldCorrection:
    when = _T0 + timedelta(minutes=minutes)
    return FieldCorrection(
        document_id="doc-1",
        doc_type="invoice",
        field_path=field_path,
        original_value="old",
        new_value=new_value,
        created_at=when,
        updated_at=when,
    )


def _defn():
    return doc_types.get_extraction_definition("invoice")


def test_scalar_correction_kept_and_verbatim():
    examples = build_correction_examples([_correction("invoice_no", "INV-9")], _defn(), 5)
    assert len(examples) == 1
    ex = examples[0]
    assert ex.extractions[0].cls == "invoice_no"
    # extraction text is the corrected value verbatim, and a substring of the source text
    assert ex.extractions[0].text == "INV-9"
    assert "INV-9" in ex.text
    assert ex.text == "Invoice No: INV-9"


def test_composite_subpath_dropped():
    # "line_items.0.desc" is not a top-level scalar field -> dropped
    examples = build_correction_examples([_correction("line_items.0.desc", "Widget")], _defn(), 5)
    assert examples == []


def test_presence_field_dropped():
    # bank_details_present is a presence field, not scalar -> dropped
    examples = build_correction_examples(
        [_correction("bank_details_present", "true")], _defn(), 5
    )
    assert examples == []


def test_empty_new_value_dropped():
    examples = build_correction_examples(
        [_correction("invoice_no", None), _correction("vendor", "")], _defn(), 5
    )
    assert examples == []


def test_dedupe_keeps_newest():
    corrections = [
        _correction("invoice_no", "OLD", minutes=0),
        _correction("invoice_no", "NEW", minutes=10),
    ]
    examples = build_correction_examples(corrections, _defn(), 5)
    assert len(examples) == 1
    assert examples[0].extractions[0].text == "NEW"


def test_cap_max_examples_newest_first():
    corrections = [
        _correction("invoice_no", "A", minutes=1),
        _correction("vendor", "B", minutes=2),
        _correction("total", "3", minutes=3),
    ]
    examples = build_correction_examples(corrections, _defn(), 2)
    assert len(examples) == 2
    # newest-first -> total (min 3) then vendor (min 2)
    classes = [e.extractions[0].cls for e in examples]
    assert classes == ["total", "vendor"]


def test_augment_examples_factory_appends_lazily():
    base = lambda: ["base-a", "base-b"]  # noqa: E731
    examples = build_correction_examples([_correction("invoice_no", "INV-9")], _defn(), 5)
    factory = _augment_examples_factory(base, examples)
    out = factory()
    # base items first, then one synthesized langextract example
    assert out[:2] == ["base-a", "base-b"]
    assert len(out) == 3
