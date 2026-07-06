# Digital Signing (PAdES)

[← Docs index](README.md) · [← Project README](../README.md)

> **Shipped:** server-held demo seal, real **PAdES-B-B** (optional **-B-T** via a TSA) + signature validation. An outbound, manual, post-decision action — deliberately **not** part of the inbound `prescan → ocr → structure → decide` auto-run.

Signs an **approved** document's PDF with a real **X.509 certificate** whose embedded CMS
signature validates against a trust chain, then exposes that validation in the UI and API.

## Why (the requirement)

A stamped image — a scanned or pasted picture of a signature — carries **no cryptographic
guarantee**: anyone can copy the pixels, and nothing binds them to the document bytes or to a
verifiable identity. It is legally worthless as proof. A **real digital signature** embeds a
CMS (`adbe.pkcs7.detached`) blob over a `/ByteRange` of the PDF, so any later edit breaks
_intact_, and the signer's certificate _chains to a trust anchor_. This realizes the
digital-signing research: a real cert signature on outgoing documents (e.g. a _Solicitud de
Transmisión_ / _Anexo_ for the Spanish Ministry requirement), not a decorative stamp.

> **Not the inbound signature-detection feature.** This repo also has an inbound
> _signature-detection_ pass that spots **handwritten** signatures inside uploaded documents
> (a spatial/vision post-step in structuring). That is about _finding_ ink on a page we
> received. **Digital signing is the opposite direction:** we _produce_ a cryptographic seal
> on a document we are about to send. Different stage, different purpose — don't conflate them.

## What shipped

- An **outbound signing stage** (`backend/app/pipeline/signing/`) that seals an approved
  document's original PDF and **self-validates** the freshly signed bytes.
- **Signature validation** — re-verify any signed (or unsigned) document against the demo
  trust root, returning `intact` / `trusted` / `valid` plus the signer identity.
- A new terminal `DocumentStatus.signed`.
- A **`SignaturePanel`** under the Decision tab in the frontend.
- Two providers: **`pyhanko`** (real PAdES) and **`mock`** (offline, covers the test suite).

## How to use it

### 1. Install the real signing path (optional extra)

The `pyhanko` provider is an **optional dependency**, lazily imported so the app boots
without it. Install it with:

```bash
cd backend
uv sync --extra signing        # pulls in pyhanko (MIT)
```

Without the extra, set `SIGNING_PROVIDER=mock` to exercise the full sign/validate round-trip
offline (this is what the test suite uses).

### 2. Endpoints

All three live under the per-document router (`/documents/{id}`):

| Method & path | Purpose | Gating |
| --- | --- | --- |
| `POST /documents/{id}/sign` | Sign the approved PDF; advances the doc to `signed`. | `400` if the source isn't a PDF · `409` if not yet decided · `409` unless the decision is `approve`. |
| `GET /documents/{id}/sign` | Return the persisted signing result without re-signing. | `404` if never signed. |
| `POST /documents/{id}/validate-signature` | Re-verify the signature (the signed PDF if present, else the original). | — |

A signature is a cryptographic attestation of a specific approval, so **re-running
`POST /documents/{id}/decide` invalidates and deletes any prior signature** — a seal must not
outlive the approval it attested. Re-sign after a new `approve`.

### 3. UI flow

Open an **approved** document → **Decision** tab → **SignaturePanel**:

1. **Sign for transmission** → runs `POST /sign` with the configured provider.
2. Status badges appear: **Intact** (covered bytes untouched), **Trusted** (signer chains to
   the trust root), **Valid** (intact **and** trusted), plus the signer **CN** and the
   **trust anchor**.
3. **Download signed PDF** — the sealed file (`/files/{id}/signed/signed.pdf`).
4. **Re-verify signature** → re-runs `POST /validate-signature` on demand.

### 4. Configuration

All vars are prefixed `SIGNING_` (see `backend/.env.example`, defaults in
`backend/app/config.py`):

| Env var | Default | Notes |
| --- | --- | --- |
| `SIGNING_PROVIDER` | `pyhanko` | `pyhanko` (real) \| `mock` (offline). |
| `SIGNING_LEVEL` | `PAdES-B-B` | `PAdES-B-B` \| `PAdES-B-T` (B-T needs a TSA URL). |
| `SIGNING_TSA_URL` | _(empty)_ | RFC 3161 timestamp-authority URL; set to enable B-T. |
| `SIGNING_FIELD_NAME` | `Signature1` | Signature field name embedded in the PDF. |
| `SIGNING_REASON` | `Approved for transmission` | Reason recorded in the signature. |
| `SIGNING_LOCATION` | _(empty)_ | Optional location recorded in the signature. |
| `SIGNING_SIGNER_NAME` | `Document Approval Demo Signer` | End-entity (leaf) certificate CN. |
| `SIGNING_CA_COMMON_NAME` | `Document Approval Demo CA` | Demo CA certificate CN / trust anchor. |
| `SIGNING_CERT_DIR` | `certs` | Demo signer cert dir, resolved relative to `backend/`. |
| `SIGNING_TIMEOUT_S` | `60` | Signing/validation wall-clock ceiling. |

## Custody model & security

**Custody = server-held demo seal (option A).** On first use, a self-signed **demo CA** plus
an **end-entity leaf** are minted and persisted under `backend/certs/`
(`SIGNING_CERT_DIR`), then reused idempotently. The signing key lives in a PKCS#12 bundle
(`signer.p12`, written `0600`); the CA public cert (`ca.pem`) is the trust root used for
validation.

> [!warning] Demo cert only — not for production.
> - The cert dir is resolved **outside** the `/files`-served `data/` dir, so private keys are
>   **never downloadable** over HTTP (the mount serves `data/` only; the cert dir 404s via
>   `/files`). It is also **gitignored** (`backend/certs/`).
> - The PKCS#12 bundle uses a **fixed demo passphrase** (`demo-signer-passphrase`) — this is a
>   documented demo constant, **not a secret**. A self-signed CA is **not** a qualified/trusted
>   certificate; browsers and Adobe will show "signer's identity unknown" because the root is
>   not in any public trust store.
> - **To go real:** replace the demo signer with a proper certificate — swap the mint/load
>   step in `backend/app/pipeline/signing/certs.py` (and the trust root in
>   `pyhanko_signer.validate`) for a real key/cert or an HSM/qualified-cert integration, and
>   set `SIGNING_TSA_URL` to a real RFC 3161 TSA to upgrade the level to **PAdES-B-T**.

## PAdES levels: built vs backlog

PAdES baseline profiles stack: **B-B → B-T → B-LT → B-LTA** (each adds longer-term
verifiability).

| Level | What it adds | Status |
| --- | --- | --- |
| **B-B** | Basic CMS signature over the PDF `/ByteRange`. | ✅ Built (default). |
| **B-T** | A trusted RFC 3161 timestamp on the signature. | ✅ Built — set `SIGNING_TSA_URL`. |
| **B-LT** | Embedded revocation data (CRL/OCSP) + certs for long-term validation. | ⬜ Backlog. |
| **B-LTA** | B-LT + archive timestamps for very-long-term integrity. | ⬜ Backlog. |

## For the next agent

**Where the code lives:**

- `backend/app/pipeline/signing/` — the stage (adapter package, mirrors `pipeline/ocr/`):
  - `__init__.py` — provider registry + `run_signing` / `validate_document_signature` entrypoints.
  - `base.py` — `SigningMeta`, provider set (`pyhanko`, `mock`), provider resolution.
  - `pyhanko_signer.py` — real PAdES sign + validate (all pyhanko imports lazy; locked to pyhanko 0.35.1).
  - `mock.py` — offline marker-based sign/validate for tests + frontend dev.
  - `certs.py` — mints/reuses the demo CA + leaf (`0600` p12).
- `backend/app/routes/pipeline.py` — the `POST/GET /sign` + `POST /validate-signature` routes,
  the gating, and the stale-seal invalidation on re-decide.
- `backend/app/schemas.py` — `SignResult`, `SignatureValidation`, `SignerInfo`.
- `backend/app/config.py` / `backend/.env.example` — the `SIGNING_*` block + `signing_cert_path`.
- `backend/app/storage.py` — signed-PDF helpers + `certs_dir()`.
- `src/features/decision/SignaturePanel.tsx` — the UI (sign / badges / download / re-verify).

**Tests:** `backend/tests/test_signing.py` (12 tests — mock offline round-trip, the gating
rules, stale-seal invalidation, and a guarded real-pyhanko smoke). Full backend suite:
**55 passed** (`cd backend && uv run --no-sync pytest -q`).

**Follow-on backlog:**

- **B-LT / B-LTA** — embed revocation data + archive timestamps for long-term validation.
- **Remote per-signer signing** — pyHanko `ExternalSigner` so each signer holds their own key
  (instead of the shared server-held seal).
- **Stirling-PDF external adapter** — a third provider that offloads signing to a
  Stirling-PDF service.
- **Inbound `digital_signature_valid` rule primitive** — let the decision engine treat a valid
  embedded signature on an _incoming_ document as a business rule.
