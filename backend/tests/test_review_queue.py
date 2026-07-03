"""Review-queue endpoint tests (offline: mock OCR + mock structuring, no network).

The queue surfaces low-confidence, unedited, non-presence leaf fields. With the mock
extractor an invoice grounds vendor/invoice_no/total at ~0.945 and currency at ~0.378;
every field the mock leaves missing (value ``None``) carries confidence 0.0. So at the
default 0.5 threshold the at-risk set is currency plus the missing fields — po_number
(0.0) among them — while the grounded ~0.945 fields and the presence-kind
bank_details_present are excluded.
"""

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


def _structured_contract(client: TestClient) -> str:
    """Upload → OCR(mock) → structure(mock) a contract; return its doc id."""
    with (SAMPLES / "contract-signed.pdf").open("rb") as fh:
        doc_id = client.post(
            "/documents", files={"file": ("contract-signed.pdf", fh)}
        ).json()["id"]
    assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200
    r = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "contract", "provider": "mock", "ocr_engine": "mock"},
    )
    assert r.status_code == 200, r.text
    return doc_id


def _doc_entry(payload: dict, doc_id: str) -> dict | None:
    """The queue entry for ``doc_id`` (shared test DB accumulates other docs)."""
    for d in payload["documents"]:
        if d["document_id"] == doc_id:
            return d
    return None


def test_invoice_low_confidence_fields_surface():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)

        payload = client.get("/review-queue").json()
        assert payload["threshold"] == 0.5
        entry = _doc_entry(payload, doc_id)
        assert entry is not None, "structured invoice should be in the review queue"

        paths = [f["path"] for f in entry["fields"]]
        confs = {f["path"]: f["confidence"] for f in entry["fields"]}

        # po_number (missing, 0.0) and currency (grounded weakly, ~0.378) are at risk.
        assert "po_number" in paths
        assert confs["po_number"] == 0.0
        assert "currency" in paths
        assert abs(confs["currency"] - 0.378) < 0.05

        # Confidently grounded fields (~0.945) are NOT surfaced.
        for grounded in ("invoice_no", "total", "vendor"):
            assert grounded not in paths

        # bank_details_present is a presence-kind field at 0.0 — excluded, not surfaced.
        assert "bank_details_present" not in paths

        # Every surfaced field is below threshold, ordered worst-first (ascending).
        assert all(c < 0.5 for c in confs.values())
        field_confs = [f["confidence"] for f in entry["fields"]]
        assert field_confs == sorted(field_confs)
        # po_number (0.0) is ordered before currency (0.378).
        assert paths.index("po_number") < paths.index("currency")

        assert entry["at_risk_count"] == len(entry["fields"])
        assert entry["lowest_confidence"] == field_confs[0]


def test_edited_field_leaves_the_queue():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)

        before = _doc_entry(client.get("/review-queue").json(), doc_id)
        assert "currency" in [f["path"] for f in before["fields"]]
        count_before = before["at_risk_count"]

        # Reviewer edits currency -> it becomes ``edited`` and drops out of the queue.
        r = client.patch(
            f"/documents/{doc_id}/structure/field",
            json={"path": "currency", "value": "EUR"},
        )
        assert r.status_code == 200, r.text

        after = _doc_entry(client.get("/review-queue").json(), doc_id)
        after_paths = [f["path"] for f in after["fields"]]
        assert "currency" not in after_paths
        assert "po_number" in after_paths  # untouched, still at risk
        assert after["at_risk_count"] == count_before - 1


def test_threshold_query_narrows_the_queue():
    with TestClient(app) as client:
        doc_id = _structured_invoice(client)

        payload = client.get("/review-queue", params={"threshold": 0.01}).json()
        assert payload["threshold"] == 0.01
        entry = _doc_entry(payload, doc_id)
        assert entry is not None
        paths = [f["path"] for f in entry["fields"]]

        # Only sub-0.01 fields remain: po_number (0.0) stays, currency (0.378) is gone.
        assert "po_number" in paths
        assert "currency" not in paths
        assert all(f["confidence"] < 0.01 for f in entry["fields"])


def test_every_queue_path_is_patchable():
    """Critical round-trip: every path the queue emits must be a valid PATCH target.

    Covers both the invoice (flat scalar paths) and the contract (whose missing
    ``termination_clause.*`` sub-fields surface at 0.0), so a nested/dotted composite
    path is exercised through PATCH — guarding the flatten↔_field_node grammar identity.
    """
    with TestClient(app) as client:
        invoice_id = _structured_invoice(client)
        contract_id = _structured_contract(client)

        payload = client.get("/review-queue").json()
        patched_a_nested_path = False
        for doc_id in (invoice_id, contract_id):
            entry = _doc_entry(payload, doc_id)
            assert entry is not None and entry["fields"]
            for field in entry["fields"]:
                r = client.patch(
                    f"/documents/{doc_id}/structure/field",
                    json={"path": field["path"], "value": field["value"]},
                )
                assert r.status_code == 200, f"{field['path']} -> {r.status_code}: {r.text}"
                if "." in field["path"]:
                    patched_a_nested_path = True

        # The contract must have contributed at least one nested (dotted) composite path,
        # so this test genuinely exercises nested-path PATCH-ability, not just flat scalars.
        assert patched_a_nested_path, "expected a nested composite path (e.g. termination_clause.*)"


def test_presence_field_never_surfaces():
    with TestClient(app) as client:
        doc_id = _structured_contract(client)

        entry = _doc_entry(client.get("/review-queue").json(), doc_id)
        assert entry is not None, "structured contract should be in the review queue"
        paths = [f["path"] for f in entry["fields"]]
        # signatures_present is presence-kind at confidence 0.0 — must never appear.
        assert "signatures_present" not in paths


def test_doc_type_filter():
    with TestClient(app) as client:
        invoice_id = _structured_invoice(client)
        contract_id = _structured_contract(client)

        inv_only = client.get("/review-queue", params={"doc_type": "invoice"}).json()
        assert _doc_entry(inv_only, invoice_id) is not None
        assert _doc_entry(inv_only, contract_id) is None
        assert all(d["doc_type"] == "invoice" for d in inv_only["documents"])

        con_only = client.get("/review-queue", params={"doc_type": "contract"}).json()
        assert _doc_entry(con_only, contract_id) is not None
        assert _doc_entry(con_only, invoice_id) is None
        assert all(d["doc_type"] == "contract" for d in con_only["documents"])
