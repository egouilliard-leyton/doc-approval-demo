"""Phase 0 template registry tests: the CRUD route end-to-end."""

from fastapi.testclient import TestClient

from app.main import app


def _create(client: TestClient, name: str, doc_type: str = "invoice") -> dict:
    resp = client.post("/templates", json={"name": name, "doc_type": doc_type})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_template_defaults():
    with TestClient(app) as client:
        body = _create(client, "Invoice A")
        assert body["id"]
        assert body["status"] == "draft"
        assert body["mode"] == "rich_html"
        assert body["output_formats"] == ["pdf"]


def test_list_populated_with_doc_type_filter():
    with TestClient(app) as client:
        # The list is empty on a clean DB; the module-shared SQLite file may already
        # hold rows from earlier tests, so assert relative to a captured baseline.
        before = {t["id"] for t in client.get("/templates").json()}

        inv = _create(client, "Invoice A", "invoice")
        con = _create(client, "Contract A", "contract")

        after = {t["id"] for t in client.get("/templates").json()}
        assert after - before == {inv["id"], con["id"]}

        invoice_ids = {t["id"] for t in client.get("/templates", params={"doc_type": "invoice"}).json()}
        assert inv["id"] in invoice_ids
        assert con["id"] not in invoice_ids


def test_get_existing_and_missing():
    with TestClient(app) as client:
        tmpl = _create(client, "Invoice A")
        got = client.get(f"/templates/{tmpl['id']}")
        assert got.status_code == 200
        assert got.json()["id"] == tmpl["id"]

        assert client.get("/templates/does-not-exist").status_code == 404


def test_update_status_only():
    with TestClient(app) as client:
        tmpl = _create(client, "Invoice A")
        resp = client.put(f"/templates/{tmpl['id']}", json={"status": "ready"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ready"


def test_update_html_body_twice_snapshots_revision():
    with TestClient(app) as client:
        tmpl = _create(client, "Invoice A")

        first = client.put(f"/templates/{tmpl['id']}", json={"html_body": "<p>v1</p>"})
        assert first.status_code == 200, first.text
        assert first.json()["html_body"] == "<p>v1</p>"

        second = client.put(
            f"/templates/{tmpl['id']}",
            json={"html_body": "<p>v2</p>", "revision_note": "second edit"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["html_body"] == "<p>v2</p>"


def test_update_missing_returns_404():
    with TestClient(app) as client:
        assert client.put("/templates/does-not-exist", json={"status": "ready"}).status_code == 404


def test_delete_then_get_and_delete_missing():
    with TestClient(app) as client:
        tmpl = _create(client, "Invoice A")
        assert client.delete(f"/templates/{tmpl['id']}").status_code == 204
        assert client.get(f"/templates/{tmpl['id']}").status_code == 404
        assert client.delete("/templates/does-not-exist").status_code == 404
