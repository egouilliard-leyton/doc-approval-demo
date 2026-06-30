"""AI doc-type wizard endpoints (Phase 3 Wave 2).

Five stateless routes that drive the conversational doc-type design wizard:

- ``POST /doc-types/assist`` — one wizard turn (clarifying questions / updated spec /
  final draft), backed by :func:`app.pipeline.doctype_assistant.run_assist_turn`.
- ``POST /doc-types/assist/ingest`` — extract plain text from an uploaded process /
  example document (text passthrough, or OCR via the Qwen-VL engine for images / PDFs).
- ``POST /doc-types/assist/annotate`` — launch a Plannotator review session over a spec.
- ``GET /doc-types/assist/annotate/{session_id}`` — poll that session's status.
- ``DELETE /doc-types/assist/annotate/{session_id}`` — cancel it (idempotent).

None of these touch the database, so they omit the session dependency. The blocking
LLM / OCR work runs off the event loop via ``asyncio.to_thread`` inside
``asyncio.wait_for`` (mirroring :mod:`app.routes.pipeline`): a hung stage becomes a clean
504 and a missing ``OPENROUTER_API_KEY`` (raised as ``ValueError``) becomes a 400 — never
a 500 on an expected failure.

These paths sit UNDER the CRUD router's ``GET /doc-types/{name}`` but never collide with
it: the assist routes are POST/DELETE, a deeper-segment GET, or a distinct sub-path.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Callable, Literal, TypeVar

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.config import settings
from app.pipeline import doctype_assistant
from app import annotate_proc
from app.schemas import (
    AnnotatePollResponse,
    AnnotateStartResponse,
    AssistRequest,
    AssistResponse,
    IngestResponse,
)

router = APIRouter(prefix="/doc-types", tags=["doc-types-wizard"])

_T = TypeVar("_T")

# Extensions read as plain UTF-8 text (no OCR). Everything else (images, PDFs) is
# transcribed by the Qwen-VL engine.
_TEXT_EXTS = {".txt", ".md", ".csv", ".json"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"}
_MAX_OCR_PAGES = 20


async def _run_off_thread(stage: str, timeout: float, fn: Callable[..., _T], *args, **kwargs) -> _T:
    """Run a blocking stage off the event loop with a timeout (mirrors pipeline._run_stage).

    ``TimeoutError`` -> 504; ``ValueError`` (e.g. a missing API key) -> 400.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs), timeout=timeout
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504, detail=f"{stage} timed out after {timeout:.0f}s."
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- ingest helpers (text vs OCR) --------------------------------------------


def _is_text(ext: str, content_type: str | None) -> bool:
    """Decide whether an upload should be read as plain text rather than OCR'd."""
    if ext in _TEXT_EXTS:
        return True
    return bool(content_type and content_type.startswith("text/"))


def _ingest_text(content: bytes) -> str:
    """Decode upload bytes as UTF-8 text, stripping a leading BOM."""
    return content.decode("utf-8-sig", errors="replace")


def _ingest_via_ocr(content: bytes, ext: str) -> str:
    """Transcribe an image or PDF upload to text via the Qwen-VL OCR engine.

    Writes the bytes to a temp file, then: for an image, transcribes it directly; for a
    PDF, rasterizes each page to a temp PNG at ``settings.render_dpi`` and transcribes
    each, joining the page texts with blank lines. Caps at ``_MAX_OCR_PAGES`` pages
    (extra pages are dropped with a warning appended). A missing API key surfaces as the
    ``ValueError`` raised by ``QwenVLEngine._client`` (mapped to a 400 by the caller).
    All temp files are cleaned up.
    """
    from app.pipeline.ocr.qwen_vl import QwenVLEngine

    engine = QwenVLEngine()
    client = engine._client()  # raises ValueError when the key is unset

    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        tmp.write(content)
        tmp.flush()
        tmp.close()
        tmp_path = Path(tmp.name)

        if ext == ".pdf":
            return _ocr_pdf(engine, client, tmp_path)
        return engine._transcribe(client, tmp_path)
    finally:
        Path(tmp.name).unlink(missing_ok=True)


def _ocr_pdf(engine, client, pdf_path: Path) -> str:
    """Rasterize a PDF (capped at ``_MAX_OCR_PAGES``) and transcribe each page."""
    import fitz  # PyMuPDF (same dep app.storage uses)

    zoom = settings.render_dpi / 72.0  # PDF user space is 72 DPI.
    matrix = fitz.Matrix(zoom, zoom)
    page_texts: list[str] = []
    truncated = False

    with fitz.open(pdf_path) as pdf:
        for index, page in enumerate(pdf):
            if index >= _MAX_OCR_PAGES:
                truncated = True
                break
            pix = page.get_pixmap(matrix=matrix)
            png = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            try:
                png.write(pix.tobytes("png"))
                png.flush()
                png.close()
                page_texts.append(engine._transcribe(client, Path(png.name)))
            finally:
                Path(png.name).unlink(missing_ok=True)

    text = "\n\n".join(page_texts)
    if truncated:
        text += f"\n\n[truncated: only the first {_MAX_OCR_PAGES} pages were transcribed]"
    return text


# --- routes ------------------------------------------------------------------


@router.post("/assist", response_model=AssistResponse)
async def assist(req: AssistRequest) -> AssistResponse:
    """Run one doc-type design wizard turn.

    Returns clarifying questions + the updated spec, or — when the design is complete —
    a validated ``draft_doctype``. Graceful degradations are carried in ``warnings``; a
    missing key is a 400 and a hung turn is a 504.
    """
    return await _run_off_thread(
        "Assist turn", settings.assist_timeout_s, doctype_assistant.run_assist_turn, req
    )


@router.post("/assist/ingest", response_model=IngestResponse)
async def ingest(
    file: UploadFile = File(...),
    kind: Literal["process", "example"] = Form(...),
) -> IngestResponse:
    """Extract plain text from one uploaded process / example document.

    Text files (``.txt/.md/.csv/.json`` or ``text/*``) are decoded inline; images and
    PDFs are transcribed via the Qwen-VL OCR engine (off-thread, 400 if the key is
    unset, 504 on timeout).
    """
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()

    content = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds the {settings.max_upload_mb} MB upload limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if _is_text(ext, file.content_type):
        text = _ingest_text(content)
    else:
        text = await _run_off_thread(
            "OCR ingest", settings.ocr_timeout_s, _ingest_via_ocr, content, ext or ".png"
        )

    return IngestResponse(text=text, filename=filename, kind=kind)


class _AnnotateStartRequest(BaseModel):
    """Body for launching a Plannotator review session over a rendered spec."""

    spec_markdown: str


@router.post("/assist/annotate", response_model=AnnotateStartResponse)
def annotate_start(body: _AnnotateStartRequest) -> AnnotateStartResponse:
    """Launch a Plannotator annotation session over the spec markdown.

    The fork is fast (no model work), so it runs inline. A missing ``plannotator``
    binary surfaces as a ``ValueError`` -> 400.
    """
    try:
        session_id, url = annotate_proc.launch_session(body.spec_markdown)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnnotateStartResponse(session_id=session_id, url=url)


@router.get("/assist/annotate/{session_id}", response_model=AnnotatePollResponse)
def annotate_poll(session_id: str) -> AnnotatePollResponse:
    """Return an annotation session's status, or 404 if the id is unknown."""
    result = annotate_proc.poll_session(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Annotation session not found.")
    return AnnotatePollResponse(**result)


@router.delete("/assist/annotate/{session_id}", status_code=204)
def annotate_cancel(session_id: str) -> None:
    """Cancel an annotation session. Idempotent: always 204, even for an unknown id."""
    annotate_proc.cancel_session(session_id)
