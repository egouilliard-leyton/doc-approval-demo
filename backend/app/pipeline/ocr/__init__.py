"""OCR engine layer: a registry of swappable engines + the stage entrypoint.

Docling and mock are code-defined (they aren't VLMs). VLM engines are data-driven:
each is a :class:`app.models.VlmEngineRow` (one OpenRouter model), resolved from the
DB at call time. Adapters keep their heavy ML imports lazy, so importing this package
is cheap and the app boots without the optional OCR deps installed.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from app.config import settings
from app.models import Document, DocTypeDefinitionRow, VlmEngineRow
from app.schemas import OCRResult

from .base import OCREngine
from .digibot import DigibotEngine
from .docling import DoclingEngine
from .mock import MockEngine
from .qwen_vl import QwenVLEngine  # noqa: F401 — re-exported for back-compat
from .spreadsheet import SpreadsheetEngine
from .vlm import VLMEngine

logger = logging.getLogger(__name__)

# Code-defined engines (not VLMs). VLM engines come from the DB (VlmEngineRow).
# ``spreadsheet`` is selected automatically for CSV/XLSX docs (see the OCR route),
# not offered in the engine picker.
_STATIC_ENGINES: dict[str, type[OCREngine]] = {
    "docling": DoclingEngine,
    "mock": MockEngine,
    "spreadsheet": SpreadsheetEngine,
    # External HTTP OCR service. Resolvable by explicit name; only offered in the
    # engine picker when DIGIBOT_ENDPOINT is set (see routes/engines.list_engines).
    "digibot": DigibotEngine,
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


# --- Multi-engine routing + fallback -----------------------------------------
#
# Three staged helpers keep the DB session off the worker thread: the two that read
# the Session (``resolve_engine_chain`` + ``build_engine_objects``) run on the request
# thread; only the session-free ``run_ocr_chain`` enters ``asyncio.to_thread``.


def resolve_engine_chain(doc_type: str | None, session: Session) -> list[str]:
    """Ordered OCR-engine names to try for a doc type (READS the DB — request thread).

    A doc type with a ``preferred_ocr_engine`` drives the chain: preferred first, then
    its ``ocr_fallback_engines`` (order-preserving, deduped against the preferred).
    Otherwise the global default chain (``ocr_default_engine`` + fallbacks) is used.
    Names are NOT validated here — unknown/disabled ones are skipped later.
    """
    if doc_type:
        row = session.get(DocTypeDefinitionRow, doc_type)
        if row is not None and row.preferred_ocr_engine:
            preferred = row.preferred_ocr_engine
            chain = [preferred]
            for name in row.ocr_fallback_engines or []:
                if name != preferred and name not in chain:
                    chain.append(name)
            return chain
    return [settings.ocr_default_engine] + list(settings.ocr_default_fallback_engines)


def build_engine_objects(
    names: list[str], session: Session
) -> list[tuple[str, OCREngine]]:
    """Resolve each name to a live engine (READS the DB — request thread).

    Unknown/disabled/stale names are logged and skipped so one bad entry doesn't
    crash the whole chain; the resulting list carries the (name, engine) pairs that
    actually resolved.
    """
    objs: list[tuple[str, OCREngine]] = []
    for name in names:
        try:
            objs.append((name, get_engine(name, session)))
        except ValueError as exc:
            logger.warning("OCR routing: skipping engine '%s': %s", name, exc)
    return objs


def run_ocr_chain(
    doc: Document, engine_objs: list[tuple[str, OCREngine]]
) -> OCRResult:
    """Run the engine chain over a document, falling back on failure/inadequacy.

    SESSION-FREE: safe to call inside a worker thread. Advances to the next engine
    when the current one (a) raises, (b) returns empty text, or (c) scores below
    ``ocr_fallback_confidence_threshold`` — EXCEPT on the last engine, whose output is
    accepted regardless so the chain always terminates with something. Raises
    ``ValueError`` only if EVERY engine raised.
    """
    if not engine_objs:
        raise ValueError("No OCR engines could be resolved for this document.")

    attempted: list[str] = []
    last_error: Exception | None = None

    for idx, (name, eng) in enumerate(engine_objs):
        is_last = idx == len(engine_objs) - 1
        attempted.append(name)
        try:
            result = eng.run(doc)
        except Exception as exc:  # noqa: BLE001 — try the next engine, remember the error
            last_error = exc
            logger.warning("OCR fallback: engine '%s' raised: %s", name, exc)
            if is_last:
                # Every engine (including this last one) failed — surface as a 400.
                raise ValueError(
                    f"All OCR engines failed (tried {', '.join(attempted)}). "
                    f"Last error: {exc}"
                ) from exc
            continue

        inadequate = not result.full_text.strip() or (
            result.avg_confidence is not None
            and result.avg_confidence < settings.ocr_fallback_confidence_threshold
        )
        if inadequate and not is_last:
            logger.info(
                "OCR fallback: '%s' output inadequate (empty/low-confidence); trying next.",
                name,
            )
            continue

        result.attempted_engines = list(attempted)
        if len(attempted) > 1:
            result.warnings = list(result.warnings) + [
                f"OCR fallback: '{attempted[0]}' unavailable/inadequate; used '{name}'."
            ]
            logger.info(
                "OCR fallback: used '%s' after %s.", name, ", ".join(attempted[:-1])
            )
        return result

    # Unreachable: the last engine either returns or raises above. Guard anyway.
    raise ValueError(
        f"All OCR engines failed (tried {', '.join(attempted)})."
    ) from last_error


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


__all__ = [
    "get_engine",
    "available_engines",
    "run_ocr",
    "resolve_engine_chain",
    "build_engine_objects",
    "run_ocr_chain",
    "prewarm",
    "OCREngine",
    "VLMEngine",
]
