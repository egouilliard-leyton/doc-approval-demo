"""Route-level tests for the signature detection post-pass in structuring.

The detector is monkeypatched to return a fixed detection (no weights, no network), so
the test asserts the structuring result carries a spatially-grounded signature field with
a bbox + crop URL, and that a detector failure degrades to an empty field + a warning
rather than breaking structuring.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.pipeline import signature_detector
from app.pipeline.signature_detector import Detection, SignatureDetectorUnavailable

from .conftest import SAMPLES


def _upload(client: TestClient, name: str, doc_type: str | None = None) -> str:
    data = {"doc_type": doc_type} if doc_type else None
    with (SAMPLES / name).open("rb") as fh:
        resp = client.post("/documents", files={"file": (name, fh)}, data=data)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _ocr(client: TestClient, doc_id: str) -> None:
    resp = client.post(f"/documents/{doc_id}/ocr", params={"engine": "mock"})
    assert resp.status_code == 200, resp.text


def _structure(client: TestClient, doc_id: str) -> dict:
    resp = client.post(
        f"/documents/{doc_id}/structure",
        params={"doc_type": "contract", "provider": "mock", "ocr_engine": "mock"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_signatures_detected_and_grounded(monkeypatch):
    monkeypatch.setattr(
        signature_detector,
        "detect_signatures",
        lambda page_path: [Detection(bbox=(10.0, 20.0, 110.0, 80.0), confidence=0.87)],
    )
    with TestClient(app) as client:
        doc_id = _upload(client, "contract-standard.pdf")
        _ocr(client, doc_id)
        result = _structure(client, doc_id)

        sigs = result["fields"]["signatures"]
        assert isinstance(sigs, list) and len(sigs) >= 1
        fv = sigs[0]
        assert fv["value"] is True
        assert fv["confidence"] == 0.87
        assert fv["grounding"]["bbox"] == [10.0, 20.0, 110.0, 80.0]
        assert fv["grounding"]["image_url"].endswith("-sig-00.png")
        assert fv["grounding"]["page"] == 1
        # The list[FieldValue] is flattened into the hover grounding map.
        assert "signatures.0" in result["grounding_map"]
        assert result["grounding_map"]["signatures.0"]["bbox"] == [10.0, 20.0, 110.0, 80.0]

        # The crop image is actually written and served via /files.
        crop = client.get(fv["grounding"]["image_url"])
        assert crop.status_code == 200


def test_signature_detector_unavailable_degrades_gracefully(monkeypatch):
    def _unavailable(page_path):
        raise SignatureDetectorUnavailable("no model file")

    monkeypatch.setattr(signature_detector, "detect_signatures", _unavailable)
    with TestClient(app) as client:
        doc_id = _upload(client, "contract-standard.pdf")
        _ocr(client, doc_id)
        result = _structure(client, doc_id)

        # Structuring still succeeds; the signature field is empty + a warning is logged.
        assert result["status"] == "structured"
        assert result["fields"]["signatures"] == []
        assert any("signature detection unavailable" in w for w in result["warnings"])


def test_signature_detection_disabled_is_silent(monkeypatch):
    monkeypatch.setattr(settings, "signature_detection_enabled", False)
    # Should never be called when disabled.
    monkeypatch.setattr(
        signature_detector,
        "detect_signatures",
        lambda page_path: (_ for _ in ()).throw(AssertionError("must not run when disabled")),
    )
    with TestClient(app) as client:
        doc_id = _upload(client, "contract-standard.pdf")
        _ocr(client, doc_id)
        result = _structure(client, doc_id)

        assert result["fields"]["signatures"] == []
        assert not any("signature detection" in w for w in result["warnings"])
