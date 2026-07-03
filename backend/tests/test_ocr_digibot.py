"""External Digibot OCR adapter tests (offline: never a real HTTP call).

The engine is unreachable unless DIGIBOT_ENDPOINT is set, so the default path
raises a clean ValueError (-> HTTP 400). The happy path monkeypatches the endpoint
and httpx.Client so a canned JSON response maps into a normalized OCRResult.
"""

import httpx
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings
from app.db import engine as db_engine
from app.main import app
from app.models import Document
from app.pipeline.ocr import get_engine

from .conftest import SAMPLES


def _upload(client: TestClient, name: str) -> str:
    with (SAMPLES / name).open("rb") as fh:
        resp = client.post("/documents", files={"file": (name, fh)})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # noqa: D401 — canned success
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stands in for httpx.Client: every POST returns the same canned JSON."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def post(self, *args, **kwargs) -> _FakeResponse:
        return _FakeResponse(self._payload)


def test_unconfigured_engine_run_raises_value_error():
    """No endpoint set -> ValueError (same type VLM raises for a missing key)."""
    assert not settings.digibot_endpoint  # sanity: tests never configure it
    doc = Document(id="digibot-unconf", filename="x.pdf", mime="application/pdf", page_count=1)
    with Session(db_engine) as session:
        eng = get_engine("digibot", session)
        try:
            eng.run(doc)
        except ValueError as exc:
            assert "not configured" in str(exc)
            assert "DIGIBOT_ENDPOINT" in str(exc)
        else:
            raise AssertionError("expected ValueError for the unconfigured engine")


def test_ocr_route_digibot_unconfigured_returns_400():
    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        resp = client.post(f"/documents/{doc_id}/ocr", params={"engine": "digibot"})
        assert resp.status_code == 400, resp.text
        assert "not configured" in resp.json()["detail"]


def test_ocr_route_digibot_happy_path_maps_response(monkeypatch):
    canned = {
        "pages": [
            {
                "text": "HELLO DIGIBOT",
                "blocks": [
                    {
                        "text": "HELLO DIGIBOT",
                        "bbox": [1.0, 2.0, 3.0, 4.0],
                        "confidence": 0.88,
                        "label": "title",
                    }
                ],
                "tables": [
                    {"markdown": "| a | b |", "n_rows": 1, "n_cols": 2, "confidence": 0.7}
                ],
            }
        ]
    }
    monkeypatch.setattr(settings, "digibot_endpoint", "https://example.test/ocr")
    monkeypatch.setattr(settings, "digibot_api_key", "secret-token")
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _FakeClient(canned))

    with TestClient(app) as client:
        doc_id = _upload(client, "invoice-clean.pdf")
        resp = client.post(f"/documents/{doc_id}/ocr", params={"engine": "digibot"})
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["engine_name"] == "digibot"
        assert "HELLO DIGIBOT" in result["full_text"]
        assert result["pages"][0]["blocks"][0]["confidence"] == 0.88
        assert result["table_count"] >= 1
