"""Phase 2 classifier tests. Offline heuristic provider — no openai dep, no network."""

from app.models import Document, DocumentStatus
from app.pipeline.classify import run_classify
from app.schemas import OCRResult


def _ocr(text: str) -> OCRResult:
    """A minimal in-memory OCRResult carrying only the full_text the classifier reads."""
    return OCRResult(
        document_id="t",
        status=DocumentStatus.ocr_done,
        engine_name="mock",
        engine_version="0",
        device="cpu",
        full_text=text,
        pages=[],
    )


def _doc() -> Document:
    return Document(filename="t.pdf", mime="application/pdf")


INVOICE_TEXT = (
    "Vendor: Acme Supplies Inc.\n"
    "Invoice Number INV-2024-001   PO Number PO-5567\n"
    "Invoice Date 2024-03-01   Due Date 2024-03-31\n"
    "Line Item: 10 x Widget\n"
    "Subtotal 125.00   Tax 10.00   Total 135.00   Currency USD\n"
    "Payment Terms Net 30\n"
    "Bank Details IBAN GB29 NWBK"
)

CONTRACT_TEXT = (
    "This Agreement is made between the following parties.\n"
    "Party A: Acme Robotics Inc.   Party B: Globex Ltd.\n"
    "Effective Date 2024-01-01   Term: 12 months\n"
    "Renewal clause applies. Termination clause requires notice.\n"
    "Governing Law: Delaware.   Total Value 500000   Liability Cap 1,000,000\n"
    "Signature of authorized signatory."
)


def test_heuristic_classifies_invoice_text():
    result = run_classify(_doc(), _ocr(INVOICE_TEXT))
    assert result.provider == "heuristic"
    assert result.doc_type == "invoice"
    assert result.candidates[0].doc_type == "invoice"
    assert result.confidence > 0.0
    # candidates are a sorted, best-first ranking of every registered type.
    assert {c.doc_type for c in result.candidates} == {
        "invoice",
        "contract",
        "po",
        "delivery_note",
    }
    assert result.candidates == sorted(result.candidates, key=lambda c: -c.score)


def test_heuristic_classifies_contract_text():
    result = run_classify(_doc(), _ocr(CONTRACT_TEXT))
    assert result.doc_type == "contract"
    assert result.candidates[0].doc_type == "contract"


def test_heuristic_no_guess_on_garbage_text():
    result = run_classify(_doc(), _ocr("zzz qqq xxx foo bar baz nothing here"))
    assert result.doc_type is None
    assert result.confidence == 0.0


def test_unknown_provider_raises():
    import pytest

    with pytest.raises(ValueError):
        run_classify(_doc(), _ocr(INVOICE_TEXT), provider="nope")
