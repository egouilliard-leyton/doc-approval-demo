# Document Auto-Approval System

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Made By Agents](https://img.shields.io/badge/Made%20By%20Agents-madebyagents.com-55D44C?labelColor=1B1C1C)](https://www.madebyagents.com)

A proof-of-concept that ingests documents, pre-scans them for quality, runs
OCR (**Docling** + any **vision-language model** via OpenRouter), structures the result
into approval-relevant fields with **LangExtract**, and lets an agent make a reliable
**approve / flag / needs-review** decision with an explanation, a rule-by-rule trace, and
a confidence score. **Spreadsheets (`.xlsx`/`.csv`)** are first-class inputs too — parsed
natively (no OCR) and rendered as an interactive grid with cell-level grounding.

Highlights:

- **Configurable document types** — invoice/contract ship as built-ins; new types are data
  (a field list + approval rules), created from the UI, the `/doc-types` API, or a
  **"Create with AI"** wizard. See [Configurable document types](#configurable-document-types).
- **Connect any OCR model** — VLM engines are data-driven rows managed from the UI; the
  add-model list is populated live from OpenRouter. See [OCR models](#ocr-models-multi-vlm).
- **Spreadsheet inputs** — `.xlsx`/`.csv` are parsed cell-by-cell (no OCR/VLM), one page
  per sheet, and rendered as an interactive grid; each extracted field grounds to its
  **source cell** (e.g. `Invoice!B2`). See [Spreadsheet inputs](#spreadsheet-inputs).
- **Traceable extractions** — every field is boxed on the page (or highlighted in its grid
  cell) in a matching color; click a field to jump to its source. See
  [Reviewing extractions](#reviewing-extractions).
- **Long-document accuracy** — multi-page docs are split into sections (along the OCR engine's
  headings) and extracted section-by-section, with proximity-anchored grounding, cross-section
  dedup, and a whole-document grounding fallback. See
  [large-document-extraction.md](docs/large-document-extraction.md).
- **Human-in-the-loop** — edit any extracted value inline; every correction is logged.
- **Admin panel** — a consolidated overview, documents, corrections log, and configuration.
  See [Admin panel](#admin-panel).

Built as the demo for a video on _the best OCR tools for AI agents_. The pipeline is
modular — each stage (**pre-scan → OCR → structure → decide**) is a swappable component,
so OCR engines can be compared side-by-side on camera.

> **📚 Full documentation** lives in [`docs/`](docs/README.md):
> [Architecture](docs/ARCHITECTURE.md) · [API reference](docs/API.md) ·
> [Roadmap & work log](docs/ROADMAP.md) · [Validation rules](docs/validation-rules.md).
> Deep dives: [Large-document extraction](docs/large-document-extraction.md) ·
> [Signature detection](docs/signature-extraction.md).

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
> and is the default. **VLM engines** are vision-language models called over OpenRouter —
> no local models, stronger transcription on hard pages, but no bounding boxes (so their
> highlight overlay falls back to the containing table's box). `qwen-vl` is seeded by
> default; connect more from the UI (see [OCR models](#ocr-models-multi-vlm)). All VLMs
> reuse `OPENROUTER_API_KEY`. **Spreadsheets** bypass this stage entirely — a built-in
> `spreadsheet` engine parses the cells directly (no model call); see
> [Spreadsheet inputs](#spreadsheet-inputs).

## Run

```bash
make dev        # backend on :8000 + frontend on :5173 (Ctrl+C stops both)
# open http://localhost:5173 — drag a file from backend/samples/ to run the pipeline
```

Other targets: `make dev-backend`, `make dev-frontend`, `make test` (offline suite),
`make smoke` (offline end-to-end pipeline + API check), `make reset` (clear `backend/data/`
for a fresh demo — **run before recording**).

> **Local dev notes.** The frontend reads its API base from `VITE_API_BASE_URL`
> (default `http://localhost:8000`); if you run the backend on another port, set it
> (e.g. `VITE_API_BASE_URL=http://localhost:8001 pnpm dev`) **and** add that frontend
> origin to `CORS_ORIGINS`. The frontend requires **Node ≥ 22** (pnpm 11 is pinned); use
> `nvm use 22` + `corepack`. Machine-specific quirks (occupied ports, etc.) are not baked
> into this repo.

## Environment variables

All backend config lives in `backend/.env` (see `backend/.env.example` for the full set with
defaults). The essentials:

| Variable             | Default                            | Notes                                                                          |
| -------------------- | ---------------------------------- | ------------------------------------------------------------------------------ |
| `OPENROUTER_API_KEY` | _(required)_                       | Used by both structuring and the decision agent.                               |
| `DECISION_MODEL`     | `deepseek/deepseek-v4-flash`       | Fallback `deepseek/deepseek-v3.2`.                                             |
| `STRUCTURING_MODEL`  | `deepseek/deepseek-v4-flash`       | LangExtract extractor model.                                                   |
| `STRUCTURING_SECTIONING` | `true`                         | Section-aware extraction for long docs. `false` forces the single-blob path. Tuning knobs (`STRUCTURING_MAX_CHAR_BUFFER`, `_MAX_SECTIONS`, `_SECTION_MIN_CHARS`) + design: [large-document-extraction.md](docs/large-document-extraction.md). |
| `OCR_DEFAULT_ENGINE` | `docling`                          | `docling` \| `mock` \| any enabled VLM engine key.                             |
| `OCR_VLM_MODEL`      | `qwen/qwen3-vl-235b-a22b-instruct` | OpenRouter model used to **seed** the default `qwen-vl` engine on a fresh DB. Connect more from the UI. |
| `OCR_DEVICE`         | `cpu`                              | CPU is the reliable on-device path (MPS unsupported by Docling's float64 ops). |
| `PRE_WARM_MODELS`    | `false`                            | `true` → load OCR models at startup (set for the demo).                        |
| `CORS_ORIGINS`       | `["http://localhost:5173"]`        | Browser origins allowed to call the API (JSON list). Must include the frontend's origin. |

## How it works

`POST /documents` (upload) → then per-document stage endpoints, each persisted and re-fetchable:
`POST /documents/{id}/prescan` → `…/ocr?engine=<engine>` → `…/structure?doc_type=<type>`
→ `…/decide`. Deterministic business rules run in code and the LLM can **explain but never
override** a hard-failed rule; low OCR/extraction confidence or a poor scan caps the decision
at `needs_review`. Reviewers can correct any extracted field
(`PATCH …/structure/field`), which is logged for review. See the full
[API reference](docs/API.md).

For **long, multi-page documents**, structuring doesn't flatten the pages into one window — it
splits the document into sections along the OCR engine's headings, extracts each separately, and
merges (with proximity-anchored grounding, cross-section dedup, and a whole-document grounding
fallback). See [large-document-extraction.md](docs/large-document-extraction.md).

## OCR models (multi-VLM)

OCR engines are a **swappable registry**. **Docling** (local, bbox-grounded) and **mock**
(offline) are code-defined; **VLM engines are data** — one OpenRouter model each, stored as
rows and managed at runtime. `qwen-vl` is seeded on first boot; connect more from
**Manage models** (upload screen) or the **Admin → Configuration** section. The picker's
add-model dropdown is populated **live** from OpenRouter's image-capable models (with a
curated fallback), and you can paste any model slug. Connecting a model is a row, not a code
change — every VLM speaks the same OpenAI-compatible API. Per-engine OCR results coexist, so
the inspector's **Compare** tab diffs two engines on the same page.

```
GET    /engines                    # engines selectable at upload (docling + enabled VLMs)
GET    /engines/catalog            # all connected VLM engines (enabled + disabled)
GET    /engines/openrouter-models  # live image-capable models for the add-model dropdown
POST   /engines                    # connect a model  { label, model, key?, enabled? }
PATCH  /engines/{key}              # enable/disable or relabel
DELETE /engines/{key}              # disconnect
```

## Spreadsheet inputs

`.xlsx` and `.csv` are first-class inputs that take a **native, non-image path** — a
spreadsheet is exact machine-readable data, so running OCR/VLM on it would be slower, cost
tokens, and *lose* fidelity. Instead:

- **Ingest parses the workbook** (openpyxl / stdlib `csv`) into `data/<doc_id>/sheets.json`,
  **one page per sheet**. No page images are rendered; pre-scan (an image-quality pass) is
  skipped.
- A built-in **`spreadsheet` engine** fills the OCR stage's slot: it emits one block per
  non-empty cell whose "bbox" encodes the **grid coordinate** `(col, row)` (not pixels),
  plus the sheet as table markdown. The rest of the pipeline is unchanged.
- **Structuring is identical** — the same LangExtract call maps the grid's markdown to the
  doc-type schema (which cell is the vendor, the total, …). It's an *extraction* problem,
  not a recognition one, so an invoice extracts straight from an `.xlsx` — no new doc type.
- The inspector renders an **interactive grid** (`GridViewer`) instead of a page image, and
  each grounded field highlights its **source cell** and shows its A1 reference (e.g.
  `Invoice!B2`). Multi-sheet workbooks get one tab per sheet.

Only the `spreadsheet` engine runs for these docs (the OCR-engine picker and the **Compare**
tab are hidden), and structuring done with the offline `mock` provider shows a "demo
extraction" hint, since mock returns placeholder fields rather than reading the sheet.

## Reviewing extractions

The workspace pairs the source (page image, or an interactive grid for spreadsheets) with
the structured result:

- **Color-coded, click-to-locate highlights** — every grounded field is boxed on the page
  (or highlighted in its **grid cell** for spreadsheets) in a stable color; the same color
  keys its entry in the panel. Click a field to jump to its page/cell and flash it.
  (VLM/table fields highlight the containing table's box, since only Docling exposes
  per-block boxes; spreadsheet fields also show their A1 cell reference.)
- **Tables render as tables**; long values wrap, so nothing is clipped.
- **Inline editing** — hover a field, click the pencil, correct the value. The model's
  original is preserved and the edit is logged (`FieldCorrectionRow`). A green/amber dot
  marks each field as *as-extracted* vs *edited*.
- **Corrections review** — a **Review edits** button opens a dialog showing each edit as
  *original → final* with the field's source box on the document.
- **Optional currency** — money-like numeric fields render with the document's currency when
  one was extracted; other extractions are unaffected.

## Signature detection

When a doc type declares a **signature field** (contracts do), structuring runs a best-effort
**YOLOv8-ONNX spatial post-pass** over the page images and adds each detected signature as a
first-class field — a **cropped thumbnail** in the panel plus a **box on the page**, using the
same grounding/highlight stack as every other field. It runs directly on the page pixels
(independent of the OCR engine), and **degrades to a silent no-op** if the optional deps or the
model weights aren't present — the rest of the pipeline is unaffected.

It's tuned for the app's domain (typed/printed documents with a handwritten signature) and
calibrated on a real-document eval; the confidence floor sits in the measured gap between true
signatures and noise. Fully-handwritten or degraded historical scans are a known model ceiling.
Full design, config, weights delivery, and measured accuracy:
**[docs/signature-extraction.md](docs/signature-extraction.md).**

## Admin panel

Toggle **Admin** in the header for a consolidated view (left-sidebar navigation):

- **Overview** — KPI cards (documents, avg extraction confidence, decisions, corrections,
  models, doc types) + status/decision breakdown bars.
- **Documents** — every document in a filterable (status chips + search), paginated table;
  click a row to open it in the workspace.
- **Corrections** — the cross-document edit log grouped by document, with **accordion** and
  **master–detail** lenses (edits are a strong signal of extraction errors).
- **Configuration** — the doc-type and OCR-model managers inline in one place.

```
GET /overview                      # consolidated counts for the dashboard
GET /corrections?document_id=      # logged field corrections (optionally per document)
```

## Configurable document types

A document type is **data, not code**: a declarative definition of (1) the fields to
extract and (2) the approval rules to enforce. Definitions are stored in SQLite and turned
into the runtime extraction spec + rule set by a generic interpreter, so adding a type
requires no Python.

- **Extraction** — a field list (`scalar` / `presence` / `list_scalar` / `list_composite` /
  `composite`, each `text` or `number`). The LangExtract prompt, a typed model, and the
  grounding/confidence assembly are all derived from it.
- **Rules** — a fixed primitive vocabulary: `presence`, `threshold`, `arithmetic`,
  `set_membership`, `field_dependency`, `uniqueness`, plus an **LLM-advisory** rule that is
  structurally capped at `needs_review` severity (it can never auto-`flag`). Decisions stay
  deterministic and auditable — the whole point of the system.
- **Built-ins** (`invoice`, `contract`) keep their definitions in code (they use coded
  rule escape hatches) and are read-only; **custom types** are validated JSON and can never
  inject code.

Manage types from the **upload screen → "Manage types"** dialog (create / edit / delete,
with a preview), or via the REST API:

```
GET    /doc-types                 # list (built-ins + custom)
POST   /doc-types                 # create a custom type
PUT    /doc-types/{name}          # edit a custom type (built-ins are 403)
DELETE /doc-types/{name}          # delete (409 if documents still use it)
POST   /doc-types/{name}/preview  # dry-run a definition against sample text
```

### Create with AI (wizard)

The **"Create with AI"** button (in the Manage-types dialog) opens a wizard where an LLM
agent asks questions, ingests uploaded **process** docs and **example** docs (OCR'd via
`qwen-vl`, or read directly if text), and iteratively refines a **markdown spec** of the
type. The user answers each question in its own box (Enter = newline, Ctrl+Enter = save &
advance, **Send** submits all) and can **annotate** the spec via an embedded
[Plannotator](https://github.com/backnotprop/plannotator) session. When the agent is
done it emits a validated `DocTypeCreate`, which is committed in one shot and then opened
in the manual builder for fine-tuning.

The agent is **stateless** (the frontend re-sends the transcript + ingested texts + spec +
annotations each turn) and its output goes through the same `validate_custom_*` +
`build_spec` checks as a hand-built type (with one auto-repair turn), so a bad LLM payload
degrades gracefully — it can never create an invalid type or inject code. Requires
`OPENROUTER_API_KEY` (real per-turn LLM calls). Endpoints:

```
POST   /doc-types/assist                       # one Q&A turn -> {questions, spec_markdown, done, draft_doctype}
POST   /doc-types/assist/ingest                # upload a process/example doc -> extracted text
POST   /doc-types/assist/annotate              # spawn a Plannotator session over the spec -> {session_id, url}
GET    /doc-types/assist/annotate/{session_id} # poll for the user's annotations
DELETE /doc-types/assist/annotate/{session_id} # cancel a session
```

> **Plannotator** is a CLI that boots a short-lived **loopback** web server; the backend
> spawns it, waits until it's listening, and returns its URL for the frontend to iframe;
> annotations come back on the subprocess's stdout. This works when backend + browser are
> on the **same machine** (a local/desktop tool); a deployed multi-user version would need
> a native in-app annotation layer instead.

## Where the code lives (for contributors)

| Area | Path |
| --- | --- |
| Pipeline stages | `backend/app/pipeline/` (`prescan`, `ocr/`, `structuring`, `agent`) |
| OCR engine registry (docling/mock/spreadsheet + generic `VLMEngine`) | `backend/app/pipeline/ocr/` · engines API `backend/app/routes/engines.py` |
| Spreadsheet ingest + engine (CSV/XLSX → grid, cell-coord grounding) | `backend/app/storage.py` (`_normalize_spreadsheet`) · `backend/app/pipeline/ocr/spreadsheet.py` · UI `src/features/inspector/GridViewer.tsx` |
| Field edits + correction log | `PATCH …/structure/field` in `backend/app/routes/pipeline.py` · `GET /corrections` in `backend/app/routes/corrections.py` · `FieldCorrectionRow` in `models.py` |
| Admin overview aggregates | `backend/app/routes/overview.py` |
| Extraction engine (declarative → spec) | `backend/app/extraction/definition.py` (`build_spec`) |
| Section-aware extraction + proximity/fallback grounding ([docs](docs/large-document-extraction.md)) | `backend/app/pipeline/structuring.py` · `backend/app/extraction/base.py` (`_ground`/`_find_nearest`) |
| Signature detection (YOLOv8-ONNX post-pass → bbox + crop) ([docs](docs/signature-extraction.md)) | `backend/app/pipeline/signature_detector.py` · injected in `structuring.py` (`_detect_signatures`) · crop `storage.py` (`save_signature_crop`) |
| Rule engine (primitives + escape hatches) | `backend/app/rules/definition.py` (`build_ruleset`) |
| Doc-type registry (built-ins in code + custom from DB) | `backend/app/doc_types.py` |
| Inspector: highlights + color model | `src/lib/grounding.ts` · `src/lib/highlights.ts` · `src/features/inspector/` |
| Admin panel (overview/documents/corrections/config) | `src/features/admin/` |
| Definition (de)serialization + validation | `backend/app/serialization.py` |
| CRUD + preview routes | `backend/app/routes/doc_types.py` |
| AI wizard agent | `backend/app/pipeline/doctype_assistant.py` |
| Plannotator subprocess manager | `backend/app/annotate_proc.py` |
| Wizard routes (assist/ingest/annotate) | `backend/app/routes/doctype_assist.py` |
| DB models (incl. `DocTypeDefinitionRow`) | `backend/app/models.py` |
| Builder UI + wizard | `src/features/doctypes/` (`wizard/` for Create-with-AI) |
| Generic field rendering | `src/lib/fields.ts` · API client `src/lib/api.ts` · types `src/lib/doc-type-schema.ts` |

## Tests

```bash
make test    # backend pytest — fully offline (mock OCR engine + mock LLM provider, no API key)
make smoke   # offline end-to-end: full pipeline + doc-type CRUD/preview + wizard reachability

# Frontend (Node 22): vitest pure-logic + typecheck/build + lint
pnpm test && pnpm build && pnpm lint
```

Backend tests are 100% offline (mock providers). Frontend tests cover pure logic only
(reducers, payload building, the `pascalCase`↔backend `_pascal` parity) — UI is validated
via `pnpm build` (strict `tsc`) + `pnpm lint`. There is no frontend test runner beyond vitest.

## License

MIT © 2026 Made By Agents — see [LICENSE](LICENSE).
