"""Phase 4 (Vision QA) Wave 2 tests: render -> rasterize -> judge a template. Offline.

The ``mock`` QA provider is deterministic (fixed 2 findings, no network), and preview
render (WeasyPrint) + rasterize (pypdfium2) are both offline in this environment, so the
whole ``POST /templates/{id}/qa`` path is exercised end-to-end without an
OPENROUTER_API_KEY. Page images are read back through the ``/files`` static mount.
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine
from app.main import app
from app.models import PipelineRun, _new_id

from .generation_fixtures import make_fillable_pdf, make_plain_pdf

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

RICH_BODY = "<h1>Invoice</h1><p>Vendor: <span data-field=\"vendor\">V</span></p>"


def _fv(value):
    return {"value": value, "confidence": 0.9, "grounding": None}


STRUCTURED_FIELDS = {"vendor": _fv("Acme Supplies Inc."), "total": _fv(135.0)}


def _create_rich_template(client: TestClient, body: str | None = RICH_BODY) -> str:
    resp = client.post("/templates", json={"name": "QA T", "doc_type": "invoice"})
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]
    assert resp.json()["mode"] == "rich_html"
    if body is not None:
        put = client.put(f"/templates/{tid}", json={"html_body": body})
        assert put.status_code == 200, put.text
    return tid


def _stash_structured_doc() -> str:
    """Insert a document's latest PipelineRun carrying a mock structure result."""
    doc_id = _new_id()
    with Session(engine) as session:
        session.add(
            PipelineRun(
                document_id=doc_id,
                status="structured",
                stage_results={"structure": {"fields": STRUCTURED_FIELDS}},
            )
        )
        session.commit()
    return doc_id


# --- happy paths --------------------------------------------------------------


def test_qa_self_review_no_reference():
    with TestClient(app) as client:
        tid = _create_rich_template(client)

        resp = client.post(f"/templates/{tid}/qa", json={"provider": "mock"})
        assert resp.status_code == 201, resp.text
        report = resp.json()

        assert report["mode"] == "self_review"
        assert report["reference_image_urls"] == []
        assert report["provider_used"] == "mock"
        assert len(report["findings"]) == 2  # the mock's fixed findings

        # Every rendered page image is on the /files mount and is a real PNG.
        assert report["rendered_image_urls"]
        for url in report["rendered_image_urls"]:
            fetched = client.get(url)
            assert fetched.status_code == 200
            assert fetched.content.startswith(_PNG_MAGIC)


def test_qa_source_pdf_mode_with_pdf_source():
    with TestClient(app) as client:
        # A non-fillable PDF source flips the template to rich_html with a .pdf source.
        resp = client.post("/templates", json={"name": "QA P", "doc_type": "invoice"})
        tid = resp.json()["id"]
        up = client.post(
            f"/templates/{tid}/source",
            files={"file": ("plain.pdf", make_plain_pdf(), "application/pdf")},
        )
        assert up.status_code == 200, up.text
        assert up.json()["mode"] == "rich_html"

        got = client.post(f"/templates/{tid}/qa", json={"provider": "mock"})
        assert got.status_code == 201, got.text
        report = got.json()
        assert report["mode"] == "source_pdf"
        assert report["reference_image_urls"]
        for url in report["reference_image_urls"]:
            assert client.get(url).content.startswith(_PNG_MAGIC)


def test_qa_with_document_fills_preview():
    with TestClient(app) as client:
        tid = _create_rich_template(client)
        doc_id = _stash_structured_doc()

        resp = client.post(
            f"/templates/{tid}/qa", json={"provider": "mock", "document_id": doc_id}
        )
        assert resp.status_code == 201, resp.text
        report = resp.json()
        assert report["document_id"] == doc_id
        assert report["rendered_image_urls"]


# --- 400 matrix ---------------------------------------------------------------


def test_qa_400_form_fill_template():
    with TestClient(app) as client:
        resp = client.post("/templates", json={"name": "QA F", "doc_type": "invoice"})
        tid = resp.json()["id"]
        client.post(
            f"/templates/{tid}/source",
            files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
        )
        got = client.post(f"/templates/{tid}/qa", json={"provider": "mock"})
        assert got.status_code == 400, got.text
        assert "rich-HTML" in got.json()["detail"]


def test_qa_400_no_html_body():
    with TestClient(app) as client:
        tid = _create_rich_template(client, body=None)  # no body yet
        got = client.post(f"/templates/{tid}/qa", json={"provider": "mock"})
        assert got.status_code == 400, got.text


def test_qa_400_unknown_provider():
    with TestClient(app) as client:
        tid = _create_rich_template(client)
        got = client.post(f"/templates/{tid}/qa", json={"provider": "nope"})
        assert got.status_code == 400, got.text
        assert "Unknown qa vision provider" in got.json()["detail"]


def test_qa_400_document_without_structure():
    with TestClient(app) as client:
        tid = _create_rich_template(client)
        got = client.post(
            f"/templates/{tid}/qa", json={"provider": "mock", "document_id": "no-such-doc"}
        )
        assert got.status_code == 400, got.text


def test_qa_404_missing_template():
    with TestClient(app) as client:
        got = client.post("/templates/missing/qa", json={"provider": "mock"})
        assert got.status_code == 404, got.text
