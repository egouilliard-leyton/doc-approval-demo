"""Outbound digital signing stage: provider registry + the stage entrypoints.

A separate, manual, post-decision action (NOT part of the inbound auto-run
pipeline, NOT in STAGE_ORDER): an APPROVED document's original PDF is sealed with
a real X.509 signature whose embedded CMS validates against a trust chain.

Two providers behind one entrypoint, mirroring the decision stage:
  * ``pyhanko`` — real PAdES signatures (optional ``signing`` extra, lazily imported)
  * ``mock``    — offline, no heavy deps (default in tests)

The pyhanko path keeps every heavy import lazy so the app boots without the extra;
a missing dep surfaces as a ``ValueError`` (-> 400), never a bare swallow.
"""

from __future__ import annotations

from importlib.util import find_spec
from time import perf_counter

from app import storage
from app.models import Document, DocumentStatus
from app.schemas import SignatureValidation, SignResult

from . import mock
from .base import PROVIDERS, resolve_provider, signing_meta_from_settings


def _pyhanko_version() -> str:
    """The installed pyhanko version string (or 'pyhanko' if unavailable)."""
    try:
        from importlib.metadata import version

        return f"pyhanko {version('pyhanko')}"
    except Exception:  # noqa: BLE001
        return "pyhanko"


def available_engines() -> list[str]:
    """Signing providers usable right now: mock always, pyhanko iff importable."""
    engines = ["mock"]
    if find_spec("pyhanko") is not None:
        engines.append("pyhanko")
    return engines


def run_signing(doc: Document, provider: str = "") -> SignResult:
    """Sign an approved document's original PDF and return the sealed result.

    Requires a PDF source. Self-validates the freshly signed output and embeds
    that validation in the returned :class:`SignResult` (status = ``signed``).
    """
    provider = resolve_provider(provider)
    if doc.mime != "application/pdf":
        raise ValueError("Digital signing requires a PDF source document.")

    meta = signing_meta_from_settings()
    src = storage.read_original(doc.id)

    start = perf_counter()
    if provider == "mock":
        signed_bytes, validation = mock.sign(src, meta)
        engine_version = "mock"
    else:
        from . import pyhanko_signer  # lazy: only touches pyhanko on the real path

        signed_bytes, validation = pyhanko_signer.sign(src, meta)
        engine_version = _pyhanko_version()
    latency_ms = int((perf_counter() - start) * 1000)

    storage.save_signed_pdf(doc.id, signed_bytes)

    return SignResult(
        document_id=doc.id,
        status=DocumentStatus.signed,
        provider=provider,
        engine_version=engine_version,
        level=validation.level,
        field_name=meta.field_name,
        signed_pdf_url=storage.signed_pdf_url(doc.id),
        validation=validation,
        latency_ms=latency_ms,
        warnings=list(validation.warnings),
    )


def validate_document_signature(doc: Document, provider: str = "") -> SignatureValidation:
    """Validate a document's signature: the signed PDF if present, else the original."""
    provider = resolve_provider(provider)

    if storage.signed_pdf_exists(doc.id):
        pdf_bytes = storage.signed_pdf_path(doc.id).read_bytes()
    else:
        pdf_bytes = storage.read_original(doc.id)

    if provider == "mock":
        return mock.validate(pdf_bytes)

    from . import pyhanko_signer  # lazy: only touches pyhanko on the real path

    return pyhanko_signer.validate(pdf_bytes)


def prewarm(engines) -> None:  # noqa: ARG001 — parity with ocr.prewarm; nothing to load
    """No-op: signing has no models to warm (keeps main.py generic if ever used)."""
    return None


__all__ = [
    "PROVIDERS",
    "available_engines",
    "run_signing",
    "validate_document_signature",
    "prewarm",
]
