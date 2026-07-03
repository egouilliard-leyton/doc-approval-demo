"""Offline tests for correction few-shot injection in run_structuring (no network).

Mock provider stays byte-identical regardless of corrections; the langextract path
folds the corrected values into ``spec.examples_factory()`` when (and only when) the
flag is on and there are usable corrections.
"""

from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.extraction.base import FlatExtraction
from app.models import Document, DocumentStatus
from app.pipeline import structuring
from app.pipeline.structuring import run_structuring
from app.schemas import FieldCorrection, OCRBlock, OCRPage, OCRResult


def _ocr() -> OCRResult:
    block = OCRBlock(page=1, text="Vendor: Acme Corp", bbox=(0.0, 0.0, 1.0, 1.0), label="text")
    page = OCRPage(page=1, text=block.text, blocks=[block], tables=[])
    return OCRResult(
        document_id="x",
        status=DocumentStatus.ocr_done,
        engine_name="docling",
        engine_version="1",
        device="cpu",
        full_text=page.text,
        pages=[page],
    )


def _correction(field_path: str, new_value: str) -> FieldCorrection:
    when = datetime(2026, 1, 1, 12, 0, 0)
    return FieldCorrection(
        document_id="doc-1",
        doc_type="invoice",
        field_path=field_path,
        original_value="old",
        new_value=new_value,
        created_at=when,
        updated_at=when,
    )


def test_mock_identical_with_and_without_corrections():
    doc = Document(id="doc-1", filename="f.pdf", mime="application/pdf")
    base = run_structuring(doc, _ocr(), "invoice", provider="mock")
    with_corr = run_structuring(
        doc, _ocr(), "invoice", provider="mock", corrections=[_correction("invoice_no", "INV-9")]
    )
    assert with_corr.fields == base.fields


def _capture_factory_texts(monkeypatch, corrections, *, enabled=True):
    """Run the langextract path with a canned extractor, returning the example texts
    the (possibly augmented) ``examples_factory`` produced."""
    monkeypatch.setattr(settings, "few_shot_corrections_enabled", enabled)
    monkeypatch.setattr(structuring.storage, "save_structure_artifact", lambda *a, **k: None)
    monkeypatch.setattr(structuring.storage, "structure_artifact_url", lambda *a, **k: None)

    captured: dict = {}

    def _fake_langextract(spec, text: str):
        captured["examples"] = spec.examples_factory()
        return [FlatExtraction(cls="vendor", text="Acme Corp")], "artifact"

    monkeypatch.setattr(structuring, "_structure_langextract", _fake_langextract)

    doc = Document(id="doc-1", filename="f.pdf", mime="application/pdf")
    run_structuring(doc, _ocr(), "invoice", provider="langextract", corrections=corrections)
    return [ex.text for ex in captured["examples"]]


def test_correction_example_present_with_corrections(monkeypatch):
    texts = _capture_factory_texts(monkeypatch, [_correction("invoice_no", "INV-9")])
    assert "Invoice No: INV-9" in texts


def test_correction_example_absent_when_none(monkeypatch):
    texts = _capture_factory_texts(monkeypatch, None)
    assert not any("INV-9" in t for t in texts)


def test_correction_example_absent_when_empty(monkeypatch):
    texts = _capture_factory_texts(monkeypatch, [])
    assert not any("INV-9" in t for t in texts)


def test_correction_example_absent_when_flag_off(monkeypatch):
    texts = _capture_factory_texts(
        monkeypatch, [_correction("invoice_no", "INV-9")], enabled=False
    )
    assert not any("INV-9" in t for t in texts)
