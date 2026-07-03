"""Multi-engine OCR routing + fallback tests (offline: mock/fake engines only)."""

import pytest
from sqlmodel import Session

from app.config import settings
from app.db import engine as db_engine, init_db
from app.models import Document, DocTypeDefinitionRow


@pytest.fixture(autouse=True)
def _ensure_tables():
    """Create tables (the app lifespan does this in the served app)."""
    init_db()
from app.pipeline.ocr import (
    build_engine_objects,
    resolve_engine_chain,
    run_ocr_chain,
)
from app.pipeline.ocr.base import OCREngine
from app.pipeline.ocr.mock import MockEngine


class _AlwaysRaisingEngine(OCREngine):
    name = "fake"
    version = "0"

    def _ocr_pages(self, doc_id, pages):
        raise RuntimeError("boom")


def test_chain_falls_back_to_next_on_raise():
    doc = Document(id="route-raise", filename="x.pdf", mime="application/pdf", page_count=2)
    result = run_ocr_chain(doc, [("fake", _AlwaysRaisingEngine()), ("mock", MockEngine())])

    assert result.engine_name == "mock"
    assert result.attempted_engines == ["fake", "mock"]
    assert any("OCR fallback" in w for w in result.warnings)


def test_chain_single_engine_no_fallback_warning():
    doc = Document(id="route-single", filename="x.pdf", mime="application/pdf", page_count=1)
    result = run_ocr_chain(doc, [("mock", MockEngine())])
    assert result.attempted_engines == ["mock"]
    assert not any("OCR fallback" in w for w in result.warnings)


def test_chain_all_raise_raises_value_error():
    doc = Document(id="route-allraise", filename="x.pdf", mime="application/pdf", page_count=1)
    with pytest.raises(ValueError):
        run_ocr_chain(doc, [("fake", _AlwaysRaisingEngine()), ("fake2", _AlwaysRaisingEngine())])


def test_resolve_chain_from_doc_type_row_dedups():
    with Session(db_engine) as session:
        row = DocTypeDefinitionRow(
            name="routed-type",
            label="Routed",
            preferred_ocr_engine="mock",
            # duplicate of preferred + a real fallback -> dedup keeps order, drops dup.
            ocr_fallback_engines=["mock", "docling"],
        )
        session.add(row)
        session.commit()

        chain = resolve_engine_chain("routed-type", session)
        assert chain == ["mock", "docling"]

        session.delete(row)
        session.commit()


def test_resolve_chain_default_when_no_doc_type(monkeypatch):
    monkeypatch.setattr(settings, "ocr_default_engine", "docling")
    monkeypatch.setattr(settings, "ocr_default_fallback_engines", ["mock"])
    with Session(db_engine) as session:
        assert resolve_engine_chain(None, session) == ["docling", "mock"]
        # An unknown doc type also falls back to the default chain.
        assert resolve_engine_chain("nope", session) == ["docling", "mock"]


def test_build_engine_objects_skips_stale_names():
    with Session(db_engine) as session:
        objs = build_engine_objects(["mock", "ghost-engine", "docling"], session)
    names = [n for n, _ in objs]
    # The stale/unknown name is dropped; the real ones resolve.
    assert "ghost-engine" not in names
    assert "mock" in names and "docling" in names
