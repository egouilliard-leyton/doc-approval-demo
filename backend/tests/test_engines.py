"""Engine registry endpoint tests: catalog CRUD + engine resolution.

Offline: no OPENROUTER_API_KEY in tests, so the model-list endpoint returns the
curated fallback and no engine ever fires a real call (we only resolve, never run VLM).
"""

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import engine as db_engine
from app.main import app
from app.pipeline.ocr import get_engine
from app.pipeline.ocr.vlm import VLMEngine


def test_default_engine_seeded_and_listed():
    """Lifespan seeds qwen-vl; docling is always present as a layout engine."""
    with TestClient(app) as client:
        engines = client.get("/engines").json()
        keys = {e["key"] for e in engines}
        assert "docling" in keys and "qwen-vl" in keys
        docling = next(e for e in engines if e["key"] == "docling")
        qwen = next(e for e in engines if e["key"] == "qwen-vl")
        assert docling["kind"] == "layout"
        assert qwen["kind"] == "vlm"


def test_openrouter_models_fallback_without_key():
    """No key configured -> curated fallback, never a 500."""
    with TestClient(app) as client:
        resp = client.get("/engines/openrouter-models")
        assert resp.status_code == 200
        models = resp.json()
        assert models and all("id" in m and "name" in m for m in models)
        assert any("qwen" in m["id"] for m in models)


def test_engine_crud_lifecycle():
    with TestClient(app) as client:
        # Create with an explicit-ish model; key is derived from the slug.
        created = client.post(
            "/engines", json={"label": "Gemini 3 Pro", "model": "google/gemini-3-pro"}
        )
        assert created.status_code == 201, created.text
        key = created.json()["key"]
        assert key == "google-gemini-3-pro"

        # Duplicate -> 409.
        assert client.post(
            "/engines", json={"label": "dup", "model": "google/gemini-3-pro"}
        ).status_code == 409

        # Appears enabled in the selector.
        assert any(e["key"] == key for e in client.get("/engines").json())

        # Disable -> drops out of the selector but stays in the catalog.
        assert client.patch(f"/engines/{key}", json={"enabled": False}).status_code == 200
        assert not any(e["key"] == key for e in client.get("/engines").json())
        assert any(r["key"] == key for r in client.get("/engines/catalog").json())

        # Delete -> gone from the catalog.
        assert client.delete(f"/engines/{key}").status_code == 204
        assert not any(r["key"] == key for r in client.get("/engines/catalog").json())
        assert client.patch(f"/engines/{key}", json={"label": "x"}).status_code == 404


def test_get_engine_resolves_and_rejects():
    with TestClient(app) as client:
        client.post("/engines", json={"label": "Resolve Me", "model": "vendor/model-x", "key": "resolveme"})
        client.post(
            "/engines",
            json={"label": "Off", "model": "vendor/model-y", "key": "offengine", "enabled": False},
        )
    with Session(db_engine) as session:
        eng = get_engine("resolveme", session)
        assert isinstance(eng, VLMEngine)
        assert eng.name == "resolveme" and eng.model == "vendor/model-x"

        # Disabled and unknown both raise (route maps to 400).
        for bad in ("offengine", "does-not-exist"):
            try:
                get_engine(bad, session)
                raise AssertionError(f"expected ValueError for '{bad}'")
            except ValueError:
                pass
