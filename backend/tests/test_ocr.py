"""Phase 3 OCR layer tests. Use the offline mock engine — no heavy ML deps."""

from fastapi.testclient import TestClient

from sqlmodel import Session

from app.db import engine
from app.main import app
from app.models import Document
from app.pipeline.ocr import run_ocr
from app.pipeline.ocr.mock import MockEngine

from .conftest import SAMPLES


def _upload(client: TestClient, name: str) -> str:
    with (SAMPLES / name).open("rb") as fh:
        resp = client.post("/documents", files={"file": (name, fh)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_ocr_route_persists_and_advances_status():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")

        post = client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
        assert post.status_code == 200, post.text
        result = post.json()
        assert result["engine_name"] == "mock"
        assert result["status"] == "ocr_done"
        assert len(result["pages"]) >= 1
        assert result["full_text"]
        assert isinstance(result["latency_ms"], int)
        assert result["table_count"] >= 1

        # Document status advanced.
        detail = client.get(f"/documents/{doc_id}").json()
        assert detail["status"] == "ocr_done"

        # GET returns the persisted result without recompute.
        got = client.get(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).json()
        assert got["engine_name"] == "mock"
        assert got["full_text"] == result["full_text"]


def test_ocr_unknown_engine_returns_400():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        resp = client.post(f"/documents/{doc_id}/ocr", params={"engine": "nope"})
        assert resp.status_code == 400, resp.text
        assert "Unknown or disabled OCR engine" in resp.json()["detail"]


def test_ocr_missing_document_returns_404():
    with TestClient(app) as client:
        assert client.post("/documents/missing/ocr", params={"engine": "mock"}).status_code == 404
        assert client.get("/documents/missing/ocr", params={"engine": "mock"}).status_code == 404


def test_get_ocr_before_run_returns_404():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        assert client.get(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 404


def test_routed_resolution_persists_under_actual_engine():
    """With no ?engine=, the document's doc type routes OCR; the result persists
    under the ACTUAL engine key, not a requested one."""
    from sqlmodel import Session

    from app.models import DocTypeDefinitionRow

    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")

        # Give this document a doc type whose preferred engine is mock, so routing
        # (no explicit ?engine=) resolves to mock.
        with Session(engine) as session:
            row = session.get(DocTypeDefinitionRow, "invoice")
            assert row is not None  # built-ins are seeded at startup
            row.preferred_ocr_engine = "mock"
            session.add(row)
            doc = session.get(Document, doc_id)
            doc.doc_type = "invoice"
            session.add(doc)
            session.commit()

        try:
            post = client.post(f"/documents/{doc_id}/ocr")  # no engine -> routed
            assert post.status_code == 200, post.text
            result = post.json()
            assert result["engine_name"] == "mock"
            # Persisted under the actual engine key.
            got = client.get(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
            assert got.status_code == 200, got.text
            assert got.json()["engine_name"] == "mock"
        finally:
            # Restore the shared built-in row so other tests are unaffected.
            with Session(engine) as session:
                row = session.get(DocTypeDefinitionRow, "invoice")
                row.preferred_ocr_engine = None
                session.add(row)
                session.commit()


def test_routed_ocr_then_structure_without_explicit_engine():
    """End-to-end: OCR routed to a NON-default engine (via the doc type's preferred
    engine), then the staged routes are called WITHOUT an ocr_engine param. They must
    find the routed OCR stage — not 409/404 against ``ocr_default_engine`` (docling)."""
    from sqlmodel import Session

    from app.config import settings
    from app.models import DocTypeDefinitionRow

    # The default engine is docling; routing sends OCR to mock. This test only holds
    # if the two differ (otherwise the default-key lookup would trivially match).
    assert settings.ocr_default_engine != "mock"

    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")

        with Session(engine) as session:
            row = session.get(DocTypeDefinitionRow, "invoice")
            assert row is not None  # built-ins are seeded at startup
            row.preferred_ocr_engine = "mock"
            session.add(row)
            doc = session.get(Document, doc_id)
            doc.doc_type = "invoice"
            session.add(doc)
            session.commit()

        try:
            # OCR with no ?engine= -> routed to mock, persisted under "mock".
            post = client.post(f"/documents/{doc_id}/ocr")
            assert post.status_code == 200, post.text
            assert post.json()["engine_name"] == "mock"

            # GET /ocr with NO engine must return the routed result (not 404 on docling).
            got = client.get(f"/documents/{doc_id}/ocr")
            assert got.status_code == 200, got.text
            assert got.json()["engine_name"] == "mock"

            # /structure with NO ocr_engine must find the mock OCR stage (not 409).
            resp = client.post(
                f"/documents/{doc_id}/structure", params={"provider": "mock"}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["doc_type"] == "invoice"
        finally:
            # Restore the shared built-in row so other tests are unaffected.
            with Session(engine) as session:
                row = session.get(DocTypeDefinitionRow, "invoice")
                row.preferred_ocr_engine = None
                session.add(row)
                session.commit()


def test_base_aggregates_pages_offline():
    """MockEngine.run reads no files, so aggregation is testable in isolation."""
    doc = Document(id="agg-test", filename="x.pdf", mime="application/pdf", page_count=2)
    with Session(engine) as session:
        result = run_ocr(doc, "mock", session)

    assert result.engine_name == "mock"
    assert len(result.pages) == 2
    # Two blocks/page at 0.97 and 0.92 -> mean 0.945; well above the warn floor.
    assert result.avg_confidence == 0.945
    assert all(p.avg_confidence == 0.945 for p in result.pages)
    assert result.table_count == 2
    assert "page 1" in result.full_text and "page 2" in result.full_text
    assert not any("low average" in w for w in result.warnings)
    assert isinstance(MockEngine().version, str)
