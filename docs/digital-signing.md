# Digital Signing (PAdES)

[← Docs index](README.md) · [← Project README](../README.md)

> **Shipped:** server-held demo seal, real **PAdES-B-B** (optional **-B-T** via a TSA) + signature validation, applied to **two** targets — an approved inbound document *and* a **generated** template output (the real outbound artifact). A **visible** signature stamp is drawn by default, placed at the **template's signature marker** (or a configurable corner). An outbound, manual action — deliberately **not** part of the inbound `prescan → ocr → structure → decide` auto-run.

Signs a PDF with a real **X.509 certificate** whose embedded CMS signature validates against a
trust chain, then exposes that validation in the UI and API. Two flows share one signing core:
an **approved inbound document** (`/documents/{id}/sign`) and a **generated template output**
(`/templates/{id}/outputs/{output_id}/sign`) — the *Solicitud de Transmisión* / *Anexo* you
actually transmit.

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

- An **outbound signing stage** (`backend/app/pipeline/signing/`) with one shared
  `sign_pdf_bytes` core that seals a PDF and **self-validates** the freshly signed bytes.
- **Two signing targets:**
  - an **approved inbound document** — `POST /documents/{id}/sign` (`SignResult`);
  - a **generated template output** — `POST /templates/{id}/outputs/{output_id}/sign`
    (`GeneratedSignResult`), the outbound document you transmit.
- **Signature validation** — re-verify any signed (or unsigned) document against the demo
  trust root, returning `intact` / `trusted` / `valid` plus the signer identity.
- A **visible signature stamp** (default on) — "Digitally signed by … / timestamp / reason" —
  drawn **at the template's signature marker** if the document has one, else a configurable
  corner. The cryptographic signature is unaffected either way.
- A new terminal `DocumentStatus.signed`; a **`SignaturePanel`** (Decision tab) for documents
  and an **`OutputSigner`** in the **`GeneratePanel`** for generated outputs.
- Reliable cross-origin **downloads** — the signed-PDF buttons fetch the bytes and save a blob
  (a cross-origin `<a download>` is ignored and `target="_blank"` is popup-blocked).
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

### 4. Signing a generated document (the outbound flow)

The real PAdES use case is signing the document you **produce and send** — the filled
*Solicitud de Transmisión* / *Anexo* from the [template generator](../README.md), not the
inbound invoice. This is distinct from the generator's optional stamped **signature image**
(`signature_image` on `/generate`), which is a legally-worthless *picture*; this applies a real
cryptographic seal to the generated PDF.

| Method & path | Purpose |
| --- | --- |
| `POST /templates/{id}/outputs/{output_id}/sign` | Seal a generated output PDF with a real PAdES signature; writes `<output_id>-signed.pdf` beside the output and self-validates it. Returns `GeneratedSignResult`. `404` if the template/output is missing · `400` on an unknown provider. |

**UI:** in a template's **Generate** panel, after generating a PDF the result card shows a
**Sign for transmission** action (the `OutputSigner`). Signing reveals the **Intact / Trusted /
Valid** badges and a **Download signed PDF** button. No approve-gating here — a generated
document is itself the outbound artifact.

### 5. Visible signature & placement

A PAdES signature is **cryptographic, not visual**: it lives in the PDF's signature dictionary,
so a plain viewer (Chrome, `pdf.js`, Evince) shows nothing on the page even though the signature
is valid — only a signature-aware viewer (Adobe Acrobat) surfaces its panel. To make the seal
human-visible, a **visible stamp** is drawn by default (`SIGNING_VISIBLE=true`):

```
Digitally signed by:
Document Approval Demo Signer
2026-01-01 12:00:00 UTC
Approved for transmission
```

**Placement — the template decides.** Both template editors (the manual **Generate** editor and
the **AI edit** editor) let you drop a signature placeholder via the **Insert field → Signature
image** button, which serializes to `<img data-signature>`. The generator leaves an *invisible,
locatable anchor* at that spot (transparent in the PDF; stripped from the DOCX output so it
never leaks into Word), and the signer places the visible stamp exactly there. When a document
carries **no** marker (e.g. an inbound document, or a template without the placeholder), the
stamp falls back to a configurable corner/page (`SIGNING_VISIBLE_POSITION` / `_PAGE`). Set
`SIGNING_VISIBLE=false` for a bare (invisible) cryptographic signature.

### 6. Configuration

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
| `SIGNING_VISIBLE` | `true` | Draw a visible stamp (at the template marker if present, else the fallback below). `false` → invisible signature. |
| `SIGNING_VISIBLE_POSITION` | `bottom-right` | Fallback corner when there's no template marker: `top`/`bottom`-`left`/`center`/`right`. |
| `SIGNING_VISIBLE_PAGE` | `1` | Fallback page (1-based, clamped to the last page). |
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
  - `__init__.py` — provider registry + `sign_pdf_bytes` (shared core), `run_signing` /
    `validate_document_signature` entrypoints.
  - `base.py` — `SigningMeta`, provider set (`pyhanko`, `mock`), provider resolution, and the
    `SIGNATURE_ANCHOR_TOKEN` / stamp geometry / `VISIBLE_POSITIONS` constants.
  - `pyhanko_signer.py` — real PAdES sign + validate + the visible-stamp placement (`_placement`
    → template anchor via PyMuPDF, else `_corner_placement`). All pyhanko imports lazy; locked
    to pyhanko 0.35.1.
  - `mock.py` — offline marker-based sign/validate for tests + frontend dev.
  - `certs.py` — mints/reuses the demo CA + leaf (`0600` p12).
- `backend/app/routes/pipeline.py` — `POST/GET /documents/{id}/sign` + `/validate-signature`,
  gating, and the stale-seal invalidation on re-decide.
- `backend/app/routes/templates.py` — `POST /templates/{id}/outputs/{output_id}/sign`.
- `backend/app/pipeline/generation/binder.py` — leaves the invisible signature **anchor** at the
  `<img data-signature>` marker; `render.py` strips it from the DOCX output.
- `backend/app/schemas.py` — `SignResult`, `GeneratedSignResult`, `SignatureValidation`, `SignerInfo`.
- `backend/app/config.py` / `backend/.env.example` — the `SIGNING_*` block + `signing_cert_path`.
- `backend/app/storage.py` — signed-PDF + `template_output_path` helpers + `certs_dir()`.
- `src/features/decision/SignaturePanel.tsx` — the document UI (sign / badges / download / re-verify).
- `src/features/templates/GeneratePanel.tsx` — the `OutputSigner` for generated outputs;
  `src/lib/api.ts` — `signTemplateOutput` + the `downloadFile` blob helper.

**Tests:** `backend/tests/test_signing.py` (22 tests — mock offline round-trips for both
targets, the gating rules, stale-seal invalidation, visible-vs-invisible appearance,
template-anchor placement, and guarded real-pyhanko smokes) plus the DOCX-anchor-strip test in
`test_generation_render.py` and a `scenario_signing` in `scripts/smoke.py`. Full backend suite:
**661 passed, 1 skipped** (`cd backend && uv run --no-sync pytest -q`); smoke: **87/87**.

**Follow-on backlog:**

- **B-LT / B-LTA** — embed revocation data + archive timestamps for long-term validation.
- **Remote per-signer signing** — pyHanko `ExternalSigner` so each signer holds their own key
  (instead of the shared server-held seal).
- **Stirling-PDF external adapter** — a third provider that offloads signing to a
  Stirling-PDF service.
- **Inbound `digital_signature_valid` rule primitive** — let the decision engine treat a valid
  embedded signature on an _incoming_ document as a business rule.
