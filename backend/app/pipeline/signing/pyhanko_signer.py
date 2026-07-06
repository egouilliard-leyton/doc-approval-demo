"""Real PAdES signer/validator via pyHanko (the optional ``signing`` extra).

Produces a real CMS signature embedded in the PDF and validates it against the
demo CA trust root. All pyhanko/cryptography/asn1crypto imports are LAZY (inside
the functions), so the app boots without the extra; a missing dep surfaces as a
``ValueError`` (-> 400 upstream), matching how the OCR/LLM optional paths degrade.

Recipe locked to pyhanko 0.35.1 (verified working in this env).
"""

from __future__ import annotations

from app.schemas import SignatureValidation, SignerInfo

from . import certs
from .base import SigningMeta

_LEVEL_B_B = "PAdES-B-B"
_LEVEL_B_T = "PAdES-B-T"


def _require_pyhanko():
    """Import the pyhanko signing surface, raising a clean ValueError if absent."""
    try:
        from pyhanko.sign.signers import (  # noqa: F401
            PdfSignatureMetadata,
            PdfSigner,
            SimpleSigner,
        )
        from pyhanko.pdf_utils.incremental_writer import (  # noqa: F401
            IncrementalPdfFileWriter,
        )
    except ImportError as exc:
        raise ValueError(
            "Digital signing needs the 'signing' extra (pyhanko). "
            "Install it with: uv sync --extra signing"
        ) from exc


def sign(src_pdf_bytes: bytes, meta: SigningMeta) -> tuple[bytes, SignatureValidation]:
    """Sign the PDF (PAdES) with the demo signer; return (signed_bytes, validation).

    Self-validates the freshly produced output so the returned validation reflects
    the exact bytes persisted downstream.
    """
    _require_pyhanko()
    import io

    from pyhanko.sign.signers import PdfSignatureMetadata, PdfSigner, SimpleSigner
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter

    p12_path, passphrase = certs.ensure_demo_signer()
    signer = SimpleSigner.load_pkcs12(p12_path, passphrase=passphrase)  # PATH, not BytesIO

    use_tsa = bool(meta.tsa_url)
    sig_meta_kwargs = dict(
        field_name=meta.field_name,
        reason=meta.reason,
        location=meta.location or None,
        name=meta.signer_name,
    )
    timestamper = None
    if use_tsa:
        from pyhanko.timestamps import HTTPTimeStamper

        sig_meta_kwargs["md_algorithm"] = "sha256"
        timestamper = HTTPTimeStamper(meta.tsa_url)

    sig_meta = PdfSignatureMetadata(**sig_meta_kwargs)

    # A VISIBLE appearance (stamp box on page 1) in addition to the cryptographic
    # signature, so the seal shows in any PDF viewer — not only a signature-aware one.
    stamp_style = None
    new_field_spec = None
    if meta.visible:
        from pyhanko.sign.fields import SigFieldSpec
        from pyhanko.stamp import TextStampStyle

        stamp_text = "Digitally signed by:\n%(signer)s\n%(ts)s"
        if meta.reason:
            stamp_text += f"\n{meta.reason}"
        stamp_style = TextStampStyle(stamp_text=stamp_text)
        page_index, box = _placement(src_pdf_bytes, meta)
        new_field_spec = SigFieldSpec(
            sig_field_name=meta.field_name,
            on_page=page_index,
            box=box,
        )

    writer = IncrementalPdfFileWriter(io.BytesIO(src_pdf_bytes))
    signed_bytes = (
        PdfSigner(
            sig_meta,
            signer=signer,
            timestamper=timestamper,
            stamp_style=stamp_style,
            new_field_spec=new_field_spec,
        )
        .sign_pdf(writer)
        .getvalue()
    )

    validation = validate(signed_bytes)
    return signed_bytes, validation


# Fallback page size (A4 points) when a page's dimensions can't be read.
_A4_W, _A4_H = 595.0, 842.0

Box = "tuple[float, float, float, float]"


def _placement(src_pdf_bytes: bytes, meta: SigningMeta) -> "tuple[int, Box]":
    """Where to draw the visible stamp: ``(page_index, box)`` in PDF (bottom-left) coords.

    Prefers the template's signature anchor — the spot the author marked with the
    ``<img data-signature>`` placeholder — so the seal lands "in the correct place".
    Falls back to the configured corner/page when the PDF carries no anchor (e.g. an
    inbound document, or a template without a signature placeholder).
    """
    anchor = _find_anchor(src_pdf_bytes)
    if anchor is not None:
        return anchor
    return _corner_placement(src_pdf_bytes, meta.visible_position, meta.visible_page)


def _find_anchor(src_pdf_bytes: bytes) -> "tuple[int, Box] | None":
    """Locate the generation signature-anchor token; return ``(page_index, box)`` or None.

    The token (rendered invisibly by the binder at the template's signature placeholder)
    is found with PyMuPDF text search; the stamp box is anchored top-left at the token
    and extends down-right, clamped to stay on the page.
    """
    from .base import SIGNATURE_ANCHOR_TOKEN, STAMP_HEIGHT, STAMP_WIDTH

    try:
        import fitz  # PyMuPDF (base dep)

        doc = fitz.open(stream=src_pdf_bytes, filetype="pdf")
        for idx in range(doc.page_count):
            page = doc[idx]
            hits = page.search_for(SIGNATURE_ANCHOR_TOKEN)
            if not hits:
                continue
            rect, ph, pw = hits[0], page.rect.height, page.rect.width
            # fitz top-left origin -> PDF bottom-left; box top edge at the token.
            x0 = max(0.0, min(rect.x0, pw - STAMP_WIDTH))
            y_top = ph - rect.y0
            y_bottom = max(0.0, y_top - STAMP_HEIGHT)
            return idx, (x0, y_bottom, x0 + STAMP_WIDTH, y_bottom + STAMP_HEIGHT)
    except Exception:  # noqa: BLE001 — anchor is best-effort; fall through to corner
        return None
    return None


def _corner_placement(
    src_pdf_bytes: bytes, position: str, page: int
) -> "tuple[int, Box]":
    """A stamp box in the given corner of the given (1-based, clamped) page."""
    from .base import STAMP_HEIGHT, STAMP_MARGIN, STAMP_WIDTH

    page_w, page_h, idx = _A4_W, _A4_H, 0
    try:
        import fitz

        doc = fitz.open(stream=src_pdf_bytes, filetype="pdf")
        idx = max(0, min((page or 1) - 1, max(doc.page_count, 1) - 1))
        rect = doc[idx].rect
        page_w, page_h = float(rect.width), float(rect.height)
    except Exception:  # noqa: BLE001 — best-effort; A4/page-1 fallback
        page_w, page_h, idx = _A4_W, _A4_H, 0

    vert, _, horiz = (position or "bottom-right").partition("-")
    x0 = {
        "left": STAMP_MARGIN,
        "center": (page_w - STAMP_WIDTH) / 2,
        "right": page_w - STAMP_MARGIN - STAMP_WIDTH,
    }.get(horiz, page_w - STAMP_MARGIN - STAMP_WIDTH)
    y0 = STAMP_MARGIN if vert == "bottom" else page_h - STAMP_MARGIN - STAMP_HEIGHT
    return idx, (x0, y0, x0 + STAMP_WIDTH, y0 + STAMP_HEIGHT)


def validate(pdf_bytes: bytes) -> SignatureValidation:
    """Validate the first embedded signature against the demo CA trust root."""
    _require_pyhanko()
    import io

    from asn1crypto import x509 as asn1_x509
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    reader = PdfFileReader(io.BytesIO(pdf_bytes))
    sigs = reader.embedded_signatures
    if not sigs:
        return SignatureValidation(
            valid=False,
            intact=False,
            trusted=False,
            level=_LEVEL_B_B,
            summary="NO-SIGNATURE",
        )

    ca_asn1 = asn1_x509.Certificate.load(certs.demo_ca_der())
    vc = ValidationContext(trust_roots=[ca_asn1])
    status = validate_pdf_signature(sigs[0], vc)

    intact = bool(getattr(status, "intact", False))
    trusted = bool(getattr(status, "trusted", False))

    warnings: list[str] = []
    signer = None
    trust_anchor = None
    signed_at = None
    level = _LEVEL_B_T if getattr(status, "timestamp_validity", None) else _LEVEL_B_B

    cert = getattr(status, "signing_cert", None)
    if cert is not None:
        try:
            signer = SignerInfo(
                common_name=cert.subject.native.get("common_name") or "",
                issuer=cert.issuer.native.get("common_name") or "",
                serial=str(cert.serial_number),
                valid_from=_cert_datetime(cert, "not_before"),
                valid_to=_cert_datetime(cert, "not_after"),
            )
            trust_anchor = cert.issuer.native.get("common_name")
        except Exception as exc:  # noqa: BLE001 — never fail validation on parsing
            warnings.append(f"could not parse signer certificate: {exc}")

    try:
        summary = status.summary()
    except Exception:  # noqa: BLE001
        summary = f"{'INTACT' if intact else 'BROKEN'}:{'TRUSTED' if trusted else 'UNTRUSTED'}"

    return SignatureValidation(
        valid=intact and trusted,
        intact=intact,
        trusted=trusted,
        level=level,
        signer=signer,
        signed_at=signed_at,
        trust_anchor=trust_anchor,
        summary=summary,
        warnings=warnings,
    )


def _cert_datetime(cert, which: str):
    """Best-effort extract a validity datetime from an asn1crypto certificate."""
    try:
        return cert["tbs_certificate"]["validity"][which].native
    except Exception:  # noqa: BLE001
        return None
