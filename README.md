# Document Auto-Approval System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Made By Agents](https://img.shields.io/badge/Made%20By%20Agents-madebyagents.com-55D44C?labelColor=1B1C1C)](https://www.madebyagents.com)

A proof-of-concept that ingests contracts & invoices, pre-scans them for quality, runs
OCR (**Qwen3-VL / Docling**), structures the result into approval-relevant fields with
**LangExtract**, and lets an agent make a reliable **approve / flag / needs-review**
decision with an explanation, a rule-by-rule trace, and a confidence score. An approved
document can then be **digitally signed** (real PAdES / X.509) for outbound transmission —
see [`docs/digital-signing.md`](docs/digital-signing.md).

Built as the demo for a video on _the best OCR tools for AI agents_. The pipeline is
modular — each stage (**pre-scan → OCR → structure → decide**) is a swappable component,
so OCR engines can be compared side-by-side on camera. **Signing** is a separate, manual,
post-decision action (not part of the auto-run).

📚 Full feature docs: **[`docs/`](docs/README.md)**.

- **Backend:** FastAPI (`backend/`, Python 3.12, `uv`) — the pipeline + REST API.
- **Frontend:** Vite + React 19 (TypeScript) at the repo root — `pnpm` + Tailwind v4 + shadcn/ui.
- **Agent / structuring model:** OpenRouter `deepseek/deepseek-v4-flash` (OpenAI-compatible).
- **Storage:** local filesystem + SQLite (zero cloud setup).

## Prerequisites

- macOS (Apple Silicon supported) or Linux, **Python 3.12**, [`uv`](https://docs.astral.sh/uv/),
  Node + [`pnpm`](https://pnpm.io/), and an **OpenRouter API key**.

## Setup

```bash
git clone <repo> && cd doc-approval-system

# 1. Install everything (backend deps + frontend).
make install

# 2. Configure secrets.
cp backend/.env.example backend/.env
#   edit backend/.env -> set OPENROUTER_API_KEY=...
#   (model defaults to deepseek/deepseek-v4-flash; fallback deepseek/deepseek-v3.2)

# 3. Pre-load the local Docling models so the first request isn't slow on camera (~once).
make warm

# 4. (Optional) Enable real digital signing (PAdES via pyhanko).
cd backend && uv sync --extra signing   # omit to use the offline "mock" provider
```

> **OCR engines.** **Docling** runs locally (layout + tables + bbox-grounded highlights)
> and is the default. **Qwen3-VL** (`qwen-vl`) is a vision-language model called over
> OpenRouter — no local models, stronger transcription on hard pages, but no bounding
> boxes, so its on-image highlight overlay is disabled. It reuses `OPENROUTER_API_KEY`.

## Run

```bash
make dev        # backend on :8000 + frontend on :5173 (Ctrl+C stops both)
# open http://localhost:5173 — drag a file from backend/samples/ to run the pipeline
```

Other targets: `make dev-backend`, `make dev-frontend`, `make test` (offline suite),
`make reset` (clear `backend/data/` for a fresh demo — **run before recording**).

## Environment variables

All backend config lives in `backend/.env` (see `backend/.env.example` for the full set with
defaults). The essentials:

| Variable             | Default                            | Notes                                                                          |
| -------------------- | ---------------------------------- | ------------------------------------------------------------------------------ |
| `OPENROUTER_API_KEY` | _(required)_                       | Used by both structuring and the decision agent.                               |
| `DECISION_MODEL`     | `deepseek/deepseek-v4-flash`       | Fallback `deepseek/deepseek-v3.2`.                                             |
| `STRUCTURING_MODEL`  | `deepseek/deepseek-v4-flash`       | LangExtract extractor model.                                                   |
| `OCR_DEFAULT_ENGINE` | `docling`                          | `qwen-vl` \| `docling` \| `mock`.                                              |
| `OCR_VLM_MODEL`      | `qwen/qwen3-vl-235b-a22b-instruct` | OpenRouter VLM for the `qwen-vl` engine (reuses `OPENROUTER_API_KEY`).         |
| `OCR_DEVICE`         | `cpu`                              | CPU is the reliable on-device path (MPS unsupported by Docling's float64 ops). |
| `PRE_WARM_MODELS`    | `false`                            | `true` → load OCR models at startup (set for the demo).                        |
| `SIGNING_PROVIDER`   | `pyhanko`                           | `pyhanko` (real PAdES, needs `--extra signing`) \| `mock` (offline).           |
| `SIGNING_LEVEL`      | `PAdES-B-B`                         | `PAdES-B-B` \| `PAdES-B-T` (B-T needs `SIGNING_TSA_URL`).                       |
| `SIGNING_TSA_URL`    | _(empty)_                          | RFC 3161 timestamp-authority URL; set to enable B-T.                           |
| `SIGNING_CERT_DIR`   | `certs`                            | Demo signer cert dir, outside `data/` and gitignored (see signing doc).        |

See [`docs/digital-signing.md`](docs/digital-signing.md) for the full `SIGNING_*` set and the
demo-cert security notes.

## How it works

`POST /documents` (upload) → then per-document stage endpoints, each persisted and re-fetchable:
`POST /documents/{id}/prescan` → `…/ocr?engine=qwen-vl|docling` → `…/structure?doc_type=invoice|contract`
→ `…/decide`. Deterministic business rules run in code and the LLM can **explain but never
override** a hard-failed rule; low OCR/extraction confidence or a poor scan caps the decision
at `needs_review`.

Once a document is **approved**, three signing endpoints become available (a manual,
post-decision step — not part of the auto-run): `POST /documents/{id}/sign` seals the PDF with
a real X.509 signature and advances it to `signed` (gated: `400` if not a PDF, `409` unless
decided **and** approved); `GET /documents/{id}/sign` returns the persisted result; and
`POST /documents/{id}/validate-signature` re-verifies it. Re-deciding invalidates any prior
signature. See [`docs/digital-signing.md`](docs/digital-signing.md).

## Tests

```bash
make test   # backend pytest — fully offline (mock OCR engine + mock LLM provider, no API key)
```

## License

MIT © 2026 Made By Agents — see [LICENSE](LICENSE).
