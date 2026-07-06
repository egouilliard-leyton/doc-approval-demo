"""Demo server-held signer: mint + persist a self-signed CA and end-entity leaf.

Custody option A for the demo — a self-signed CA + leaf minted on first use and
reused thereafter (idempotent). Private key material is kept under
``storage.certs_dir()`` (OUTSIDE the /files-served data dir) with 0600 perms.

The ``cryptography`` import is lazy (a pyhanko dep, only present with the optional
``signing`` extra); a missing dep surfaces as a ``ValueError`` (-> 400), never a
bare swallow. NOT for production — a fixed demo passphrase is used by design.
"""

from __future__ import annotations

import os
from pathlib import Path

from app import storage
from app.config import settings

# Persisted filenames under the certs dir.
_CA_PEM = "ca.pem"
_SIGNER_P12 = "signer.p12"

# Fixed demo-only passphrase for the PKCS#12 bundle. This is a demo seal, not a
# production HSM — the passphrase is not a secret and is documented as such.
DEMO_P12_PASSPHRASE = b"demo-signer-passphrase"


def _chmod_600(path: Path) -> None:
    """Best-effort restrict a private-key file to owner read/write only."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # e.g. filesystems without POSIX perms; the dir is already gitignored.


def ensure_demo_signer() -> tuple[str, bytes]:
    """Return (p12_path, passphrase), minting + persisting the CA+leaf if absent.

    Idempotent: reuses an existing ``ca.pem`` + ``signer.p12`` when both are
    present, otherwise mints a fresh self-signed CA and end-entity leaf and writes
    them with 0600 perms. Returns the PKCS#12 path as a string (pyhanko's
    ``SimpleSigner.load_pkcs12`` wants a path, not bytes).
    """
    certs = storage.certs_dir()
    ca_pem = certs / _CA_PEM
    p12 = certs / _SIGNER_P12

    if ca_pem.is_file() and p12.is_file():
        return str(p12), DEMO_P12_PASSPHRASE

    _mint(ca_pem, p12)
    return str(p12), DEMO_P12_PASSPHRASE


def demo_ca_der() -> bytes:
    """The demo CA certificate as DER bytes (for a pyhanko ValidationContext root).

    Ensures the signer exists first, then parses the persisted PEM and re-encodes
    it as DER (``asn1crypto``/pyhanko trust roots load from DER).
    """
    ensure_demo_signer()
    from cryptography import x509  # lazy: optional dep
    from cryptography.hazmat.primitives.serialization import Encoding

    ca_pem = storage.certs_dir() / _CA_PEM
    cert = x509.load_pem_x509_certificate(ca_pem.read_bytes())
    return cert.public_bytes(Encoding.DER)


def _mint(ca_pem: Path, p12: Path) -> None:
    """Mint a self-signed CA + end-entity leaf and persist them (LOCKED recipe)."""
    try:
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import Encoding, pkcs12
        from cryptography.x509.oid import NameOID
    except ImportError as exc:  # optional dep absent -> clean 400 upstream
        raise ValueError(
            "Digital signing needs the 'signing' extra (pyhanko). "
            "Install it with: uv sync --extra signing"
        ) from exc

    ca_cn = settings.signing_ca_common_name
    signer_cn = settings.signing_signer_name

    now = datetime.datetime.now(datetime.timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, ca_cn)])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ee_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ee_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, signer_cn)])
    ee = (
        x509.CertificateBuilder()
        .subject_name(ee_name)
        .issuer_name(ca_name)
        .public_key(ee_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    p12_bytes = pkcs12.serialize_key_and_certificates(
        b"demo-signer",
        ee_key,
        ee,
        [ca],
        serialization.BestAvailableEncryption(DEMO_P12_PASSPHRASE),
    )

    # The CA public cert is not secret; the p12 carries the private key -> 0600.
    ca_pem.write_bytes(ca.public_bytes(Encoding.PEM))
    p12.write_bytes(p12_bytes)
    _chmod_600(p12)
