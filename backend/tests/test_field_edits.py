"""Field-edit + correction-log tests (offline: mock structuring, no network)."""

from fastapi.testclient import TestClient

from app.main import app

from .conftest import SAMPLES


def _structured_invoice(client: TestClient) -> str:
    """Upload → OCR(mock) → structure(mock) an invoice; return its doc id."""
    with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
        doc_id = client.post(
            "/documents", files={"file": ("invoice-clean.pdf", fh)}
        ).json()["id"]
    assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200
    r = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "invoice", "provider": "mock", "ocr_engine": "mock"},
    )
    assert r.status_code == 200, r.text
    return doc_id


def test_edit_scalar_field_records_correction():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)

        # The mock extractor sets invoice_no to "page 1"; correct it.
        r = client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "invoice_no", "value": "INV-999"},
        )
        assert r.status_code == 200, r.text
        node = r.json()["fields"]["invoice_no"]
        assert node["value"] == "INV-999"
        assert node["edited"] is True
        assert node["original_value"] == "page 1"

        # Correction logged with original pinned.
        corr = client.get("/corrections", params={"document_id": doc_id}).json()
        assert len(corr) == 1
        assert corr[0]["field_path"] == "invoice_no"
        assert corr[0]["original_value"] == "page 1"
        assert corr[0]["new_value"] == "INV-999"

        # Re-edit keeps the original but updates new_value; still one row.
        client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "invoice_no", "value": "INV-1000"},
        )
        corr = client.get("/corrections", params={"document_id": doc_id}).json()
        assert len(corr) == 1
        assert corr[0]["original_value"] == "page 1"
        assert corr[0]["new_value"] == "INV-1000"

        # The persisted structure reflects the edit on reload.
        got = client.get(f"/documents/{doc_id}/structure").json()
        assert got["fields"]["invoice_no"]["value"] == "INV-1000"


def test_edit_numeric_field_coerces():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        r = client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "total", "value": "$1,299.50"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fields"]["total"]["value"] == 1299.5


def test_edit_line_item_cell():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        r = client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "line_items.0.desc", "value": "Corrected desc"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["fields"]["line_items"][0]["desc"]["value"] == "Corrected desc"


def test_edit_unknown_field_and_doc_404():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        assert (
            client.patch(
                f"/documents/{doc_id}/structure/field",
                json={"path": "nope", "value": "x"},
            ).status_code
            == 404
        )
        assert (
            client.patch(
                "/documents/missing/structure/field",
                json={"path": "invoice_no", "value": "x"},
            ).status_code
            == 404
        )
