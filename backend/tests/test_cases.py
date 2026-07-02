"""Phase 1 case CRUD + association + assembly tests. Offline (mock provider, no network)."""

from fastapi.testclient import TestClient

from app.main import app

from .conftest import SAMPLES


def _upload(client: TestClient, sample: str, doc_type: str | None = None, case_id: str | None = None) -> str:
    """Upload a sample document; return its id."""
    data: dict = {}
    if doc_type is not None:
        data["doc_type"] = doc_type
    if case_id is not None:
        data["case_id"] = case_id
    with (SAMPLES / sample).open("rb") as fh:
        resp = client.post("/documents", files={"file": (sample, fh)}, data=data)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _structured(client: TestClient, sample: str, doc_type: str) -> str:
    """Upload → OCR(mock) → structure(mock) a document of ``doc_type``; return its id."""
    doc_id = _upload(client, sample, doc_type=doc_type)
    assert client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"}).status_code == 200
    r = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": doc_type, "provider": "mock", "ocr_engine": "mock"},
    )
    assert r.status_code == 200, r.text
    return doc_id


def test_create_open_pile_case():
    with TestClient(app) as client:
        resp = client.post("/cases", json={"label": "open pile"})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["case_type"] is None
        assert body["label"] == "open pile"
        assert body["members"] == []
        assert body["id"]


def test_create_defined_case():
    with TestClient(app) as client:
        resp = client.post("/cases", json={"case_type": "ap_match", "label": "match 1"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["case_type"] == "ap_match"


def test_create_unknown_case_type_422():
    with TestClient(app) as client:
        resp = client.post("/cases", json={"case_type": "nope"})
        assert resp.status_code == 422, resp.text


def test_list_and_get_case():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "listed"}).json()["id"]
        listed = client.get("/cases")
        assert listed.status_code == 200, listed.text
        assert case_id in {c["id"] for c in listed.json()}

        got = client.get(f"/cases/{case_id}")
        assert got.status_code == 200, got.text
        assert got.json()["id"] == case_id
        assert client.get("/cases/missing").status_code == 404


def test_associate_and_detach_document():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "c"}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf")

        added = client.post(f"/cases/{case_id}/documents/{doc_id}")
        assert added.status_code == 200, added.text
        assert [m["document_id"] for m in added.json()["members"]] == [doc_id]

        # The document surfaces its case_id on its own detail view.
        assert client.get(f"/documents/{doc_id}").json()["case_id"] == case_id

        detached = client.delete(f"/cases/{case_id}/documents/{doc_id}")
        assert detached.status_code == 204, detached.text
        assert client.get(f"/cases/{case_id}").json()["members"] == []
        assert client.get(f"/documents/{doc_id}").json()["case_id"] is None


def test_detach_non_member_404():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf")
        assert client.delete(f"/cases/{case_id}/documents/{doc_id}").status_code == 404


def test_associate_missing_case_or_doc_404():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf")
        assert client.post(f"/cases/missing/documents/{doc_id}").status_code == 404
        assert client.post(f"/cases/{case_id}/documents/missing").status_code == 404


def test_reassignment_across_cases():
    with TestClient(app) as client:
        case_a = client.post("/cases", json={"label": "a"}).json()["id"]
        case_b = client.post("/cases", json={"label": "b"}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf")

        assert client.post(f"/cases/{case_a}/documents/{doc_id}").status_code == 200
        # Re-associating to case B silently reassigns (one-case-per-document).
        assert client.post(f"/cases/{case_b}/documents/{doc_id}").status_code == 200

        assert client.get(f"/cases/{case_a}").json()["members"] == []
        assert [m["document_id"] for m in client.get(f"/cases/{case_b}").json()["members"]] == [doc_id]
        assert client.get(f"/documents/{doc_id}").json()["case_id"] == case_b


def test_upload_with_case_id_form_field():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "c"}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf", case_id=case_id)
        assert [m["document_id"] for m in client.get(f"/cases/{case_id}").json()["members"]] == [doc_id]

        # Uploading with an unknown case_id is a 404.
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            resp = client.post(
                "/documents",
                files={"file": ("invoice-clean.pdf", fh)},
                data={"case_id": "missing"},
            )
        assert resp.status_code == 404, resp.text


def test_delete_case_leaves_documents():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "c"}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf", case_id=case_id)

        assert client.delete(f"/cases/{case_id}").status_code == 204
        assert client.get(f"/cases/{case_id}").status_code == 404

        # The document survives, now caseless.
        got = client.get(f"/documents/{doc_id}")
        assert got.status_code == 200, got.text
        assert got.json()["case_id"] is None
        assert client.delete("/cases/missing").status_code == 404


def test_delete_document_removes_its_membership():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"label": "c"}).json()["id"]
        doc_id = _upload(client, "invoice-clean.pdf", case_id=case_id)
        assert [m["document_id"] for m in client.get(f"/cases/{case_id}").json()["members"]] == [doc_id]

        # Deleting the document must purge its CaseMembership (no orphan rows).
        assert client.delete(f"/documents/{doc_id}").status_code == 204
        assert client.get(f"/cases/{case_id}").json()["members"] == []


def test_assembly_groups_structured_results():
    with TestClient(app) as client:
        case_id = client.post("/cases", json={"case_type": "ap_match", "label": "3-way"}).json()["id"]

        inv_id = _structured(client, "invoice-clean.pdf", "invoice")
        con_id = _structured(client, "contract-standard.pdf", "contract")

        assert client.post(f"/cases/{case_id}/documents/{inv_id}").status_code == 200
        assert client.post(f"/cases/{case_id}/documents/{con_id}").status_code == 200

        detail = client.get(f"/cases/{case_id}")
        assert detail.status_code == 200, detail.text
        members = {m["document_id"]: m for m in detail.json()["members"]}
        assert set(members) == {inv_id, con_id}

        assert members[inv_id]["structured"] is not None
        assert members[inv_id]["structured"]["doc_type"] == "invoice"
        assert members[con_id]["structured"] is not None
        assert members[con_id]["structured"]["doc_type"] == "contract"
