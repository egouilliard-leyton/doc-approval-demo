"""Back-compat shim for the original Qwen3-VL engine.

The VLM adapter is now generic (:class:`app.pipeline.ocr.vlm.VLMEngine`, one instance
per OpenRouter model). ``QwenVLEngine`` remains as the default ``qwen-vl`` engine —
still importable, still constructible with no args — so existing imports
(``routes.doctype_assist``, ``scripts.smoke``) and the ``_client``/``_transcribe``
monkeypatch points in the tests keep working unchanged.
"""

from __future__ import annotations

from app.config import settings

from .vlm import VLMEngine, _extract_md_tables

__all__ = ["QwenVLEngine", "VLMEngine", "_extract_md_tables"]


class QwenVLEngine(VLMEngine):
    """The default VLM engine: ``qwen-vl`` pinned to ``settings.ocr_vlm_model``."""

    def __init__(self, device: str | None = None) -> None:
        super().__init__(name="qwen-vl", model=settings.ocr_vlm_model, device=device)
