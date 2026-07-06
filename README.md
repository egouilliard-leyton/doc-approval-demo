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
  add-model list is populated live from OpenRouter. Each document type can **prefer an engine
  with an automatic fallback chain** (or reach an external service via the `digibot` adapter),
  and the picker gains an **"Auto"** option that routes by doc type. See
  [OCR models](#ocr-models-multi-vlm).
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
- **Human-in-the-loop that learns** — edit any extracted value inline; every correction is
  logged, **exportable as JSONL labels**, and auto-injected as **few-shot examples** so a doc
  type stops repeating the same mistakes. See [Reviewing extractions](#reviewing-extractions).
- **Accuracy & benchmarking** — a golden-set harness scores any engine on the same documents,
  per field **and by line-item/table row**, and stores every scored run. See
  [Accuracy & benchmarking](#accuracy--benchmarking).
- **Programmatic extraction API** — `POST /extract` runs the whole pipeline on one file (or
  `/extract/batch` on many) and returns structured fields + a decision, no UI needed. See
  [Black-box extraction API](#black-box-extraction-api).
- **Multi-document cases** — drop several documents at once and they become a **case**: each
  is classified and extracted, then reconciled across documents into one cross-checked
  approve / flag decision. See [Multi-document cases](docs/multi-document-cases.md).
- **Shareable deep links** — every place in the app has a real hash URL that updates the
  address bar and restores on cold load (back/forward included), so any document, tab, field,
  case, or admin view can be copied and shared. See [Shareable links](#shareable-links).
- **Admin panel** — a consolidated **KPI dashboard**, documents, corrections log, a
  low-confidence **review queue**, **accuracy** runs, and configuration. See
  [Admin panel](#admin-panel).
- **Outbound digital signing** — seal a PDF with a real **PAdES / X.509** signature that
  validates against a trust chain, either an **approved** inbound document or a **generated**
  template output (the *Solicitud de Transmisión* you transmit). Draws a **visible** stamp,
  placed at the template's signature marker (or a configurable corner). A manual action, off the
  inbound pipeline. See [`docs/digital-signing.md`](docs/digital-signing.md).

Built as the demo for a video on _the best OCR tools for AI agents_. The pipeline is
modular — each stage (**pre-scan → OCR → structure → decide**) is a swappable component,
so OCR engines can be compared side-by-side on camera. **Signing** is a separate, manual,
post-decision action (not part of the auto-run).

📚 Full feature docs: **[`docs/`](docs/README.md)**.

> **📚 Full documentation** lives in [`docs/`](docs/README.md):
> [Architecture](docs/ARCHITECTURE.md) · [API reference](docs/API.md) ·
> [Roadmap & work log](docs/ROADMAP.md) · [Validation rules](docs/validation-rules.md).
> Deep dives: [Multi-document cases](docs/multi-document-cases.md) ·
> [Document generation](docs/document-generation.md) ·
> [Large-document extraction](docs/large-document-extraction.md) ·
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

# 4. (Optional) Enable real digital signing (PAdES via pyhanko).
cd backend && uv sync --extra signing   # omit to use the offline "mock" provider
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
# open http://localhost:5173 — drop one document (from backend/samples/) to analyze it,
# or several to cross-check them as a case
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
| `SIGNING_PROVIDER`   | `pyhanko`                           | `pyhanko` (real PAdES, needs `--extra signing`) \| `mock` (offline).           |
| `SIGNING_LEVEL`      | `PAdES-B-B`                         | `PAdES-B-B` \| `PAdES-B-T` (B-T needs `SIGNING_TSA_URL`).                       |
| `SIGNING_TSA_URL`    | _(empty)_                          | RFC 3161 timestamp-authority URL; set to enable B-T.                           |
| `SIGNING_VISIBLE`    | `true`                             | Draw a visible stamp (at the template marker, else a corner). `false` → invisible signature. |
| `SIGNING_CERT_DIR`   | `certs`                            | Demo signer cert dir, outside `data/` and gitignored (see signing doc).        |

See [`docs/digital-signing.md`](docs/digital-signing.md) for the full `SIGNING_*` set and the
demo-cert security notes.

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

## Black-box extraction API

The staged endpoints are ideal for the UI, but automated pipelines want **one call in, structured
data out**. `POST /extract` takes a single file, runs the **whole** pipeline
(upload → prescan → OCR → [classify] → structure → decide) synchronously, and returns the
structured fields, the decision, and a `document_id`:

```
POST /extract          # one file (multipart) -> { document_id, doc_type, structured, decision, … }
POST /extract/batch    # N files -> per-file results with failure isolation (always HTTP 200)
```

`doc_type` may be **omitted to auto-classify**; `ocr_engine` may be omitted to use
[doc-type routing](#per-doc-type-routing--the-auto-engine). It reuses the exact same stage
functions and persistence as the staged routes — so nothing is a black box in the end: every
`/extract` run lands a normal document you can open and inspect in the UI. Batch runs are
sequential (the invoice-duplicate scan reads other documents' committed decisions) and isolate
per-file failures. Try it live from FastAPI's Swagger UI at **`/docs`**.

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

### Per-doc-type routing + the "Auto" engine

You don't have to pick an engine by hand. Each **document type** can declare a **preferred OCR
engine plus an ordered fallback chain**; the chain advances to the next engine when the current
one errors, returns empty text, or scores below `OCR_FALLBACK_CONFIDENCE_THRESHOLD`, and the
engine that actually produced the result is recorded on the OCR result. The upload picker's
**"Auto — use doc-type routing"** option (`resolve_engine_chain`) leaves the engine unset so this
routing decides; picking a concrete engine still pins it. Routing is a pipeline concern separate
from the read-only definition, so it's editable on **built-ins** (`invoice`/`contract`/`po`/
`delivery_note`) as well as custom types:

```
PATCH  /doc-types/{name}/routing   # { preferred_ocr_engine, ocr_fallback_engines[] } (built-ins OK)
```

### External-service adapter (`digibot`)

Beyond local Docling and OpenRouter VLMs, the built-in **`digibot`** engine is a clean template
for wrapping **any external document-AI service** (Rossum/proprietary) behind the same
`OCREngine` interface: it POSTs each page image to an HTTP endpoint and maps the JSON back into
the normalized OCR shape. It's configured entirely via env (`DIGIBOT_ENDPOINT`,
`DIGIBOT_API_KEY`) and **degrades cleanly when unset** — it's hidden from the picker and raises a
clean 400 rather than booting a broken engine.

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
- **Corrections that teach** — the log is the app's ground truth, used two ways. **Export** it
  as JSONL labels (`GET /corrections/export?shape=raw|examples[&doc_type=][&include_text=]` —
  `raw` = one line per correction; `examples` = one reviewer-approved record per document,
  optionally with the OCR text). And **few-shot self-improvement**: a doc type's past *scalar-field*
  corrections are auto-injected as `label: value` examples into its extraction prompt (bounded by
  `FEW_SHOT_MAX_EXAMPLES`, deduped newest-first), so it stops repeating the same mistakes. Both are
  no-ops for the offline `mock` provider and when `FEW_SHOT_CORRECTIONS_ENABLED=false`.
- **Optional currency** — money-like numeric fields render with the document's currency when
  one was extracted; other extractions are unaffected.

## Shareable links

Every navigable place in the app has a real, shareable **hash URL** that updates the address
bar as you move and restores that exact place when the link is opened cold (browser back /
forward work throughout). A **Copy link** button sits on the document, case, and admin
headers.

The router is hand-rolled — no `react-router`. Its core is a pure, unit-tested mapping between
the location hash and a typed `Route` (`src/lib/route.ts` + `route.test.ts`); the React seam and
the header button live in `src/features/routing/`. The URL grammar:

| URL | Opens |
| --- | --- |
| `#/` | Home — the unified upload entry + recent work |
| `#/documents/<id>?tab=<ocr\|structured\|decision\|compare>&field=<path>` | A document, focused on a tab (and optionally a field) |
| `#/cases` · `#/cases/<id>?member=<docId>` | The cases list · one case (optionally drilled into a member document) |
| `#/admin/<overview\|documents\|corrections\|review\|eval\|config>` | An admin section |
| `#/admin/config/doctype/<name>` | The doc-type builder for one type |
| `#/admin/eval?run=<id>` | One evaluation run's expected-vs-actual detail |

A shared `#/cases/<id>` link cold-loads the case into a **read-only** overview (a fresh fetch
of the saved case + its reconciliation/decision) — the saved result, not a resumed live
classify/reconcile orchestration.

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

- **Overview** — a **program KPI dashboard**: four headline cards — **precision** (accuracy from
  the eval harness, incl. line-item), **coverage** (documents per doc type), **throughput**
  (documents/day, 30-day sparkline), and **maintenance** (corrections/day) — over the original
  count/confidence/decision cards, plus a per-doc-type table. All fields are additive on
  `GET /overview`.
- **Documents** — every document in a filterable (status chips + search), paginated table;
  click a row to open it in the workspace.
- **Corrections** — the cross-document edit log grouped by document, with **accordion** and
  **master–detail** lenses (edits are a strong signal of extraction errors), plus the JSONL
  **export** controls.
- **Review queue** — the individual **low-confidence fields** worth a human's attention
  (confidence below a threshold, excluding already-edited and presence-kind fields), grouped by
  document, worst-first; click a field to deep-link straight to it in the inspector and correct
  in place (which then feeds the few-shot loop).
- **Accuracy** — the [benchmark harness](#accuracy--benchmarking): per-engine **Run** buttons and
  an expected-vs-actual drill-in that opens the source document.
- **Configuration** — the doc-type and OCR-model managers inline in one place.

```
GET /overview                      # KPI dashboard: counts + precision/coverage/throughput/maintenance
GET /corrections?document_id=      # logged field corrections (optionally per document)
GET /review-queue?threshold=&doc_type=   # low-confidence, unedited fields, grouped by document
```

## Accuracy & benchmarking

"Is it actually right?" gets a real answer. A **golden-set scorer** measures extraction accuracy
against known-good expected outputs (`backend/golden/*.json`) — **per field** (both exact and
normalized match) **and, the headline metric for invoices, line-item / table-row accuracy**
(matched vs expected vs extracted rows). Any OCR engine can be run over the same golden documents,
and every scored run is persisted (`EvalRunRow`) so you can compare engines and track regressions.

The **Admin → Accuracy** section (deep-linkable, `#/admin/eval?run=<id>`) gives each golden a
per-engine **Run** button and an **expected-vs-actual** drill-in that opens the source document to
see where a field went wrong. The overview KPI dashboard's **precision** card reads straight from
these runs.

```
GET  /eval/goldens          # the golden catalogue (compact)
GET  /eval/goldens/{id}     # one golden's full expected values
POST /eval/run              # score a golden { golden_id, engine?, provider?, document_id? } and persist the run
GET  /eval/runs             # persisted scored runs, newest first (filter by golden/doc-type/engine)
GET  /eval/runs/{id}        # one run in full detail
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
agent asks questions, ingests uploaded **process** docs and **example** docs (OCR'd via the
configured OCR engine, or read directly if text), and iteratively refines a **markdown
spec** of the type. Opening the wizard shows a **fixed** starting template + first
questions immediately (no LLM call); the agent runs only from the first **Send**. The user
answers each question in its own box (Enter = newline, Ctrl+Enter = save & advance, **Send**
submits all) and can **annotate** the spec via an embedded
[Plannotator](https://github.com/backnotprop/plannotator) session. If a turn comes back with
no follow-up questions but isn't finished, a free-form continue/finalize box keeps the
conversation moving. When the agent is done it emits a validated `DocTypeCreate`, which is
committed in one shot and then opened in the manual builder for fine-tuning.

The agent can author the **full** schema — every extraction kind (including `signature`
fields) and all **23** rule primitives (equality, aggregate, format/checksum,
date-constraint, the expression DSL, `signature_presence`, …). It doesn't hand-list them:
the prompt's field/rule/DSL catalogue is generated from the same dataclasses the validator
uses (`pipeline/doctype_schema_reference.py`), so it stays in lockstep with what a
hand-built type can express. The agent is **stateless** (the frontend re-sends the
transcript + ingested texts + spec + annotations each turn) and its output goes through the
same `validate_custom_*` + `build_spec` checks as a hand-built type (with one auto-repair
turn), so a bad LLM payload degrades gracefully — it can never create an invalid type or
inject code. Requires `OPENROUTER_API_KEY` (real per-turn LLM calls). Endpoints:

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
| Admin overview aggregates + KPI dashboard (precision/coverage/throughput/maintenance) | `backend/app/routes/overview.py` |
| Accuracy harness (scorer + runner + goldens) | `backend/app/evaluation/` · goldens `backend/golden/*.json` · API `backend/app/routes/evaluation.py` · UI `src/features/admin/EvalSection.tsx` |
| Review queue (low-confidence, unedited fields) | `backend/app/routes/review_queue.py` · UI `src/features/admin/ReviewQueueSection.tsx` |
| Active learning (corrections export + few-shot injection) | `GET /corrections/export` in `backend/app/routes/corrections.py` · `build_correction_examples` in `backend/app/extraction/definition.py` · injected in `pipeline/structuring.py` |
| Black-box extraction API (whole pipeline in one call) | `backend/app/routes/extract.py` |
| OCR routing + fallback chain + external adapter | `resolve_engine_chain`/`run_ocr_chain` in `backend/app/pipeline/ocr/__init__.py` · `backend/app/pipeline/ocr/digibot.py` · `PATCH /doc-types/{name}/routing` in `backend/app/routes/doc_types.py` |
| Extraction engine (declarative → spec) | `backend/app/extraction/definition.py` (`build_spec`) |
| Section-aware extraction + proximity/fallback grounding ([docs](docs/large-document-extraction.md)) | `backend/app/pipeline/structuring.py` · `backend/app/extraction/base.py` (`_ground`/`_find_nearest`) |
| Signature detection (YOLOv8-ONNX post-pass → bbox + crop) ([docs](docs/signature-extraction.md)) | `backend/app/pipeline/signature_detector.py` · injected in `structuring.py` (`_detect_signatures`) · crop `storage.py` (`save_signature_crop`) |
| Rule engine (primitives + escape hatches) | `backend/app/rules/definition.py` (`build_ruleset`) |
| Doc-type registry (built-ins in code + custom from DB) | `backend/app/doc_types.py` |
| Inspector: highlights + color model | `src/lib/grounding.ts` · `src/lib/highlights.ts` · `src/features/inspector/` |
| Hash router / deep links | `src/lib/route.ts` · `src/features/routing/` |
| Admin panel (overview/documents/corrections/review/eval/config) | `src/features/admin/` |
| Definition (de)serialization + validation | `backend/app/serialization.py` |
| CRUD + preview routes | `backend/app/routes/doc_types.py` |
| AI wizard agent | `backend/app/pipeline/doctype_assistant.py` |
| Wizard prompt schema catalogue (derived from the validator's dataclasses) | `backend/app/pipeline/doctype_schema_reference.py` |
| Plannotator subprocess manager | `backend/app/annotate_proc.py` |
| Wizard routes (assist/ingest/annotate) | `backend/app/routes/doctype_assist.py` |
| DB models (incl. `DocTypeDefinitionRow`) | `backend/app/models.py` |
| Builder UI + wizard | `src/features/doctypes/` (`wizard/` for Create-with-AI) |
| Generic field rendering | `src/lib/fields.ts` · API client `src/lib/api.ts` · types `src/lib/doc-type-schema.ts` |

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

An **Edit / Preview** toggle in the editor renders the persisted styled HTML in a sandboxed
iframe — faithful to the export. This matters because **TipTap flattens complex HTML on load**
(dropping divs/classes/tables), so plain rich-text typing + Save is **lossy** for styled
layouts; the faithful ways to view and change a styled template are the **Preview** toggle and
the **AI edit** agent (which writes raw HTML). A placeholder ↔ doc-type **lint** flags stale
bindings as an advisory badge. Full design: **[`docs/document-generation.md`](docs/document-generation.md)**.

Key endpoints (all under `/templates`): CRUD, `POST /{id}/source`, `GET /{id}/catalogue`,
`POST /{id}/suggest-mapping`, `POST /{id}/generate`, `POST /{id}/agent` (SSE),
`POST /{id}/qa`, `GET /{id}/revisions`, `POST /{id}/revisions/{rev}/restore`.

> **License note:** all generation libraries are permissive (BSD/MIT/Apache). New rasterization
> uses **pypdfium2** (not the AGPL PyMuPDF, which is retained only for the pre-existing ingestion
> path). WeasyPrint needs system **Pango + GDK-PixBuf** (`apt install libpango-1.0-0 libgdk-pixbuf2.0-0`);
> without them, DOCX output still works and PDF degrades gracefully. Install the generation extra
> with `uv sync --extra docgen` (already included in `make install`).

Once a document is **approved**, three signing endpoints become available (a manual,
post-decision step — not part of the auto-run): `POST /documents/{id}/sign` seals the PDF with
a real X.509 signature and advances it to `signed` (gated: `400` if not a PDF, `409` unless
decided **and** approved); `GET /documents/{id}/sign` returns the persisted result; and
`POST /documents/{id}/validate-signature` re-verifies it. Re-deciding invalidates any prior
signature. See [`docs/digital-signing.md`](docs/digital-signing.md).

## Tests

```bash
make test    # backend pytest — fully offline (mock OCR/LLM/vision providers, no API key)
make smoke   # offline end-to-end: full pipeline + doc-type CRUD/preview + wizard reachability

# Frontend (Node 22): vitest pure-logic + typecheck/build + lint
pnpm test && pnpm build && pnpm lint
```

Backend tests are 100% offline (mock providers). Frontend tests cover pure logic only
(reducers, payload building, the `pascalCase`↔backend `_pascal` parity) — UI is validated
via `pnpm build` (strict `tsc`) + `pnpm lint`. There is no frontend test runner beyond vitest.

The template/generation pipeline is likewise fully offline-tested (WeasyPrint renders real
PDFs, pypdfium2 rasterizes for real, the LLM/vision legs use deterministic mocks), including
SSE streaming, vision-QA, and end-to-end smoke tests for both generation journeys.

## License

MIT © 2026 Made By Agents — see [LICENSE](LICENSE).
