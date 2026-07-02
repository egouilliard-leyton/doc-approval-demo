"""OCR engine layer: a registry of swappable engines + the stage entrypoint.

Docling and mock are code-defined (they aren't VLMs). VLM engines are data-driven:
each is a :class:`app.models.VlmEngineRow` (one OpenRouter model), resolved from the
DB at call time. Adapters keep their heavy ML imports lazy, so importing this package
is cheap and the app boots without the optional OCR deps installed.
"""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import Document, VlmEngineRow
from app.schemas import OCRResult

from .base import OCREngine
from .docling import DoclingEngine
from .mock import MockEngine
from .qwen_vl import QwenVLEngine  # noqa: F401 — re-exported for back-compat
from .spreadsheet import SpreadsheetEngine
from .vlm import VLMEngine

# Code-defined engines (not VLMs). VLM engines come from the DB (VlmEngineRow).
# ``spreadsheet`` is selected automatically for CSV/XLSX docs (see the OCR route),
# not offered in the engine picker.
_STATIC_ENGINES: dict[str, type[OCREngine]] = {
    "docling": DoclingEngine,
    "mock": MockEngine,
    "spreadsheet": SpreadsheetEngine,
}


def get_engine(name: str, session: Session) -> OCREngine:
    """Resolve an engine by name: a static factory, or an enabled VLM row.

    Raises ``ValueError`` for an unknown or disabled engine (the route maps it to a 400).
    """
    factory = _STATIC_ENGINES.get(name)
    if factory is not None:
        return factory()

    row = session.get(VlmEngineRow, name)
    if row is not None and row.enabled:
        return VLMEngine(name=row.key, model=row.model)

    available = ", ".join(available_engines(session))
    raise ValueError(f"Unknown or disabled OCR engine '{name}'. Available: {available}")


def available_engines(session: Session) -> list[str]:
    """Names accepted by the OCR route's ``engine`` parameter (static + enabled VLMs)."""
    vlm = session.exec(
        select(VlmEngineRow.key).where(VlmEngineRow.enabled == True)  # noqa: E712
    ).all()
    return list(_STATIC_ENGINES) + list(vlm)


def run_ocr(doc: Document, engine_name: str, session: Session) -> OCRResult:
    """Run the named engine over the document's pages, returning a normalized result."""
    return get_engine(engine_name, session).run(doc)


def prewarm(engine_names: list[str], *, log=print) -> None:
    """Load each named *static* engine's models so the first real request is fast.

    Only static engines (docling) load local models worth warming; ``mock`` has
    nothing and VLM ``warm()`` is a no-op (warming one would fire a paid call), so
    non-static names are simply skipped. Each engine warms independently; a failure
    (e.g. an uninstalled optional dep) is logged and skipped, never raised.
    """
    for name in engine_names:
        factory = _STATIC_ENGINES.get(name)
        if factory is None or name == "mock":
            continue
        try:
            log(f"[prewarm] loading {name} models…")
            factory().warm()
            log(f"[prewarm] {name} ready")
        except Exception as exc:  # noqa: BLE001 — warming is best-effort
            log(f"[prewarm] {name} skipped: {type(exc).__name__}: {exc}")


__all__ = ["get_engine", "available_engines", "run_ocr", "prewarm", "OCREngine", "VLMEngine"]
