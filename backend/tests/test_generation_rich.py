"""Phase 2 (rich-HTML) Wave 2 tests: bind + render an HTML template. Fully offline.

WeasyPrint's system libs are present in this environment so the PDF renders; the DOCX
path (html4docx) is pure-python and always available. Both are asserted end-to-end via
the TestClient, with the rendered bytes read back off disk.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app import storage
from app.db import engine
from app.main import app
from app.models import PipelineRun, _new_id
from sqlmodel import Session


def _fv(value):
    return {"value": value, "confidence": 0.9, "grounding": None}


# A dumped InvoiceFields-shaped blob: two present scalars + one absent field.
STRUCTURED_FIELDS = {
    "vendor": _fv("Acme Supplies Inc."),
    "total": _fv(135.0),
    "po_number": _fv(None),  # absent -> a bound placeholder here must be skipped
}

# A rich body carrying two fillable placeholders + one that resolves to a missing value.
RICH_BODY = (
    "<h1>Invoice</h1>"
    '<p>Vendor: <span data-field="vendor">V</span></p>'
    '<p>Total: <span data-field="total">T</span></p>'
    '<p>PO: <span data-field="po_number">PO</span></p>'
)


def _create_rich_template(client: TestClient) -> str:
    resp = client.post("/templates", json={"name": "R1", "doc_type": "invoice"})
    assert resp.status_code == 201, resp.text
    tid = resp.json()["id"]
    assert resp.json()["mode"] == "rich_html"
    put = client.put(
        f"/templates/{tid}",
        json={"html_body": RICH_BODY, "output_formats": ["pdf", "docx"]},
    )
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


def test_generate_rich_renders_pdf_and_docx():
    with TestClient(app) as client:
        tid = _create_rich_template(client)
        doc_id = _stash_structured_doc()

        resp = client.post(f"/templates/{tid}/generate", params={"document_id": doc_id})
        assert resp.status_code == 201, resp.text
        body = resp.json()

        # Both configured formats rendered, each with a distinct output id.
        formats = {o["format"] for o in body["outputs"]}
        assert formats == {"pdf", "docx"}
        assert len({o["output_id"] for o in body["outputs"]}) == 2

        # The present placeholders filled; the None-valued one skipped, never guessed.
        assert set(body["filled_fields"]) == {"vendor", "total"}
        assert "po_number" in body["skipped_fields"]

        # The top-level primary output mirrors the PDF entry.
        pdf_out = next(o for o in body["outputs"] if o["format"] == "pdf")
        assert body["output_url"] == pdf_out["output_url"]
        assert body["output_id"] == pdf_out["output_id"]

        # Every output exists on disk (nonempty) and is fetchable via the /files mount.
        for out in body["outputs"]:
            on_disk = (
                storage.template_outputs_dir(tid) / f"{out['output_id']}.{out['format']}"
            )
            assert on_disk.exists() and on_disk.stat().st_size > 0
            fetched = client.get(out["output_url"])
            assert fetched.status_code == 200
            assert fetched.content


def test_generate_rich_400_without_html_body():
    with TestClient(app) as client:
        resp = client.post("/templates", json={"name": "R2", "doc_type": "invoice"})
        tid = resp.json()["id"]
        doc_id = _stash_structured_doc()
        got = client.post(f"/templates/{tid}/generate", params={"document_id": doc_id})
        assert got.status_code == 400, got.text
        assert "html body" in got.json()["detail"].lower()
