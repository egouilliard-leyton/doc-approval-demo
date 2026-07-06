"""Offline mock signer/validator (no heavy deps) for tests + frontend dev.

Appends a plain-text marker line to the PDF bytes instead of producing a real CMS
signature, and validates by looking for that marker. Deterministic and dependency-
free, so the full sign/validate round-trip can be exercised without pyhanko.
"""

from __future__ import annotations

from app.schemas import SignatureValidation, SignerInfo

from .base import MOCK_LEVEL, MOCK_MARKER_PREFIX, SigningMeta

_MOCK_ISSUER = "Mock Demo CA"


def _marker(field_name: str, signer_cn: str) -> str:
    return f"\n{MOCK_MARKER_PREFIX}{field_name}:{signer_cn}\n"


def sign(src_pdf_bytes: bytes, meta: SigningMeta) -> tuple[bytes, SignatureValidation]:
    """Append a mock signature marker; return (signed_bytes, its validation)."""
    signed = src_pdf_bytes + _marker(meta.field_name, meta.signer_name).encode("utf-8")
    validation = SignatureValidation(
        valid=True,
        intact=True,
        trusted=True,
        level=MOCK_LEVEL,
        signer=SignerInfo(
            common_name=meta.signer_name,
            issuer=_MOCK_ISSUER,
            serial="MOCK",
        ),
        signed_at=None,
        trust_anchor=_MOCK_ISSUER,
        summary="MOCK:INTACT:TRUSTED",
    )
    return signed, validation


def validate(pdf_bytes: bytes) -> SignatureValidation:
    """Validate mock-signed bytes: valid iff the marker is present."""
    prefix = MOCK_MARKER_PREFIX.encode("utf-8")
    idx = pdf_bytes.rfind(prefix)
    if idx == -1:
        return SignatureValidation(
            valid=False,
            intact=False,
            trusted=False,
            level=MOCK_LEVEL,
            summary="MOCK:NO-SIGNATURE",
        )

    # Parse "<field>:<signer_cn>" out of the marker line.
    line = pdf_bytes[idx + len(prefix):].split(b"\n", 1)[0].decode("utf-8", "replace")
    field_name, _, signer_cn = line.partition(":")
    return SignatureValidation(
        valid=True,
        intact=True,
        trusted=True,
        level=MOCK_LEVEL,
        signer=SignerInfo(
            common_name=signer_cn or "Mock Demo Signer",
            issuer=_MOCK_ISSUER,
            serial="MOCK",
        ),
        signed_at=None,
        trust_anchor=_MOCK_ISSUER,
        summary="MOCK:INTACT:TRUSTED",
    )
