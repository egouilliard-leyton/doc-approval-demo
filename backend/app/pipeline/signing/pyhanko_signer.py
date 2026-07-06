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
    writer = IncrementalPdfFileWriter(io.BytesIO(src_pdf_bytes))
    signed_bytes = PdfSigner(
        sig_meta, signer=signer, timestamper=timestamper
    ).sign_pdf(writer).getvalue()

    validation = validate(signed_bytes)
    return signed_bytes, validation


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
