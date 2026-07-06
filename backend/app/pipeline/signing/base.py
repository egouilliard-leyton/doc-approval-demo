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

# A hidden token the generation stage renders at a template's signature placeholder
# (the `<img data-signature>` marker), so the signer can locate WHERE on the generated
# document the visible signature should land — "the correct place" the author chose,
# rather than a fixed corner. Invisible in the PDF; stripped from the DOCX output.
SIGNATURE_ANCHOR_TOKEN = "§§SIGZONE§§"  # §§SIGZONE§§

# Default visible-stamp box size in PDF points (also the size placed at an anchor).
STAMP_WIDTH = 200.0
STAMP_HEIGHT = 72.0
STAMP_MARGIN = 36.0

# Allowed corner positions for the fallback placement (when no template anchor).
VISIBLE_POSITIONS = frozenset(
    {
        "top-left",
        "top-center",
        "top-right",
        "bottom-left",
        "bottom-center",
        "bottom-right",
    }
)


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
    visible: bool = True
    visible_position: str = "bottom-right"  # corner fallback when no template anchor
    visible_page: int = 1  # 1-based; clamped to the last page


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
        visible=settings.signing_visible,
        visible_position=settings.signing_visible_position,
        visible_page=settings.signing_visible_page,
    )
