# Document Auto-Approval System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Made By Agents](https://img.shields.io/badge/Made%20By%20Agents-madebyagents.com-55D44C?labelColor=1B1C1C)](https://www.madebyagents.com)

A proof-of-concept that ingests contracts & invoices, pre-scans them for quality, runs
OCR (**Qwen3-VL / Docling**), structures the result into approval-relevant fields with
**LangExtract**, and lets an agent make a reliable **approve / flag / needs-review**
decision with an explanation, a rule-by-rule trace, and a confidence score.

Built as the demo for a video on _the best OCR tools for AI agents_. The pipeline is
modular — each stage (**pre-scan → OCR → structure → decide**) is a swappable component,
so OCR engines can be compared side-by-side on camera.

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

## How it works

`POST /documents` (upload) → then per-document stage endpoints, each persisted and re-fetchable:
`POST /documents/{id}/prescan` → `…/ocr?engine=qwen-vl|docling` → `…/structure?doc_type=invoice|contract`
→ `…/decide`. Deterministic business rules run in code and the LLM can **explain but never
override** a hard-failed rule; low OCR/extraction confidence or a poor scan caps the decision
at `needs_review`.

## Templates & document generation

Once a document is extracted, the **Templates** section (top-nav → _Templates_, or `#/templates`)
turns those fields into a filled, downloadable document. A template is tied to a doc type and
works in one of two modes, auto-detected from the source you upload:

- **Form-fill** — upload a fillable **PDF** (AcroForm). Its fields are enumerated, an
  AI/heuristic mapper suggests which extracted field each maps to, and _Generate_ produces a
  filled PDF (with optional signature-image stamping). Permissive stack: **pypdf** + **reportlab**.
- **Rich-HTML** — upload a **DOCX / formatted PDF** (converted to editable HTML via
  **mammoth** / **Docling**), or start blank. Author it in a **TipTap** WYSIWYG editor, drop in
  `{{field}}` placeholders from the catalogue palette, and _Generate_ renders **PDF**
  (**WeasyPrint**) and/or **DOCX** (**html4docx**).

Three AI assists layer on top of the rich-HTML editor:

- **AI edit** — a streaming (SSE) authoring agent that edits the HTML/CSS from natural language
  ("make the header navy, bullets 11pt"); every edit is a revision.
- **Fidelity (auto-validate on upload)** — renders the template to page images (**pypdfium2**)
  and a vision model checks it against your uploaded example, showing a side-by-side + a
  severity-coded discrepancy checklist; one click hands the fixes to the AI editor.
- **History** — every edit snapshots a revision; restore rolls back (and is itself undoable).

Key endpoints (all under `/templates`): CRUD, `POST /{id}/source`, `GET /{id}/catalogue`,
`POST /{id}/suggest-mapping`, `POST /{id}/generate`, `POST /{id}/agent` (SSE),
`POST /{id}/qa`, `GET /{id}/revisions`, `POST /{id}/revisions/{rev}/restore`.

> **License note:** all generation libraries are permissive (BSD/MIT/Apache). New rasterization
> uses **pypdfium2** (not the AGPL PyMuPDF, which is retained only for the pre-existing ingestion
> path). WeasyPrint needs system **Pango + GDK-PixBuf** (`apt install libpango-1.0-0 libgdk-pixbuf2.0-0`);
> without them, DOCX output still works and PDF degrades gracefully. Install the generation extra
> with `uv sync --extra docgen` (already included in `make install`).

## Tests

```bash
make test   # backend pytest — fully offline (mock OCR/LLM/vision providers, no API key)
```

The template/generation pipeline is fully offline-tested (WeasyPrint renders real PDFs,
pypdfium2 rasterizes for real, the LLM/vision legs use deterministic mocks), including SSE
streaming, vision-QA, and end-to-end smoke tests for both generation journeys.

## License

MIT © 2026 Made By Agents — see [LICENSE](LICENSE).
