# Architecture

This document describes how the Document Auto-Approval System is put together: the
end-to-end pipeline, the swappable component layers, the data model, and the frontend.

> For a feature-level overview and setup, see the [root README](../README.md). For the
> REST surface, see [API.md](./API.md). For history and what's next, see
> [ROADMAP.md](./ROADMAP.md).

---

## 1. High-level shape

```
┌─────────────────────────── Browser (Vite + React 19) ───────────────────────────┐
│  Workspace view                              Admin view                          │
│  ┌───────────────┬───────────────┐          ┌──────────┬─────────────────────┐   │
│  │ Page image    │ Inspector      │          │ sidebar  │ Overview / Documents │   │
│  │ (bbox overlay)│ OCR/Structured │          │          │ Corrections / Config │   │
│  │               │ /Decision/Cmp  │          └──────────┴─────────────────────┘   │
│  └───────────────┴───────────────┘                                               │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                     │  REST (JSON)  — VITE_API_BASE_URL
┌────────────────────────────────────▼──────────────────────────────────────────┐
│  FastAPI (backend/app)                                                          │
│  routes/ ── documents · pipeline · doc_types · doctype_assist · engines ·       │
│             corrections · overview                                              │
│  pipeline/ ── prescan → ocr/ → structuring → agent (decide)                     │
│  extraction/ (declarative → spec)   rules/ (primitives → ruleset)               │
│  doc_types.py (registry)   models.py (SQLModel)   storage.py (files)            │
└───────────────┬───────────────────────────────────┬────────────────────────────┘
                │ SQLite (backend/data/app.db)        │ OpenRouter (OpenAI-compatible)
                │ + files (backend/data/<doc_id>/)    │ VLM OCR · LangExtract · decision · wizard
```

- **Backend** — FastAPI, Python 3.12, `uv`. Owns the pipeline and the REST API.
- **Frontend** — Vite + React 19 + TypeScript at the repo root; Tailwind v4 + shadcn/ui.
  **No router** — view switching is local state (see [§6](#6-frontend)).
- **Storage** — SQLite for metadata + a per-document directory on disk for page images,
  OCR markdown, and artifacts. Zero cloud setup.
- **External model calls** — everything model-shaped goes through **OpenRouter** with one
  `OPENROUTER_API_KEY`: VLM OCR, LangExtract structuring, the decision agent, and the
  doc-type wizard.

---

## 2. The pipeline

A document moves through four persisted, independently re-runnable stages. Each stage
writes its result under `PipelineRun.stage_results[<stage>]` and advances the document's
status.

```
upload ─▶ prescan ─▶ ocr ─▶ structure ─▶ decide
uploaded  prescanned ocr_done structured  decided | needs_review
```

| Stage | Entry point | What it does |
| --- | --- | --- |
| **Ingest** | `POST /documents` | Rasterize PDF/image pages to PNG at `RENDER_DPI` + thumbnails; **or**, for a spreadsheet (`.xlsx`/`.csv`), parse it into `sheets.json` (one page per sheet, no images). Persist the `Document`. |
| **Pre-scan** | `pipeline/prescan.py` | Quality metrics (resolution, sharpness, contrast, brightness, skew), optional deskew/clean. Advisory `warn` verdict. **Skipped for spreadsheets** (no image to score). |
| **OCR** | `pipeline/ocr/` | Run a swappable engine over the page PNGs → normalized `OCRResult` (text, blocks+bbox, tables). Spreadsheets are forced to the native `spreadsheet` engine (a parser, not a recognizer). See [§3](#3-ocr-engine-layer). |
| **Structure** | `pipeline/structuring.py` | Turn OCR text into validated, grounded fields for the doc type. See [§4](#4-structuring). |
| **Decide** | `pipeline/agent.py` + `rules/` | Run deterministic rules in code; an LLM explains but can never override a hard fail. Output `approve` / `flag` / `needs_review`. See [§5](#5-rules--decision). |

Design invariant: **deterministic rules are authoritative**; the LLM is advisory and is
structurally capped at `needs_review` severity. Low OCR/extraction confidence or a poor
scan caps the decision at `needs_review`.

---

## 3. OCR engine layer

`backend/app/pipeline/ocr/` is a **registry of swappable engines** behind one interface
(`OCREngine`, `base.py`). Every engine emits the same normalized `OCRResult` so downstream
stages are engine-agnostic.

- **`docling`** (`docling.py`) — local layout model: text blocks **with bounding boxes**,
  tables (with a per-table bbox), reading order. The spatially-grounded engine that powers
  on-image highlighting. No per-block confidence.
- **`mock`** (`mock.py`) — deterministic, offline; used by tests and `make smoke`.
- **`spreadsheet`** (`spreadsheet.py`) — **not OCR/VLM**: for `.xlsx`/`.csv` it reads the
  parsed grid (`sheets.json`) and emits one `OCRPage` per sheet, one block per non-empty
  cell whose `bbox` encodes the **grid coordinate** `(col, row, col+1, row+1)` (not pixels),
  plus the sheet as `OCRTable` markdown. This reuses the whole grounding stack: the frontend
  matches a field to its cell by text and reads the bbox as a cell reference. Selected
  automatically for spreadsheet docs (not offered in the picker); overrides `run()` since
  there are no page PNGs to read.
- **VLM engines** (`vlm.py`, `VLMEngine`) — **data-driven**. Each is one OpenRouter model
  (a `VlmEngineRow`), called over the OpenAI-compatible API to transcribe each page to
  Markdown. A VLM returns text but no bboxes/confidence. `qwen_vl.py` is a thin back-compat
  shim (`QwenVLEngine` = the seeded `qwen-vl` engine).

Resolution is DB-aware:

- `get_engine(name, session)` → a static factory (`docling`/`mock`/`spreadsheet`) or, for a
  VLM, an enabled `VlmEngineRow` built into a `VLMEngine(name, model)`.
- `available_engines(session)` / `run_ocr(doc, name, session)` are the thin wrappers.
- `prewarm(names)` only warms static engines (VLM warming would bill a real call).

**Multi-VLM.** Connecting a model is a row, not a code change — every VLM speaks the same
API behind OpenRouter. The `/engines` routes manage the registry; the add-model dropdown is
populated **live** from OpenRouter's model list (filtered to image-capable models), with a
curated fallback when the key/network is absent. See the settings UI in [§6](#6-frontend).

> Per-engine OCR results coexist under `stage_results["ocr"][<engine>]`, so the inspector's
> **Compare** tab can diff engines on the same document.

---

## 4. Structuring

`pipeline/structuring.py` turns OCR text into a validated, **source-grounded** field model
for the resolved doc type. Two providers behind one entry point:

- **`langextract`** — [LangExtract](https://github.com/google/langextract) pointed at
  OpenRouter. Given the doc type's prompt + few-shot examples, it extracts typed spans.
- **`mock`** — deterministic, offline (tests).

Key mechanics:

- **Tables are fed to the extractor.** OCR engines (Docling especially) keep tables out of
  `full_text`, so invoice numbers, dates and totals live only in `page.tables[].markdown`.
  `_build_structuring_text()` appends each page's table markdown to that page's text and
  builds matching page offsets, so the model sees the table values **and** grounding still
  maps a span back to its page. This is why the invoice example's few-shots include a
  Markdown-table case.
- **Grounding + confidence** (`extraction/base.py`) — each extracted span is located in the
  source text (**proximity-anchored** to the occurrence nearest the extractor's offset hint, so
  a repeated token in a long doc doesn't snap to page 1); alignment quality
  (`exact`/`partial`/`ungrounded`) × propagated OCR confidence yields a per-field confidence.
  The grounding map drives the inspector's boxes.
- **Table backfill fallback** — for invoices, empty line items are best-effort backfilled
  from Docling tables (capped low confidence).
- **Human corrections** — a reviewer can edit any field
  (`PATCH /documents/{id}/structure/field`). The edit is written into the stored structure
  (with the model's `original_value` pinned and `edited: true` set) and logged to
  `FieldCorrectionRow`. A plain JSON column doesn't track nested mutations, so the write
  uses SQLAlchemy `flag_modified`. Re-running Structure produces a fresh extraction and
  clears `edited` flags; the correction **log** rows persist for the audit trail.

### 4a. Declarative doc types

A doc type is **data, not code** — a declarative definition of (1) the fields to extract
and (2) the approval rules — interpreted at runtime:

- `extraction/definition.py` → `build_spec()` turns a field list (`scalar` / `presence` /
  `list_scalar` / `list_composite` / `composite`, each `text` or `number`) into the
  LangExtract prompt, a typed Pydantic model, and the grounding/assembly.
- **Built-ins** (`invoice`, `contract`) keep their definitions in code (they use coded rule
  escape hatches) and are read-only. **Custom types** are validated JSON in SQLite
  (`DocTypeDefinitionRow`) and can never inject code.
- `doc_types.py` is the registry (built-ins from code + custom rebuilt from DB rows).
- The **Create-with-AI wizard** (`pipeline/doctype_assistant.py` + `routes/doctype_assist.py`)
  is a stateless agent that designs a type conversationally, then emits a validated
  `DocTypeCreate` through the same validators as a hand-built type.

### 4b. Large documents: section-aware extraction

For long, multi-page documents the `langextract` provider does **not** flatten every page into
one window. `run_structuring` partitions the document into **sections** along the headings the
OCR engine already emits (`docling` `section_header`/`title` block labels, or `#` markdown
headings from a VLM), extracts each section against its own section-scoped `GroundingCtx`, then
merges the per-section field models. This localises extraction, keeps grounding accurate
(section-relative offsets → real page numbers), and layers on **opt-in cross-section list dedup**
(collapses the same entity extracted from two sections — e.g. `parties`) and a **whole-document
grounding fallback** (re-grounds a field whose span spilled across a section boundary). Small /
mock / spreadsheet / header-less docs reproduce the single-blob path byte-for-byte. **Full
design, config, and gates: [large-document-extraction.md](./large-document-extraction.md).**

### 4c. Signature detection

A doc type may declare a field of `kind="signature"`; structuring then runs a best-effort YOLOv8s
**ONNX** spatial post-pass (`_detect_signatures`, via `onnxruntime` — no `ultralytics`) over the
page PNGs, emitting located + cropped signature regions that reuse the grounding/render stack
(`Grounding.bbox` + `FieldValue.image_url`, both optional/`None`-defaulted so text-grounded fields
are untouched). It runs on the page pixels independently of the OCR engine, is **contract-only**
today, and is a **graceful no-op** without the optional deps or model file. The confidence floor
(`0.45`) was calibrated on a real-document eval; fully-handwritten/degraded scans are a known model
ceiling. Full design, weights delivery, and measured accuracy:
**[signature-extraction.md](./signature-extraction.md).**

---

## 5. Rules & decision

`backend/app/rules/` evaluates a doc type's rule set against the extracted fields, in code:

- **Primitive vocabulary** — a broad set of declarative validation primitives interpreted
  from JSON: equality/comparison (`equality` with exact/normalized/regex/fuzzy modes,
  `set_membership`, `threshold`, `numeric_range`, `percentage_tolerance`), arithmetic &
  aggregation (`arithmetic`, `aggregate` — e.g. *total == Σ line_items*, `expression` — a
  **sandboxed formula DSL**), dates (`date_constraint`), presence & cardinality
  (`presence`, `field_dependency`, `conditional_presence`, `mutual_exclusivity`,
  `at_least_n_of`, `required_together`), format/checksum (`format` — IBAN/Luhn/email/UUID/
  ISO codes), text (`contains`, `length_bounds`), confidence/provenance (`field_confidence_floor`,
  `grounded_on_page`), `signature_presence`, `uniqueness`, plus an **LLM-advisory** rule
  structurally capped at `needs_review` (it can never auto-`flag`). Each emits a
  `Check(name, passed, detail, severity)`. **The full catalogue, the DSL, and how to add a
  primitive are in [validation-rules.md](./validation-rules.md).**
- **Safety** — custom (user-built) types are validated JSON that can *never* carry code; the
  `expression` DSL is evaluated by a default-deny AST interpreter (no `eval`), not arbitrary
  Python. Built-in `invoice`/`contract` may use a coded escape hatch; custom types cannot.
- `pipeline/agent.py` reconciles: the LLM proposes a decision + reasons, but any hard-failed
  code rule wins, and low confidence caps at `needs_review`. The `DecisionResult` carries a
  rule-by-rule trace, citations built from the grounding map, and the LLM's pre-reconciliation
  proposal — so every decision is auditable.

---

## 6. Frontend

Vite + React 19, no router. `App.tsx`'s `Shell` holds a top-level **view** state and a
header **Workspace / Admin** toggle.

### Pipeline state

`features/pipeline/usePipeline.ts` is a `useReducer` state machine shared via
`PipelineContext`. It owns the open document, per-engine OCR results, structure, decision,
the active engine, and the sequential auto-run. `useEngines` (`features/upload/`) fetches the
selectable engines and refetches on window focus.

### Workspace

- **Upload view** (`features/upload/`) — dropzone, doc-type + engine pickers (both collapse
  from pills to a searchable **Combobox** past a threshold), and the document library.
- **`features/Workspace.tsx` → `inspector/SplitInspector.tsx`** — left: `PageViewer`, or
  `GridViewer` for spreadsheets; right: tabs `OCR text` · `Structured` · `Decision` ·
  `Compare` (Compare hidden for spreadsheets — single engine).
- **Highlighting** (`lib/highlights.ts` + `lib/grounding.ts`) — every grounded field resolves
  to a page **region**; fields sharing a physical region (e.g. all values read from one table)
  share a color and one box. `PageViewer` draws persistent, **color-coded** boxes; clicking a
  field in the panel jumps to its page and **flashes** its box (color-matched). For
  spreadsheets, `buildHighlights` branches on `engine_name === "spreadsheet"` and reads each
  matched block's bbox as a **cell** (`cellsForField`); `GridViewer` renders the sheet as an
  HTML grid (fetched from `sheets.json`) and highlights the source `<td>`.
- **Structured panel** (`inspector/StructuredPanel.tsx`) — color-coded fields; tables rendered
  as tables; **inline editing** (pencil → input → save) with a green/amber status dot
  (as-extracted vs edited) and an "edited" badge showing the original; optional **currency**
  formatting on money-like numeric fields when the doc has a currency; a **Review edits**
  button opening `CorrectionsDialog` (original→final + the field's source box/cell). For
  spreadsheets, each field shows an **A1 cell reference** badge (e.g. `Invoice!B2`,
  `cellRefsForFields`); a **mock-extraction hint** appears when the result used the `mock`
  provider.
- **Compare** (`inspector/EngineComparison.tsx`) — a per-engine roster (run/metrics on-demand)
  plus a two-pane A/B transcription diff.

### Admin

`features/admin/AdminPanel.tsx` — a left sidebar over four sections:

- **Overview** — KPI cards + status/decision breakdown bars (from `GET /overview`).
- **Documents** — status filter chips (with counts) + search + pagination; row → workspace.
- **Corrections** — the cross-document edit log, grouped by document, with two lenses
  (a collapsible **accordion** and a **master–detail** split).
- **Configuration** — the doc-type manager and OCR-model manager inline in one place.

---

## 7. Data model

`backend/app/models.py` (SQLModel → SQLite):

| Table | Purpose |
| --- | --- |
| `Document` | An uploaded document + ingestion metadata (filename, doc_type, status, pages). |
| `PipelineRun` | One run per document; `stage_results` (JSON) accumulates prescan/ocr/structure/decide. |
| `DocTypeDefinitionRow` | Persisted doc-type definition (built-ins mirrored; custom rebuilt from JSON). |
| `VlmEngineRow` | A connected VLM OCR engine (`key`, `label`, OpenRouter `model`, `enabled`). |
| `FieldCorrectionRow` | One row per (document, field) reviewer edit: `original_value` → `new_value`, timestamps. |

On-disk per document: `backend/data/<doc_id>/` holds `original.<ext>`, `pages/`, `thumbs/`,
`prescan/`, `ocr/` (per-engine Markdown), and `structure/` artifacts. For spreadsheets it
instead holds `sheets.json` (the parsed grid, one entry per sheet) and no page images.

---

## 8. Testing

- **Backend** — `pytest`, fully offline (mock OCR engine + mock structuring/decision
  providers, no API key). `make test`; `make smoke` runs an offline end-to-end pass.
- **Frontend** — Node ≥ 22. `vitest` covers **pure logic only** (reducers, payload building,
  `pascalCase`↔backend `_pascal` parity — the test env is node, no jsdom). UI correctness is
  enforced via `pnpm build` (strict `tsc`) + `pnpm lint`.


---

📚 **Docs:** [Index](./README.md) · **Architecture** · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)
