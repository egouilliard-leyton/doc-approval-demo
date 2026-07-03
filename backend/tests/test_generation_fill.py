"""Phase 1 (form-fill) Wave 4 tests: fill + signature stamp + generate. Fully offline."""

import io
from types import SimpleNamespace

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from app import storage
from app.db import engine
from app.main import app
from app.models import PipelineRun, _new_id
from app.pipeline.generation import generate_pdf
from sqlmodel import Session

from .generation_fixtures import make_fillable_pdf


def _fv(value):
    return {"value": value, "confidence": 0.9, "grounding": None}


# A dumped InvoiceFields-shaped blob (FieldValue leaves keyed value/confidence/grounding).
STRUCTURED_FIELDS = {
    "vendor": _fv("Acme Supplies Inc."),
    "total": _fv(135.0),
    "currency": _fv("USD"),
    "bank_details_present": _fv(True),
    "po_number": _fv(None),  # absent -> a bound field resolving here must be skipped
    "line_items": [{"desc": _fv("Widget"), "amount": _fv(125.0)}],
}

# Binds every fixture form field: text, text-number, checkbox, choice, signature.
FIELD_MAP = {
    "vendor_name": {"field_path": "vendor", "is_signature": False},
    "total_amount": {"field_path": "total", "is_signature": False},
    "approved": {"field_path": "bank_details_present", "is_signature": False},
    "currency": {"field_path": "currency", "is_signature": False},
    "Signature": {"field_path": None, "is_signature": True},
}


def _signature_png() -> bytes:
    im = Image.new("RGB", (200, 60), (255, 255, 255))
    for x in range(200):
        im.putpixel((x, 30), (0, 0, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _create_form_template(client: TestClient) -> str:
    resp = client.post("/templates", json={"name": "T1", "doc_type": "invoice"})
    tid = resp.json()["id"]
    client.post(
        f"/templates/{tid}/source",
        files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
    )
    # Wave 3: an AI/heuristic suggestion pass (offline mock) precedes the manual bind.
    assert client.post(f"/templates/{tid}/suggest-mapping").status_code == 200
    put = client.put(f"/templates/{tid}", json={"form_field_map": FIELD_MAP})
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


def test_generate_fills_values_and_stamps_signature():
    with TestClient(app) as client:
        tid = _create_form_template(client)
        doc_id = _stash_structured_doc()

        # 1) Generate WITHOUT a signature image.
        resp = client.post(
            f"/templates/{tid}/generate", params={"document_id": doc_id, "flatten": True}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert set(body["filled_fields"]) == {"vendor_name", "total_amount", "approved", "currency"}
        assert body["signature_stamped"] is False
        # A bound signature with no supplied image is noted, not stamped.
        assert any("signature" in w.lower() for w in body["warnings"])

        # The output PDF exists on disk and its mapped values read back via pypdf.
        out_path = storage.template_outputs_dir(tid) / f"{body['output_id']}.pdf"
        assert out_path.exists()
        got = PdfReader(str(out_path)).get_fields()
        assert got["vendor_name"]["/V"] == "Acme Supplies Inc."
        assert got["total_amount"]["/V"] == "135.0"
        assert got["currency"]["/V"] == "USD"
        assert got["approved"]["/V"] == "/Yes"  # truthy value -> checkbox on-state

        # 2) Generate WITH a signature image -> stamped.
        resp2 = client.post(
            f"/templates/{tid}/generate",
            params={"document_id": doc_id, "flatten": True},
            files={"signature_image": ("sig.png", _signature_png(), "image/png")},
        )
        assert resp2.status_code == 201, resp2.text
        assert resp2.json()["signature_stamped"] is True


def test_generate_400_when_document_has_no_structure():
    with TestClient(app) as client:
        tid = _create_form_template(client)
        resp = client.post(
            f"/templates/{tid}/generate", params={"document_id": "no-such-doc"}
        )
        assert resp.status_code == 400, resp.text


def test_generate_404_missing_template():
    with TestClient(app) as client:
        assert (
            client.post("/templates/missing/generate", params={"document_id": "x"}).status_code
            == 404
        )


def test_generate_pdf_skips_radio_and_unresolved_values():
    """Radio groups and None-valued bindings are skipped with a warning, never guessed."""
    tid = _new_id()
    storage.save_template_source(tid, ".pdf", make_fillable_pdf())
    template = SimpleNamespace(
        id=tid,
        form_fields=[
            {"name": "vendor_name", "kind": "text", "page": 1, "rect": [1, 2, 3, 4]},
            {"name": "some_radio", "kind": "radio", "page": 1, "rect": [1, 2, 3, 4],
             "options": ["A", "B"]},
        ],
        form_field_map={
            "vendor_name": {"field_path": "po_number"},  # value is None -> skip
            "some_radio": {"field_path": "total"},  # radio -> skip in Phase 1
        },
    )

    outcome = generate_pdf(template, STRUCTURED_FIELDS, None, flatten=True)

    assert "vendor_name" in outcome.skipped
    assert "some_radio" in outcome.skipped
    assert outcome.filled == []
    assert any("radio" in w.lower() for w in outcome.warnings)
