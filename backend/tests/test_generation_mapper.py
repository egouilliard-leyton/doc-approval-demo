"""Phase 1 (form-fill) Wave 3 tests: the mock/heuristic field mapper. Fully offline."""

from fastapi.testclient import TestClient

from app.main import app
from app.pipeline.generation import field_catalogue, suggest_mapping
from app.schemas import TemplateFormField

from .generation_fixtures import make_fillable_pdf


def _field(name: str, kind: str = "text", label: str | None = None) -> TemplateFormField:
    return TemplateFormField(name=name, kind=kind, page=1, nearby_label=label)


# --- heuristic suggest_mapping ------------------------------------------------


def test_heuristic_maps_obvious_fields_and_signature():
    catalogue = field_catalogue("invoice")
    fields = [
        _field("invoice_number", label="Invoice No"),
        _field("vendor_name"),
        _field("Signature", kind="signature"),
        _field("sprocket_gizmo_widget"),  # nothing in the catalogue overlaps this
    ]

    out = suggest_mapping("invoice", fields, catalogue, provider="mock")

    # An obviously-named field lands on a catalogue path containing its key tokens.
    inv = out["invoice_number"]
    assert inv.field_path is not None
    assert "invoice" in inv.field_path or "number" in inv.field_path
    assert inv.source == "heuristic"
    assert inv.is_signature is False

    assert out["vendor_name"].field_path == "vendor"

    # A signature field is flagged for stamping, not bound to a data path.
    sig = out["Signature"]
    assert sig.is_signature is True
    assert sig.field_path is None

    # A genuinely unmatchable field is left unbound rather than force-matched.
    assert out["sprocket_gizmo_widget"].field_path is None


def test_unknown_provider_raises():
    try:
        suggest_mapping("invoice", [], field_catalogue("invoice"), provider="nope")
    except ValueError as exc:
        assert "Unknown mapping provider" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unknown provider")


# --- POST /suggest-mapping route ----------------------------------------------


def _create_template(client: TestClient, doc_type: str = "invoice") -> str:
    resp = client.post("/templates", json={"name": "T1", "doc_type": doc_type})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_suggest_mapping_route_falls_back_to_mock_without_key():
    with TestClient(app) as client:
        tid = _create_template(client)
        client.post(
            f"/templates/{tid}/source",
            files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
        )

        resp = client.post(f"/templates/{tid}/suggest-mapping")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # No OPENROUTER_API_KEY in the test env -> the heuristic (mock) is what ran.
        assert body["provider_used"] == "mock"
        suggestions = body["suggestions"]
        assert {"vendor_name", "currency", "Signature"} <= set(suggestions)
        assert suggestions["Signature"]["is_signature"] is True
        assert suggestions["vendor_name"]["field_path"] == "vendor"


def test_suggest_mapping_404_without_form_fields():
    with TestClient(app) as client:
        tid = _create_template(client)  # no source uploaded -> no form fields
        assert client.post(f"/templates/{tid}/suggest-mapping").status_code == 404
        assert client.post("/templates/missing/suggest-mapping").status_code == 404


def test_suggest_mapping_invalid_provider_is_400_not_500():
    with TestClient(app) as client:
        tid = _create_template(client)
        client.post(
            f"/templates/{tid}/source",
            files={"file": ("fillable.pdf", make_fillable_pdf(), "application/pdf")},
        )
        resp = client.post(f"/templates/{tid}/suggest-mapping", params={"provider": "nope"})
        assert resp.status_code == 400, resp.text
        assert "Unknown mapping provider" in resp.json()["detail"]
