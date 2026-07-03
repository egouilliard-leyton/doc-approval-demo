"""External OCR-service adapter (Digibot / Rossum-style).

Unlike the local layout engine (Docling) or a VLM over OpenRouter, this engine
posts each page image to a third-party OCR HTTP service and maps its JSON response
into the normalized :class:`OCRResult` shape. Connecting a real service is just a
matter of pointing ``DIGIBOT_ENDPOINT`` (and ``DIGIBOT_API_KEY`` if required) at it
— no code change per tenant.

The engine is only reachable once configured: with no endpoint set, ``run`` raises
the same ``ValueError`` type the VLM engine raises for a missing key, so the OCR
route maps it to a clean HTTP 400 rather than a 500. ``httpx`` is imported lazily
inside the request method (it's available transitively, but never needed at import
or boot time), and ``warm()`` is a no-op so startup never fires a networked/paid call.
"""

from __future__ import annotations

import base64
from pathlib import Path

from app import storage
from app.config import settings
from app.schemas import OCRBlock, OCRPage, OCRTable

from .base import OCREngine


class DigibotEngine(OCREngine):
    """OCR via an external HTTP service (one page image per request)."""

    name = "digibot"
    # Stub version stamp; a real integration would surface the service's model/version.
    version = "digibot-external-1"

    def _request_page(self, client, path: Path) -> dict:
        """POST one page image to the service and return the parsed JSON page dict.

        The request/response shape below is a PLACEHOLDER for a real Rossum/Digibot
        schema — adapt the payload and the mapping in ``_ocr_pages`` to the concrete
        service. Any transport/parse failure is re-raised as a ``ValueError`` so it
        surfaces as a 400 (mirrors ``VLMEngine._transcribe``), never a raw 500.
        """
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        headers = {}
        if settings.digibot_api_key:
            headers["Authorization"] = f"Bearer {settings.digibot_api_key}"
        try:
            response = client.post(
                settings.digibot_endpoint,
                headers=headers,
                json={"image": b64},
                timeout=settings.digibot_timeout_s,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 — surface as a clean 400, not a 500
            raise ValueError(f"digibot OCR request failed: {exc}") from exc

    def _ocr_pages(self, doc_id: str, pages: list[Path]) -> tuple[list[OCRPage], list[str]]:
        if not settings.digibot_endpoint:
            raise ValueError(
                "'digibot' OCR engine is not configured: set DIGIBOT_ENDPOINT "
                "(and DIGIBOT_API_KEY if required)."
            )

        import httpx  # lazy: available transitively, only needed when configured

        out: list[OCRPage] = []
        with httpx.Client() as client:
            for page_no, path in enumerate(pages, start=1):
                payload = self._request_page(client, path)
                # Assumed response shape (placeholder — see _request_page):
                # {"pages": [{"text": ..., "blocks": [...], "tables": [...]}]}
                page_data = (payload.get("pages") or [{}])[0]
                text = page_data.get("text") or ""

                raw_blocks = page_data.get("blocks") or []
                if raw_blocks:
                    blocks = [
                        OCRBlock(
                            page=page_no,
                            text=b.get("text") or "",
                            bbox=tuple(b.get("bbox") or (0.0, 0.0, 0.0, 0.0)),
                            confidence=b.get("confidence"),
                            label=b.get("label") or "text",
                        )
                        for b in raw_blocks
                    ]
                else:
                    # No block detail: one page-spanning, no-bbox block (mirrors VLMEngine).
                    blocks = [
                        OCRBlock(page=page_no, text=text, bbox=(0.0, 0.0, 0.0, 0.0), label="text")
                    ]

                tables = [
                    OCRTable(
                        page=page_no,
                        bbox=tuple(t["bbox"]) if t.get("bbox") else None,
                        n_rows=t.get("n_rows") or 0,
                        n_cols=t.get("n_cols") or 0,
                        markdown=t.get("markdown") or "",
                        confidence=t.get("confidence"),
                    )
                    for t in (page_data.get("tables") or [])
                ]

                markdown_url: str | None = None
                if text:
                    storage.save_ocr_markdown(doc_id, self.name, page_no, text)
                    markdown_url = storage.ocr_markdown_url(doc_id, self.name, page_no)

                out.append(
                    OCRPage(
                        page=page_no,
                        text=text,
                        blocks=blocks,
                        tables=tables,
                        markdown_url=markdown_url,
                    )
                )
        return out, []

    def warm(self) -> None:
        """No-op: never fire a networked/paid external call at startup."""
