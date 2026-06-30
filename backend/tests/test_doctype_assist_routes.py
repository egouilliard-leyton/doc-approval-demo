"""Offline tests for the doc-type wizard routes (Phase 3 Wave 2).

The assist turn patches ``doctype_assistant._call_llm`` (so the real ``run_assist_turn``
runs without network); the annotate start route patches ``annotate_proc.launch_session``
so no real Plannotator process is spawned. Covers: a 200 assist turn shape, the
missing-key 400, an
annotate launch returning a session id + url, poll of an unknown id (404), and cancel of
an unknown id (204, idempotent).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import annotate_proc
from app.config import settings
from app.main import app
from app.pipeline import doctype_assistant


@pytest.fixture(autouse=True)
def _set_key():
    saved = settings.openrouter_api_key
    settings.openrouter_api_key = "test-key"
    try:
        yield
    finally:
        settings.openrouter_api_key = saved


def test_assist_turn_returns_questions(monkeypatch):
    raw = json.dumps(
        {
            "questions": ["What kind of document is this?"],
            "updated_spec_markdown": "# Draft\n",
            "done": False,
            "draft_doctype": None,
        }
    )
    monkeypatch.setattr(doctype_assistant, "_call_llm", lambda messages: raw)
    with TestClient(app) as client:
        resp = client.post("/doc-types/assist", json={"messages": []})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["questions"] == ["What kind of document is this?"]
    assert body["done"] is False
    assert body["draft_doctype"] is None
    assert body["updated_spec_markdown"] == "# Draft\n"
    assert body["warnings"] == []


def test_assist_missing_key_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    with TestClient(app) as client:
        resp = client.post("/doc-types/assist", json={"messages": []})
    assert resp.status_code == 400, resp.text


def test_annotate_start_returns_session(monkeypatch):
    # Patch the module-level function the route calls (it invokes
    # launch_session(body.spec_markdown) without _popen=, so patching
    # annotate_proc.subprocess.Popen would not be used by the route).
    monkeypatch.setattr(
        annotate_proc,
        "launch_session",
        lambda spec_markdown: ("fake-session-id", "http://127.0.0.1:19999/"),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/annotate", json={"spec_markdown": "# Spec\n"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["session_id"] == "fake-session-id"
        assert body["url"].startswith("http://127.0.0.1:")


def test_annotate_poll_unknown_returns_404():
    with TestClient(app) as client:
        resp = client.get("/doc-types/assist/annotate/does-not-exist")
    assert resp.status_code == 404, resp.text


def test_annotate_cancel_unknown_returns_204():
    with TestClient(app) as client:
        resp = client.delete("/doc-types/assist/annotate/does-not-exist")
    assert resp.status_code == 204, resp.text
