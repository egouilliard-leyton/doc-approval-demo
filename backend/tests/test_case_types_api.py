"""Phase 1 case-type CRUD tests. Offline (no network, no pipeline)."""

from fastapi.testclient import TestClient

from app import case_types
from app.main import app


def _create_body(name: str) -> dict:
    """A minimal custom case type: two required members + one optional."""
    return {
        "name": name,
        "label": name.replace("_", " ").title(),
        "icon": "",
        "members": [
            {"doc_type": "invoice", "min_count": 1, "max_count": 1, "label": "Invoice"},
            {"doc_type": "po", "min_count": 1, "max_count": 1, "label": "PO"},
            {"doc_type": "contract", "min_count": 0, "max_count": 1, "label": "Contract"},
        ],
        "canonical_fields": {},
    }


def test_list_includes_builtin_ap_match():
    with TestClient(app) as client:
        resp = client.get("/case-types")
        assert resp.status_code == 200, resp.text
        by_name = {row["name"]: row for row in resp.json()}
        assert "ap_match" in by_name
        assert by_name["ap_match"]["builtin"] is True
        assert by_name["ap_match"]["label"] == "AP 3-Way Match"
        member_types = {m["doc_type"] for m in by_name["ap_match"]["members"]}
        assert member_types == {"invoice", "po", "contract", "delivery_note"}


def test_get_single_and_404():
    with TestClient(app) as client:
        got = client.get("/case-types/ap_match")
        assert got.status_code == 200, got.text
        assert got.json()["name"] == "ap_match"
        assert client.get("/case-types/nope").status_code == 404


def test_create_valid_custom_type_and_registered():
    name = "two_way_match_create"
    with TestClient(app) as client:
        resp = client.post("/case-types", json=_create_body(name))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["builtin"] is False
        assert body["version"] == 1
        assert len(body["members"]) == 3

        got = client.get(f"/case-types/{name}")
        assert got.status_code == 200, got.text
        assert case_types.is_registered(name)


def test_create_duplicate_409():
    name = "two_way_match_dupe"
    with TestClient(app) as client:
        assert client.post("/case-types", json=_create_body(name)).status_code == 201
        assert client.post("/case-types", json=_create_body(name)).status_code == 409


def test_delete_builtin_403():
    with TestClient(app) as client:
        assert client.delete("/case-types/ap_match").status_code == 403


def test_delete_custom_type():
    name = "two_way_match_delete"
    with TestClient(app) as client:
        assert client.post("/case-types", json=_create_body(name)).status_code == 201
        assert client.delete(f"/case-types/{name}").status_code == 204
        assert client.get(f"/case-types/{name}").status_code == 404


def test_delete_in_use_409():
    name = "two_way_match_inuse"
    with TestClient(app) as client:
        assert client.post("/case-types", json=_create_body(name)).status_code == 201

        created = client.post("/cases", json={"case_type": name, "label": "c1"})
        assert created.status_code == 201, created.text

        resp = client.delete(f"/case-types/{name}")
        assert resp.status_code == 409, resp.text
