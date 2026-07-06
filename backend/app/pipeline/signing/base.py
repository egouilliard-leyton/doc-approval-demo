"""Shared constants + provider resolution for the outbound signing stage.

Kept intentionally light and dependency-free: the mock provider imports from here
without dragging in any heavy signing/crypto deps, and the app boots without them.
"""

from __future__ import annotations

from dataclasses import dataclass

# The two signing providers behind the one entrypoint (mirrors decision PROVIDERS):
#   "pyhanko" — real PAdES signatures (optional dep, lazily imported)
#   "mock"    — offline, no heavy deps (default in tests)
PROVIDERS = {"pyhanko", "mock"}

MOCK_LEVEL = "mock"

# Marker line the mock signer appends to the PDF bytes; parsed back on validate.
MOCK_MARKER_PREFIX = "%%MOCK-SIGNATURE:"


@dataclass(frozen=True)
class SigningMeta:
    """The signing parameters shared by the mock and pyhanko providers."""

    field_name: str
    reason: str
    location: str
    signer_name: str
    ca_common_name: str
    level: str
    tsa_url: str


def resolve_provider(name: str) -> str:
    """Validate a provider name, falling back to the configured default when blank."""
    from app.config import settings

    provider = name or settings.signing_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown signing provider '{provider}'. "
            f"Available: {', '.join(sorted(PROVIDERS))}"
        )
    return provider


def signing_meta_from_settings() -> SigningMeta:
    """Build the shared signing metadata from application settings."""
    from app.config import settings

    return SigningMeta(
        field_name=settings.signing_field_name,
        reason=settings.signing_reason,
        location=settings.signing_location,
        signer_name=settings.signing_signer_name,
        ca_common_name=settings.signing_ca_common_name,
        level=settings.signing_level,
        tsa_url=settings.signing_tsa_url,
    )
