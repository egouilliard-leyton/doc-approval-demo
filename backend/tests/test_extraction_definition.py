"""Unit/parity tests for the declarative definition interpreter.

These exercise the generic assembler directly (offline, no langextract, no network),
covering the composite / list / presence paths the route-level mock tests don't reach.
"""

from __future__ import annotations

from app.extraction.base import FlatExtraction, GroundingCtx
from app.extraction.contract import CONTRACT_DEFINITION
from app.extraction.definition import build_spec
from app.extraction.invoice import INVOICE_DEFINITION
from app.models import DocumentStatus
from app.schemas import OCRPage, OCRResult

# Spans below all appear verbatim in this text so grounding anchors them exactly.
FULL_TEXT = (
    "Either party may terminate on 60 days written notice\n"
    "Acme Corp and Beta LLC sign here\n"
    "2024-09-15\n"
    "10 x Widget @ 12.50 = 125.00\n"
    "Remit to IBAN GB29 NWBK"
)


def _ctx() -> GroundingCtx:
    """A GroundingCtx over a one-page mock OCR result (no OCR confidence -> 1.0)."""
    ocr = OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="mock",
        engine_version="1",
        device="cpu",
        full_text=FULL_TEXT,
        pages=[OCRPage(page=1, text=FULL_TEXT, blocks=[], tables=[])],
    )
    return GroundingCtx(full_text=FULL_TEXT, ocr_result=ocr)


def _assemble(definition, flats: list[FlatExtraction]) -> dict:
    spec = build_spec(definition)
    return spec.assemble(flats, _ctx()).model_dump()


def test_contract_composite_present():
    span = "Either party may terminate on 60 days written notice"
    dumped = _assemble(
        CONTRACT_DEFINITION,
        [FlatExtraction(cls="termination_clause", text=span, attributes={"notice_period": "60 days"})],
    )
    clause = dumped["termination_clause"]
    assert clause["text"]["value"] == span
    assert clause["text"]["confidence"] == 1.0
    assert clause["text"]["grounding"]["snippet"] == span
    assert clause["notice_period"]["value"] == "60 days"
    assert clause["notice_period"]["confidence"] == 1.0


def test_contract_composite_absent_is_missing_field():
    dumped = _assemble(CONTRACT_DEFINITION, [])
    clause = dumped["termination_clause"]
    for sub in ("text", "notice_period"):
        assert clause[sub]["value"] is None
        assert clause[sub]["confidence"] == 0.0
        assert clause[sub]["grounding"] is None


def test_list_scalar_parties_and_key_date_label_ignored():
    dumped = _assemble(
        CONTRACT_DEFINITION,
        [
            FlatExtraction(cls="party", text="Acme Corp"),
            FlatExtraction(cls="party", text="Beta LLC"),
            # key_date carries a label attribute that list_scalar must ignore.
            FlatExtraction(cls="key_date", text="2024-09-15", attributes={"label": "renewal"}),
        ],
    )
    assert [p["value"] for p in dumped["parties"]] == ["Acme Corp", "Beta LLC"]
    assert len(dumped["key_dates"]) == 1
    assert dumped["key_dates"][0]["value"] == "2024-09-15"  # span text, label ignored


def test_list_composite_line_item_coercion():
    span = "10 x Widget @ 12.50 = 125.00"
    dumped = _assemble(
        INVOICE_DEFINITION,
        [
            FlatExtraction(
                cls="line_item",
                text=span,
                attributes={"desc": "Widget", "qty": "10", "unit_price": "12.50", "amount": "125.00"},
            )
        ],
    )
    assert len(dumped["line_items"]) == 1
    row = dumped["line_items"][0]
    assert row["desc"]["value"] == "Widget" and isinstance(row["desc"]["value"], str)
    assert row["qty"]["value"] == 10.0 and isinstance(row["qty"]["value"], float)
    assert row["unit_price"]["value"] == 12.5 and isinstance(row["unit_price"]["value"], float)
    assert row["amount"]["value"] == 125.0 and isinstance(row["amount"]["value"], float)


def test_presence_true_and_false():
    present = _assemble(
        INVOICE_DEFINITION,
        [FlatExtraction(cls="bank_details", text="Remit to IBAN GB29 NWBK")],
    )
    assert present["bank_details_present"]["value"] is True
    assert present["bank_details_present"]["confidence"] == 1.0

    absent = _assemble(INVOICE_DEFINITION, [])
    assert absent["bank_details_present"]["value"] is False
    assert absent["bank_details_present"]["confidence"] == 0.0
    assert absent["bank_details_present"]["grounding"] is None


def test_invoice_extraction_classes():
    assert build_spec(INVOICE_DEFINITION).extraction_classes == {
        "vendor",
        "invoice_no",
        "po_number",
        "invoice_date",
        "due_date",
        "subtotal",
        "tax",
        "total",
        "currency",
        "payment_terms",
        "bank_details",
        "line_item",
    }
