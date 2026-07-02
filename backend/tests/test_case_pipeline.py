"""Phase 2 case-pipeline HTTP e2e tests. Offline (mock provider, no network).

Exercises the case reconcile + decide stage endpoints and the stateless classify route,
end-to-end through ``TestClient``. Mirrors ``test_cases.py``'s ``_structured`` recipe
(upload -> OCR ?engine=mock -> structure ?provider=mock).
"""

from fastapi.testclient import TestClient

from app.main import app

from .conftest import SAMPLES


def _upload(client: TestClient, sample: str, doc_type: str | None = None) -> str:
    data: dict = {}
    if doc_type is not None:
        data["doc_type"] = doc_type
    with (SAMPLES / sample).open("rb") as fh:
        resp = client.post("/documents", files={"file": (sample, fh)}, data=data)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _structured(client: TestClient, sample: str, doc_type: str) -> str:
    """Upload -> OCR(mock) -> structure(mock) a document of ``doc_type``; return its id."""
    doc_id = _upload(client, sample, doc_type=doc_type)
    assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200
    r = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": doc_type, "provider": "mock", "ocr_engine": "mock"},
    )
    assert r.status_code == 200, r.text
    return doc_id


def _ap_match_case(client: TestClient) -> tuple[str, str, str, str]:
    """An ap_match case with a structured invoice + contract and a present (unstructured) PO.

    The PO satisfies ap_match's ``min_count=1`` completeness requirement (present but
    unstructured -> advisory only), so a clean, agreeing case can auto-approve.
    """
    case_id = client.post("/cases", json={"case_type": "ap_match", "label": "3-way"}).json()["id"]
    inv_id = _structured(client, "invoice-clean.pdf", "invoice")
    con_id = _structured(client, "contract-standard.pdf", "contract")
    po_id = _upload(client, "invoice-clean.pdf", doc_type="po")
    for doc_id in (inv_id, con_id, po_id):
        assert client.post(f"/cases/{case_id}/documents/{doc_id}").status_code == 200
    return case_id, inv_id, con_id, po_id


def test_reconcile_and_decide_happy_path():
    with TestClient(app) as client:
        case_id, _inv, _con, _po = _ap_match_case(client)

        recon = client.post(f"/cases/{case_id}/reconcile")
        assert recon.status_code == 200, recon.text
        fields = {f["name"]: f for f in recon.json()["canonical_fields"]}
        assert fields, "expected canonical fields"
        assert fields["total_amount"]["agreement"] is True
        assert fields["vendor_name"]["agreement"] is True

        decide = client.post(f"/cases/{case_id}/decide", params={"provider": "mock"})
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["decision"] == "approve"
        assert body["status"] == "decided"
        assert body["checks"], "expected a cross-document check trace"

        # GET twins return the persisted results without recomputing.
        got_recon = client.get(f"/cases/{case_id}/reconcile")
        assert got_recon.status_code == 200, got_recon.text
        assert got_recon.json()["canonical_fields"] == recon.json()["canonical_fields"]
        got_decide = client.get(f"/cases/{case_id}/decide")
        assert got_decide.status_code == 200, got_decide.text
        assert got_decide.json()["decision"] == "approve"


def test_conflict_path_routes_to_needs_review():
    with TestClient(app) as client:
        case_id, _inv, con_id, _po = _ap_match_case(client)

        # Force a deterministic total conflict: push the contract total far from the invoice's.
        patched = client.patch(
            f"/documents/{con_id}/structure/field",
            json={"path": "total_value", "value": 999999.0},
        )
        assert patched.status_code == 200, patched.text

        recon = client.post(f"/cases/{case_id}/reconcile")
        assert recon.status_code == 200, recon.text
        total = next(f for f in recon.json()["canonical_fields"] if f["name"] == "total_amount")
        assert total["agreement"] is False
        assert total["conflict_detail"]

        decide = client.post(f"/cases/{case_id}/decide", params={"provider": "mock"})
        assert decide.status_code == 200, decide.text
        body = decide.json()
        assert body["decision"] == "needs_review"
        assert any(c["name"] == "conflict:total_amount" and not c["passed"] for c in body["checks"])


def test_decide_requires_reconcile_409_and_get_twins_404():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"case_type": "ap_match"}).json()["id"]

        # Decide before any reconcile -> 409.
        assert client.post(f"/cases/{case_id}/decide", params={"provider": "mock"}).status_code == 409
        # GET twins before running -> 404.
        assert client.get(f"/cases/{case_id}/reconcile").status_code == 404
        assert client.get(f"/cases/{case_id}/decide").status_code == 404


def test_reconcile_empty_open_pile_is_200_with_no_fields():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "empty"}).json()["id"]  # open pile
        recon = client.post(f"/cases/{case_id}/reconcile")
        assert recon.status_code == 200, recon.text
        assert recon.json()["canonical_fields"] == []


def test_case_pipeline_missing_case_404():
    with TestClient(app) as client:
        assert client.post("/cases/missing/reconcile").status_code == 404
        assert client.get("/cases/missing/reconcile").status_code == 404
        assert client.post("/cases/missing/decide").status_code == 404
        assert client.get("/cases/missing/decide").status_code == 404


def test_classify_route():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200

        resp = client.post(f"/documents/{doc_id}/classify", params={"ocr_engine": "mock"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["document_id"] == doc_id
        assert body["provider"] == "heuristic"
        assert isinstance(body["candidates"], list)


def test_classify_requires_ocr_409():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")  # OCR deliberately skipped
        resp = client.post(f"/documents/{doc_id}/classify", params={"ocr_engine": "mock"})
        assert resp.status_code == 409, resp.text


def test_classify_missing_document_404():
    with TestClient(app) as client:
        assert client.post("/documents/missing/classify").status_code == 404
