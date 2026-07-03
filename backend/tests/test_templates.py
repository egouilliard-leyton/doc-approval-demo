"""Phase 0 template registry tests: the CRUD route end-to-end.

Also covers the Phase 2 source-upload branches that produce ``rich_html`` templates:
a DOCX and a non-fillable PDF both convert to a non-empty HTML body.
"""

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.generation import render_field_placeholder, sanitize_template_html
from app.storage import DOCX_MIME

from .generation_fixtures import make_docx_bytes, make_plain_pdf


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

        # Two edits -> two PRE-update snapshots, newest first: the second edit snapshotted
        # "v1" (with the note), the first edit snapshotted the original empty body.
        revs = client.get(f"/templates/{tmpl['id']}/revisions")
        assert revs.status_code == 200, revs.text
        history = revs.json()
        assert len(history) == 2
        assert history[0]["html"] == "<p>v1</p>"
        assert history[0]["note"] == "second edit"
        assert history[1]["html"] is None
        assert history[1]["note"] is None


def test_revisions_missing_returns_404():
    with TestClient(app) as client:
        assert client.get("/templates/does-not-exist/revisions").status_code == 404


def test_restore_revision_rolls_back_and_is_itself_undoable():
    with TestClient(app) as client:
        tid = _create(client, "Invoice A")["id"]
        client.put(f"/templates/{tid}", json={"html_body": "<p>A</p>"})  # snapshots blank
        client.put(f"/templates/{tid}", json={"html_body": "<p>B</p>"})  # snapshots "A"

        history = client.get(f"/templates/{tid}/revisions").json()
        # newest-first: [0] snapshot of "A" (from the B edit), [1] snapshot of blank original
        a_rev = history[0]
        assert a_rev["html"] == "<p>A</p>"

        restored = client.post(f"/templates/{tid}/revisions/{a_rev['id']}/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["html_body"] == "<p>A</p>"

        # Restore snapshotted the current ("B") state first -> it's undoable.
        after = client.get(f"/templates/{tid}/revisions").json()
        assert len(after) == 3
        assert after[0]["html"] == "<p>B</p>"


def test_restore_blank_original_clears_body_not_a_noop():
    with TestClient(app) as client:
        tid = _create(client, "Invoice A")["id"]
        client.put(f"/templates/{tid}", json={"html_body": "<p>A</p>"})  # snapshots blank(None)

        blank_rev = client.get(f"/templates/{tid}/revisions").json()[0]
        assert blank_rev["html"] is None  # the original blank state

        restored = client.post(f"/templates/{tid}/revisions/{blank_rev['id']}/restore")
        assert restored.status_code == 200, restored.text
        # None -> "" coercion: the body is cleared, not left at "<p>A</p>".
        assert restored.json()["html_body"] == ""


def test_restore_404s_for_bad_template_or_revision():
    with TestClient(app) as client:
        tid = _create(client, "Invoice A")["id"]
        client.put(f"/templates/{tid}", json={"html_body": "<p>A</p>"})
        rev_id = client.get(f"/templates/{tid}/revisions").json()[0]["id"]

        assert client.post(f"/templates/nope/revisions/{rev_id}/restore").status_code == 404
        assert client.post(f"/templates/{tid}/revisions/nope/restore").status_code == 404
        # A revision that belongs to a different template must not be restorable here.
        other = _create(client, "Invoice B")["id"]
        assert client.post(f"/templates/{other}/revisions/{rev_id}/restore").status_code == 404


def test_template_detail_surfaces_orphaned_placeholders():
    with TestClient(app) as client:
        tid = _create(client, "Invoice A")["id"]
        html = (
            '<p><span data-field="vendor">Vendor</span> '
            '<span data-field="ghost.field">Ghost</span></p>'
        )
        client.put(f"/templates/{tid}", json={"html_body": html})

        detail = client.get(f"/templates/{tid}").json()
        assert "lint" in detail
        assert detail["lint"]["orphaned_paths"] == ["ghost.field"]
        assert detail["lint"]["total_count"] == 2
        assert detail["lint"]["bound_count"] == 1


def test_sanitize_template_html_strips_active_content():
    cleaned = sanitize_template_html(
        '<p>ok<script>alert(1)</script><a href="javascript:x" onclick="y">t</a></p>'
    )
    assert "<script>" not in cleaned
    assert "alert(1)" not in cleaned
    assert "onclick" not in cleaned
    assert "javascript:" not in cleaned
    assert "<p>ok" in cleaned
    assert ">t</a>" in cleaned


def test_sanitize_template_html_none_passthrough():
    assert sanitize_template_html(None) is None


def test_render_field_placeholder_markup():
    assert (
        render_field_placeholder("vendor", "Vendor", "text")
        == '<span data-field="vendor" data-field-kind="text">Vendor</span>'
    )
    assert (
        render_field_placeholder("vendor", "Vendor", None)
        == '<span data-field="vendor">Vendor</span>'
    )


def test_update_missing_returns_404():
    with TestClient(app) as client:
        assert client.put("/templates/does-not-exist", json={"status": "ready"}).status_code == 404


def test_delete_then_get_and_delete_missing():
    with TestClient(app) as client:
        tmpl = _create(client, "Invoice A")
        assert client.delete(f"/templates/{tmpl['id']}").status_code == 204
        assert client.get(f"/templates/{tmpl['id']}").status_code == 404
        assert client.delete("/templates/does-not-exist").status_code == 404


def test_upload_docx_source_converts_to_rich_html():
    with TestClient(app) as client:
        tmpl = _create(client, "Agreement A", "contract")
        resp = client.post(
            f"/templates/{tmpl['id']}/source",
            files={"file": ("agreement.docx", make_docx_bytes(), DOCX_MIME)},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "rich_html"
        assert body["html_body"]  # non-empty HTML body from the conversion
        assert body["form_fields"] == []


def test_upload_non_fillable_pdf_source_converts_to_rich_html():
    with TestClient(app) as client:
        tmpl = _create(client, "Prose A", "contract")
        resp = client.post(
            f"/templates/{tmpl['id']}/source",
            files={"file": ("prose.pdf", make_plain_pdf(), "application/pdf")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mode"] == "rich_html"
        assert body["html_body"]  # non-empty HTML body from the conversion
        assert body["form_fields"] == []
