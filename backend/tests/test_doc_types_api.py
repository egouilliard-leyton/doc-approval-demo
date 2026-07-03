"""Phase 3 Wave 2 doc-type CRUD + preview tests. Offline (mock provider, no network)."""

from fastapi.testclient import TestClient

from app import doc_types
from app.main import app
from app.serialization import dict_to_rule_defn

from .conftest import SAMPLES


def _extraction_defn(name: str) -> dict:
    """A minimal-but-buildable extraction definition with two scalar fields."""
    return {
        "name": name,
        "fields": [
            {"name": "po_number", "kind": "scalar", "cls": "po_number", "coerce": "text"},
            {"name": "total", "kind": "scalar", "cls": "total", "coerce": "number"},
        ],
        "core_paths": ["total"],
        "prompt": "",
        "examples": [],
    }


def _rule_defn(name: str) -> dict:
    """A minimal rule set: one presence rule + one literal-threshold rule."""
    return {
        "name": name,
        "rules": [
            {"kind": "presence", "name": "po_present", "field_path": "po_number", "severity": "review"},
            {
                "kind": "threshold",
                "name": "total_cap",
                "field_path": "total",
                "op": "lte",
                "threshold": 10000,
                "severity": "review",
            },
        ],
        "citation_paths": ["po_number", "total"],
    }


def _create_body(name: str) -> dict:
    return {
        "name": name,
        "label": name.replace("_", " ").title(),
        "icon": "",
        "extraction_definition": _extraction_defn(name),
        "rule_definition": _rule_defn(name),
        "citation_paths": ["po_number", "total"],
    }


def test_list_includes_builtins():
    with TestClient(app) as client:
        resp = client.get("/doc-types")
        assert resp.status_code == 200, resp.text
        by_name = {row["name"]: row for row in resp.json()}
        assert "invoice" in by_name and "contract" in by_name
        assert by_name["invoice"]["builtin"] is True
        assert by_name["contract"]["builtin"] is True
        # Multi-word built-ins get humanized labels (not "Delivery_note").
        assert by_name["po"]["label"] == "Purchase Order"
        assert by_name["delivery_note"]["label"] == "Delivery Note"


def test_get_single_and_404():
    with TestClient(app) as client:
        assert client.get("/doc-types/invoice").status_code == 200
        assert client.get("/doc-types/nope").status_code == 404


def test_create_valid_custom_type_and_registered():
    name = "purchase_order_create"
    with TestClient(app) as client:
        resp = client.post("/doc-types", json=_create_body(name))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["builtin"] is False
        assert body["version"] == 1

        got = client.get(f"/doc-types/{name}")
        assert got.status_code == 200, got.text
        assert doc_types.is_registered(name)


def test_create_duplicate_409():
    name = "purchase_order_dupe"
    with TestClient(app) as client:
        assert client.post("/doc-types", json=_create_body(name)).status_code == 201
        assert client.post("/doc-types", json=_create_body(name)).status_code == 409


def test_create_invalid_rules_422():
    name = "purchase_order_bad"
    body = _create_body(name)
    body["rule_definition"]["rules"] = [
        # references a field not declared in the extraction definition
        {"kind": "presence", "name": "bad_ref", "field_path": "nonexistent", "severity": "review"},
        # not a serializable rule kind -> must be rejected (no code in custom types)
        {"kind": "coded", "name": "evil"},
    ]
    with TestClient(app) as client:
        resp = client.post("/doc-types", json=body)
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "nonexistent" in detail
        assert "coded" in detail


def test_builtin_is_read_only():
    with TestClient(app) as client:
        put = client.put(
            "/doc-types/invoice",
            json={
                "label": "Invoice",
                "icon": "",
                "extraction_definition": {},
                "rule_definition": {},
                "citation_paths": [],
            },
        )
        assert put.status_code == 403, put.text
        assert client.delete("/doc-types/invoice").status_code == 403


def test_update_bumps_version():
    name = "purchase_order_update"
    with TestClient(app) as client:
        assert client.post("/doc-types", json=_create_body(name)).status_code == 201

        body = _create_body(name)
        del body["name"]
        body["label"] = "Renamed PO"
        put = client.put(f"/doc-types/{name}", json=body)
        assert put.status_code == 200, put.text
        assert put.json()["version"] == 2
        assert put.json()["label"] == "Renamed PO"


def test_delete_custom_type():
    name = "purchase_order_delete"
    with TestClient(app) as client:
        assert client.post("/doc-types", json=_create_body(name)).status_code == 201
        assert client.delete(f"/doc-types/{name}").status_code == 204
        assert client.get(f"/doc-types/{name}").status_code == 404


def test_delete_in_use_409():
    name = "purchase_order_inuse"
    with TestClient(app) as client:
        assert client.post("/doc-types", json=_create_body(name)).status_code == 201

        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            up = client.post(
                "/documents",
                files={"file": ("invoice-clean.pdf", fh)},
                data={"doc_type": name},
            )
        assert up.status_code == 201, up.text

        resp = client.delete(f"/doc-types/{name}")
        assert resp.status_code == 409, resp.text


def test_preview_invoice_mock():
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/invoice/preview",
            json={"sample_text": "INVOICE\nVendor: Mock\nTotal: $1,234.56", "provider": "mock"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["doc_type"] == "invoice"
        assert body["fields"]["total"]["value"] == 1234.56
        assert body["fields"]["line_items"], "expected at least one line item"
        assert isinstance(body["checks"], list) and body["checks"]


def test_deserialize_strips_test_fn_injection():
    """A ``_`` -prefixed key in rule JSON must not be set on the rule dataclass."""
    d = {
        "name": "injected",
        "rules": [
            {
                "kind": "llm_advisory",
                "name": "x",
                "question": "q?",
                "_test_fn": "injected-payload",
            }
        ],
        "citation_paths": [],
    }
    defn = dict_to_rule_defn(d)
    assert len(defn.rules) == 1
    assert defn.rules[0]._test_fn is None


def test_create_bad_threshold_op_422():
    name = "purchase_order_badop"
    body = _create_body(name)
    body["rule_definition"]["rules"] = [
        {
            "kind": "threshold",
            "name": "total_cap",
            "field_path": "total",
            "op": "equals",
            "threshold": 10000,
            "severity": "review",
        }
    ]
    with TestClient(app) as client:
        resp = client.post("/doc-types", json=body)
        assert resp.status_code == 422, resp.text
        assert "op" in resp.json()["detail"]


def test_preview_unknown_type_404():
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/nope/preview",
            json={"sample_text": "anything", "provider": "mock"},
        )
        assert resp.status_code == 404, resp.text


# --- Phase: active-learning Wave 1 — extraction-definition accessor ----------


def test_get_extraction_definition_invoice_fields():
    """The built-in invoice definition resolves with its expected scalar fields."""
    defn = doc_types.get_extraction_definition("invoice")
    field_names = {f.name for f in defn.fields}
    assert {"invoice_no", "vendor", "total"} <= field_names


def test_get_extraction_definition_unknown_raises():
    import pytest

    with pytest.raises(ValueError):
        doc_types.get_extraction_definition("nope")


# --- OCR routing patch (narrow, allowed on built-ins) ------------------------


def _restore_invoice_routing() -> None:
    """Reset the shared built-in invoice row's routing so other tests are unaffected."""
    from sqlmodel import Session

    from app.db import engine
    from app.models import DocTypeDefinitionRow

    with Session(engine) as session:
        row = session.get(DocTypeDefinitionRow, "invoice")
        row.preferred_ocr_engine = None
        row.ocr_fallback_engines = []
        session.add(row)
        session.commit()


def test_patch_routing_allowed_on_builtin():
    """PATCH /doc-types/invoice/routing is NOT rejected (unlike PUT), and persists."""
    with TestClient(app) as client:
        before = client.get("/doc-types/invoice").json()
        try:
            resp = client.patch(
                "/doc-types/invoice/routing",
                json={"preferred_ocr_engine": "mock", "ocr_fallback_engines": ["docling"]},
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["preferred_ocr_engine"] == "mock"
            assert body["ocr_fallback_engines"] == ["docling"]
            assert body["builtin"] is True
            assert body["version"] == before["version"] + 1

            # The listing reflects the new routing.
            by_name = {r["name"]: r for r in client.get("/doc-types").json()}
            assert by_name["invoice"]["preferred_ocr_engine"] == "mock"
        finally:
            _restore_invoice_routing()


def test_patch_routing_unknown_type_404():
    with TestClient(app) as client:
        resp = client.patch(
            "/doc-types/nope/routing",
            json={"preferred_ocr_engine": "mock"},
        )
        assert resp.status_code == 404, resp.text


def test_patch_routing_engages_in_pipeline():
    """Routing set via PATCH actually steers OCR: an invoice with no ?engine= runs mock."""
    with TestClient(app) as client:
        with (SAMPLES / "invoice-clean.pdf").open("rb") as fh:
            up = client.post(
                "/documents",
                files={"file": ("invoice-clean.pdf", fh)},
                data={"doc_type": "invoice"},
            )
        assert up.status_code == 201, up.text
        doc_id = up.json()["id"]

        try:
            patch = client.patch(
                "/doc-types/invoice/routing",
                json={"preferred_ocr_engine": "mock"},
            )
            assert patch.status_code == 200, patch.text

            # No explicit ?engine= -> routes via the doc type's preferred engine (mock).
            ocr = client.post(f"/documents/{doc_id}/ocr")
            assert ocr.status_code == 200, ocr.text
            assert ocr.json()["engine_name"] == "mock"
        finally:
            _restore_invoice_routing()
