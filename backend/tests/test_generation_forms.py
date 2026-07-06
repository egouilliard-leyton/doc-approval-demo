"""Phase 1 (form-fill) Waves 1+2 tests. Fully offline — no OCR, no network."""

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.generation import (
    enumerate_form_fields,
    field_catalogue,
    flatten_field_values,
    resolve_path,
)

from .generation_fixtures import make_fillable_pdf, make_plain_pdf

# A small dumped-InvoiceFields blob (FieldValue leaves keyed value/confidence/grounding).
_NESTED_FIELDS = {
    "vendor": {"value": "Acme Supplies Inc.", "confidence": 0.9, "grounding": None},
    "total": {"value": 135.0, "confidence": 0.8, "grounding": None},
    "po_number": {"value": None, "confidence": 0.0, "grounding": None},
    "line_items": [
        {
            "desc": {"value": "Widget", "confidence": 0.7, "grounding": None},
            "amount": {"value": 125.0, "confidence": 0.7, "grounding": None},
        }
    ],
}


# --- field catalogue ----------------------------------------------------------


def test_field_catalogue_invoice_has_scalar_and_line_item_paths():
    entries = field_catalogue("invoice")
    paths = {e.path for e in entries}
    assert entries, "expected a non-empty invoice catalogue"
    assert "vendor" in paths  # a scalar leaf
    assert "total" in paths
    assert "line_items.0.amount" in paths  # a synthesized list index leaf
    # The number heuristic tags amounts as "number", free text as "text".
    by_path = {e.path: e for e in entries}
    assert by_path["line_items.0.amount"].kind == "number"
    assert by_path["vendor"].kind == "text"
    assert by_path["line_items.0.amount"].label == "Amount"


def test_field_catalogue_contract_has_nested_and_list_paths():
    paths = {e.path for e in field_catalogue("contract")}
    assert paths, "expected a non-empty contract catalogue"
    assert "parties.0" in paths  # list[FieldValue] -> indexed leaves
    assert "termination_clause.notice_period" in paths  # nested model -> dotted path
    assert "governing_law" in paths


def test_field_catalogue_list_repeat_controls_index_count():
    paths = {e.path for e in field_catalogue("invoice", list_repeat=2)}
    assert "line_items.1.amount" in paths
    assert "line_items.2.amount" not in paths


# --- value flattening ---------------------------------------------------------


def test_flatten_field_values_produces_dotted_leaf_map():
    flat = flatten_field_values(_NESTED_FIELDS)
    assert flat["vendor"] == "Acme Supplies Inc."
    assert flat["total"] == 135.0
    assert flat["po_number"] is None
    assert flat["line_items.0.amount"] == 125.0
    assert flat["line_items.0.desc"] == "Widget"


def test_resolve_path_walks_dotted_and_indexed_paths():
    assert resolve_path(_NESTED_FIELDS, "vendor") == "Acme Supplies Inc."
    assert resolve_path(_NESTED_FIELDS, "line_items.0.amount") == 125.0
    # Misses never raise -> None.
    assert resolve_path(_NESTED_FIELDS, "line_items.5.amount") is None
    assert resolve_path(_NESTED_FIELDS, "nope") is None
    assert resolve_path(_NESTED_FIELDS, "vendor.deeper") is None


# --- AcroForm enumeration -----------------------------------------------------


def test_enumerate_form_fields_reads_kinds(tmp_path):
    pdf = tmp_path / "fillable.pdf"
    pdf.write_bytes(make_fillable_pdf())

    has_acroform, fields = enumerate_form_fields(pdf)
    assert has_acroform is True
    by_name = {f.name: f for f in fields}

    assert by_name["vendor_name"].kind == "text"
    assert by_name["approved"].kind == "checkbox"
    assert by_name["currency"].kind == "choice"
    assert by_name["currency"].options == ["USD", "EUR", "GBP"]
    # A field literally named "Signature" is forced to kind="signature".
    assert by_name["Signature"].kind == "signature"

    # Widgets are located: page is 1-based, rect is [x0, y0, x1, y1].
    vendor = by_name["vendor_name"]
    assert vendor.page == 1
    assert vendor.rect is not None and len(vendor.rect) == 4


def test_enumerate_form_fields_no_acroform(tmp_path):
    pdf = tmp_path / "plain.pdf"
    pdf.write_bytes(make_plain_pdf())

    has_acroform, fields = enumerate_form_fields(pdf)
    assert has_acroform is False
    assert fields == []


# --- source upload route ------------------------------------------------------


def _create_template(client: TestClient, doc_type: str = "invoice") -> str:
    resp = client.post("/templates", json={"name": "T1", "doc_type": doc_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_upload_source_sets_form_fill_and_populates_fields():
    with TestClient(app) as client:
        tid = _create_template(client)

        resp = client.post(
            f"/templates/{tid}/source",
            files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
        )
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["mode"] == "form_fill"
        assert detail["source_url"] is not None
        names = {f["name"] for f in detail["form_fields"]}
        assert {"vendor_name", "approved", "currency", "Signature"} <= names

        # The catalogue endpoint works for the template's doc type.
        cat = client.get(f"/templates/{tid}/catalogue")
        assert cat.status_code == 200, cat.text
        cat_paths = {e["path"] for e in cat.json()}
        assert "total" in cat_paths and "line_items.0.amount" in cat_paths


def test_upload_source_plain_pdf_stays_rich_html():
    with TestClient(app) as client:
        tid = _create_template(client)
        resp = client.post(
            f"/templates/{tid}/source",
            files={"file": ("plain.pdf", make_plain_pdf(), "application/pdf")},
        )
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        assert detail["mode"] == "rich_html"
        assert detail["form_fields"] == []


def test_upload_source_rejects_non_pdf_415():
    with TestClient(app) as client:
        tid = _create_template(client)
        resp = client.post(
            f"/templates/{tid}/source",
            files={"file": ("note.png", b"not a pdf", "image/png")},
        )
        assert resp.status_code == 415, resp.text


def test_upload_source_missing_template_404():
    with TestClient(app) as client:
        resp = client.post(
            "/templates/missing/source",
            files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
        )
        assert resp.status_code == 404, resp.text


def test_catalogue_missing_template_404():
    with TestClient(app) as client:
        assert client.get("/templates/missing/catalogue").status_code == 404
