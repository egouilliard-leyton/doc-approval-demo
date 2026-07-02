"""Offline tests for the doc-type wizard ingest endpoint (Phase 3 Wave 2).

Text uploads pass through with no LLM; image / PDF uploads are OCR'd via the Qwen-VL
engine, whose ``_client`` / ``_transcribe`` are patched so nothing hits the network.
Covers: text passthrough, single-image OCR, multi-page PDF OCR (transcribe called once
per page + joined), the 413 size guard, the missing-key -> 400 guard, and that ``kind``
is echoed back.
"""

import io

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import settings
from app.main import app
from app.pipeline.ocr import qwen_vl


@pytest.fixture(autouse=True)
def _set_key():
    """Default to a key being set; the missing-key test clears it explicitly."""
    saved = settings.openrouter_api_key
    settings.openrouter_api_key = "test-key"
    try:
        yield
    finally:
        settings.openrouter_api_key = saved


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, "PNG")
    return buf.getvalue()


def _pdf_bytes(pages: int) -> bytes:
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def test_text_passthrough_no_llm(monkeypatch):
    # Any OCR call would explode -> proves the text path never touches the engine.
    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_client", lambda self: pytest.fail("OCR used"))
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("notes.txt", b"hello\nworld", "text/plain")},
            data={"kind": "process"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "hello\nworld"
    assert body["filename"] == "notes.txt"
    assert body["kind"] == "process"


def test_markdown_passthrough_strips_bom(monkeypatch):
    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_client", lambda self: pytest.fail("OCR used"))
    content = "﻿# Title".encode("utf-8")
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("spec.md", content, "text/markdown")},
            data={"kind": "example"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "# Title"
    assert resp.json()["kind"] == "example"


def test_image_ocr(monkeypatch):
    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_client", lambda self: object())
    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_transcribe", lambda self, c, p: "OCR-TEXT")
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("scan.png", _png_bytes(), "image/png")},
            data={"kind": "example"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["text"] == "OCR-TEXT"
    assert resp.json()["kind"] == "example"


def test_pdf_ocr_transcribes_each_page(monkeypatch):
    calls = {"n": 0}

    def fake_transcribe(self, client, path):
        calls["n"] += 1
        return f"PAGE-{calls['n']}"

    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_client", lambda self: object())
    monkeypatch.setattr(qwen_vl.QwenVLEngine, "_transcribe", fake_transcribe)
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("doc.pdf", _pdf_bytes(2), "application/pdf")},
            data={"kind": "process"},
        )
    assert resp.status_code == 200, resp.text
    assert calls["n"] == 2
    assert resp.json()["text"] == "PAGE-1\n\nPAGE-2"


def test_oversize_rejected_413():
    big = b"x" * (settings.max_upload_mb * 1024 * 1024 + 1)
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("big.txt", big, "text/plain")},
            data={"kind": "process"},
        )
    assert resp.status_code == 413, resp.text


def test_missing_key_ocr_returns_400(monkeypatch):
    monkeypatch.setattr(settings, "openrouter_api_key", "")
    with TestClient(app) as client:
        resp = client.post(
            "/doc-types/assist/ingest",
            files={"file": ("scan.png", _png_bytes(), "image/png")},
            data={"kind": "process"},
        )
    assert resp.status_code == 400, resp.text
