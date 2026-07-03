"""JSONL corrections-export endpoint tests (offline: mock structuring, no network).

The test DB is shared across the session, so assertions scope to each test's own
document id rather than to global row counts.
"""

import json

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


def _correct(client: TestClient, doc_id: str, path: str, value) -> None:
    r = client.patch(f"/documents/{doc_id}/structure/field", json={"path": path, "value": value})
    assert r.status_code == 200, r.text


def _lines(resp) -> list[dict]:
    return [json.loads(line) for line in resp.content.decode().splitlines() if line]


def _mine(rows: list[dict], doc_id: str) -> list[dict]:
    return [r for r in rows if r["document_id"] == doc_id]


def test_export_raw_shape_and_headers():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        _correct(client, doc_id, "invoice_no", "INV-999")
        _correct(client, doc_id, "total", "$1,299.50")

        resp = client.get("/corrections/export")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"].startswith("application/x-ndjson")
        assert 'filename="corrections-raw.jsonl"' in resp.headers["content-disposition"]

        mine = _mine(_lines(resp), doc_id)
        assert len(mine) == 2
        for row in mine:
            assert set(row) == {
                "document_id",
                "doc_type",
                "field_path",
                "original_value",
                "new_value",
                "created_at",
                "updated_at",
            }
        assert {r["field_path"] for r in mine} == {"invoice_no", "total"}


def test_export_examples_shape_groups_by_document():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        _correct(client, doc_id, "invoice_no", "INV-999")
        _correct(client, doc_id, "total", "$1,299.50")

        resp = client.get("/corrections/export", params={"shape": "examples"})
        assert resp.status_code == 200, resp.text
        assert 'filename="corrections-examples.jsonl"' in resp.headers["content-disposition"]

        mine = _mine(_lines(resp), doc_id)
        assert len(mine) == 1  # one grouped row for this document
        row = mine[0]
        assert row["fields"] == {"invoice_no": "INV-999", "total": 1299.5}
        assert "ocr_text" not in row  # include_text defaults off


def test_export_doc_type_filter_narrows():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        _correct(client, doc_id, "invoice_no", "INV-999")

        inv = client.get("/corrections/export", params={"doc_type": "invoice"})
        inv_rows = _lines(inv)
        assert all(r["doc_type"] == "invoice" for r in inv_rows)
        assert _mine(inv_rows, doc_id)  # our doc is present under its type

        contract = client.get("/corrections/export", params={"doc_type": "contract"})
        assert _mine(_lines(contract), doc_id) == []  # not under a different type
        assert (
            'filename="corrections-raw-contract.jsonl"'
            in contract.headers["content-disposition"]
        )


def test_export_include_text_toggles_ocr_text():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)
        _correct(client, doc_id, "invoice_no", "INV-999")

        without = _mine(
            _lines(client.get("/corrections/export", params={"shape": "examples"})), doc_id
        )[0]
        assert "ocr_text" not in without

        with_text = _mine(
            _lines(
                client.get(
                    "/corrections/export",
                    params={"shape": "examples", "include_text": True},
                )
            ),
            doc_id,
        )[0]
        assert "ocr_text" in with_text
