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
│  routes/ ── documents · pipeline · extract · doc_types · doctype_assist ·       │
│             engines · cases · case_types · corrections · overview ·             │
│             review_queue · evaluation                                           │
│  pipeline/ ── prescan → ocr/ → structuring → agent (decide)                     │
│  extraction/ (declarative → spec)   rules/ (primitives → ruleset)               │
│  doc_types.py (registry)   models.py (SQLModel)   storage.py (files)            │
└───────────────┬───────────────────────────────────┬────────────────────────────┘
                │ SQLite (backend/data/app.db)        │ OpenRouter (OpenAI-compatible)
                │ + files (backend/data/<doc_id>/)    │ VLM OCR · LangExtract · decision · wizard
```

- **Backend** — FastAPI, Python 3.12, `uv`. Owns the pipeline and the REST API.
- **Frontend** — Vite + React 19 + TypeScript at the repo root; Tailwind v4 + shadcn/ui.
  A **hand-rolled hash router** (`src/lib/route.ts`, no `react-router`) makes every place a
  shareable URL; the shell renders from the parsed route (see [§10](#10-frontend)).
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
curated fallback when the key/network is absent. See the settings UI in [§10](#10-frontend).

> Per-engine OCR results coexist under `stage_results["ocr"][<engine>]`, so the inspector's
> **Compare** tab can diff engines on the same document.

### 3a. Per-doc-type routing & fallback

OCR runs a **chain**, not a single engine. Three staged helpers preserve the existing
request-thread / worker-thread split so the DB session never crosses into a worker thread:

- `resolve_engine_chain(doc_type, session)` — **request thread**, reads the DB: a doc type's
  `preferred_ocr_engine` drives the chain (preferred first, then its `ocr_fallback_engines`,
  deduped); with no preferred engine it uses the global `ocr_default_engine` +
  `ocr_default_fallback_engines`. Names are **not** validated here.
- `build_engine_objects(names, session)` — **request thread**, reads the DB: resolves each
  name to a live engine, **logging and skipping** unknown/disabled/stale names so one bad
  entry can't crash the chain.
- `run_ocr_chain(doc, engine_objs)` — **session-free**, the only piece that enters the worker
  thread. It advances to the next engine when the current one (a) raises, (b) returns empty
  text, or (c) scores below `ocr_fallback_confidence_threshold` — **except the last** engine,
  whose output is always accepted so the chain terminates. It stamps
  `OCRResult.attempted_engines` (the trail tried) and appends a warning when a fallback fired;
  it raises only if *every* engine raised.

An explicit `?engine=` (or a spreadsheet doc) bypasses routing to a one-engine chain; both the
staged `POST /ocr` route and the black-box `/extract` path use these same three helpers.
`PATCH /doc-types/{name}/routing` edits the routing columns for built-in **and** custom types
(routing is orthogonal to the read-only definition). This engine-level fallback is **distinct**
from the structuring `fallback_used` flag ([§4](#4-structuring)'s Docling table backfill): one
answers "which OCR engine produced the text", the other "were empty fields backfilled from
tables".

### 3b. External-service adapter

`DigibotEngine` (`digibot.py`) is a fourth engine kind (`kind="external"`): it POSTs each page
image to a third-party OCR HTTP service (Rossum / Digibot-style) and maps the JSON response
into the normalized `OCRResult`. It is **env-configured** — `DIGIBOT_ENDPOINT` (+ optional
`DIGIBOT_API_KEY`, `DIGIBOT_TIMEOUT_S`). Unset, `run()` raises the same `ValueError` a keyless
VLM does (→ HTTP 400), it is only offered in the picker when the endpoint is set, and `warm()`
is a no-op so startup never fires a networked/paid call (`httpx` is imported lazily). The
request/response shape is a placeholder adapted per concrete service.

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
- **Few-shot corrections injection (active learning)** — when `run_structuring` is passed a
  doc type's past `FieldCorrection`s, `build_correction_examples` (`extraction/definition.py`)
  turns them into tiny `label: value` few-shot examples (scalar fields only, deduped by path
  keeping the newest, capped at `few_shot_max_examples`) and folds them onto a **fresh** spec
  via `dataclasses.replace` (`_augment_examples_factory`) so the extractor sees the
  reviewer-approved value verbatim next time. It's a strict **no-op** for the `mock` provider,
  an empty correction list, or `few_shot_corrections_enabled=False` — the spec stays
  byte-identical. The `/extract` path loads this doc type's corrections and passes them in.

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
  `DocTypeCreate` through the same validators as a hand-built type. Its system prompt does
  **not** hand-list the schema — the field/rule/DSL catalogue is generated at import time
  from the very dataclasses the validator uses (`pipeline/doctype_schema_reference.py`
  reads `serialization._KIND_MAP`, `extraction.definition.FieldDef`, and the expression
  helpers), so every extraction kind (incl. `signature`) and all 23 rule primitives are
  authorable and the prompt can never drift from `validate_custom_*`. Opening the wizard
  seeds a fixed markdown template + first questions locally (no LLM call); the agent runs
  only from the first **Send** onward.

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

## 6. Multi-document cases

A **`Case`** is an entity **above `Document`** that groups N documents (possibly of mixed
types) and owns the cross-document reasoning result. The per-document pipeline (§2) is reused
**unchanged** — each member is ingested, OCR'd, structured and (optionally) decided on its own;
the case layer only adds a **reconcile → decide** pass on top of the members' existing
`StructuredResult`s. Design & phase plan: **[multi-document-cases.md](./multi-document-cases.md)**.

```
Case ──┬── Document (invoice)  → StructuredResult ─┐
       ├── Document (po)        → StructuredResult ─┤ reconcile → canonical fields
       ├── Document (contract)  → StructuredResult ─┤ (+ conflicts) → one case decision
       └── Document (delivery)  → StructuredResult ─┘
```

- **Classify** (`pipeline/classify.py`, `POST /documents/{id}/classify`) — an advisory stage
  that guesses a file's doc-type from its persisted OCR text. Two providers behind one entry
  point (mirroring OCR/structuring/decision): **`heuristic`** (default, fully offline — scores
  each registered type by how much of its extraction vocabulary appears in the text) and an
  opt-in **`llm`**. The guess is deliberately **not persisted** and doesn't advance status —
  the user confirms/corrects it ("auto-classify + confirm") before extraction commits.
- **Reconciler** (`reconcile/`) — turns the members into **canonical fields**, each a *bag of
  grounded candidates* drawn from N documents (`candidates.py`: a defined case type follows its
  `canonical_fields` mapping; an open pile infers fields from top-level names overlapping ≥2
  docs). Candidates are compared under a **per-kind tolerance** (`tolerance.py`: money / date /
  legal-suffix-aware company names) via a **grouped-by-document exists-match** (`engine.py`), so
  `$135.00` == `135.0` and `Acme Ltd` == `Acme Limited`. Agreement yields one cited value;
  disagreement never picks a winner — it records a `conflict_detail` and routes the case to
  `needs_review`. Each candidate cites *which* document + page it came from (the `document_id`
  added to `Grounding`/`Citation`).
- **Case decision** (`case_decision.py`, `POST /cases/{id}/decide`) — lifts the single-doc
  hybrid to the case: deterministic cross-document checks run in code (a field conflict or a
  missing required document → `needs_review`; defined case types add **completeness** checks),
  and an opt-in LLM (`?provider=llm`) adds judgment it can never use to override a failed check.
  It **reuses `agent._reconcile` verbatim**, so the precedence rules match §5 exactly. The
  default path is fully offline.
- **Case-type registry** (`case_types.py` + `case_type_definition.py`) — a data-driven registry
  parallel to the doc-type one. A case type carries its expected member doc-types (with min/max
  cardinality) + the canonical-field mapping. Built-in **`ap_match`** (invoice + po + contract +
  delivery_note) seeds on boot; custom types are JSON rows (`CaseTypeDefinitionRow`) rebuilt
  verbatim — unlike doc types they carry no code, so there's no code-vs-DB split. Two new
  built-in doc-types (`po`, `delivery_note`) back the `ap_match` demo.
- **Orchestration** keeps the no-background-worker design: the client creates a case, fans out
  the existing per-document stage calls (they parallelize cleanly), then calls the server-side
  `POST /cases/{id}/reconcile` + `POST /cases/{id}/decide`. Both stages persist onto a
  **`CaseRun`** (`stage_results` keyed by `case_id`, mirroring `PipelineRun`).

---

## 7. Black-box extraction

`routes/extract.py` is a **one-call** entry over the same pipeline: `POST /extract` runs
upload → prescan → ocr → [classify] → structure → decide synchronously and returns the final
`ExtractionResult`. It does **not** re-implement any stage, nor call one route handler from
another — it imports the shared persistence helpers from `routes/pipeline.py`
(`get_or_create_run`, `_save_stage`, `_run_stage`, `_prior_invoice_numbers`) and the staged
pipeline functions, so every stage is persisted onto **one `PipelineRun`** and the
`stage_results` dict is built up exactly as driving the `/documents/{id}/…` routes by hand
would (the same seam the eval runner uses).

- **Auto-classify.** An empty `doc_type` runs the classify stage; a resolved type that isn't
  registered → 422.
- **Routing.** An explicit `ocr_engine` (or a spreadsheet) pins a one-engine chain, else the
  doc type's routing chain resolves ([§3a](#3a-per-doc-type-routing--fallback)).
- **Few-shot.** The doc type's past corrections are loaded and passed into structuring
  ([§4](#4-structuring)).
- **Batch (`POST /extract/batch`) is sequential by design** — the `_prior_invoice_numbers`
  duplicate-invoice scan reads other documents' committed decide results, so concurrent runs
  would race. It always returns HTTP 200; one bad file is isolated into its `BatchExtractionItem`
  (`error` + `error_status`) without sinking the batch.

---

## 8. Accuracy evaluation harness

`backend/app/evaluation/` measures extraction accuracy against **golden fixtures** —
`golden/<id>.json` files (`GoldenCase`: `sample_file`, `doc_type`, `expected_fields`,
`expected_collections`), provider-agnostic plain data. The `mock-baseline` golden pins the
deterministic offline mock output so the harness scores meaningfully with no network.

- **Scorer** (`scorer.py`, pure — no DB/HTTP/pipeline imports) works on the plain
  `StructuredResult.fields` JSON. Scalar/dotted fields are compared for `exact_match` (literal
  equality after minimal coercion) and `normalized_match` (exact **or** agreement under the
  field's kind) — **reusing the reconciler's** `infer_kind` / `values_agree` money/date/string
  tolerance and `rules.base.as_number`, so a field "agrees" here exactly as the cross-document
  reconciler would. Collection fields (`line_items`, `parties`, …) go through a **greedy
  highest-first row alignment** into per-collection `row_precision`/`row_recall`/`row_f1`,
  `cell_accuracy` over matched pairs, and `line_item_score = row_f1 × cell_accuracy`.
  `overall_score` pools every scalar `normalized_match` with every matched/missed collection
  cell.
- **Runner** (`runner.py`) bridges a golden to the real pipeline: it uploads the sample once as
  a persisted `[eval]`-prefixed Document (reused across runs), runs OCR + structuring via the
  same `_save_stage` / `get_or_create_run` helpers the staged routes use (so stage results land
  identically), scores the output, and persists an `EvalRunRow`. It scores **any** engine
  (offline `mock` by default; the frontend passes real engines/providers), and `score_existing`
  re-scores a document's already-persisted structure stage instead of re-running the pipeline.

---

## 9. Per-field review queue

`routes/review_queue.py` (`GET /review-queue`) surfaces the individual low-confidence fields a
reviewer should check, rather than whole documents.

- **`flatten_field_values`** (`pipeline/structuring.py`) flattens a structure into
  dotted-path → raw `FieldValue` dict. It's the public counterpart of the grounding-only
  `_flatten_grounding`, sharing the same `_walk_leaves` recursion and **the exact dotted-path
  grammar the `PATCH /structure/field` endpoint accepts** (`.{i}` into a list, `.{key}` into a
  dict).
- **At-risk rule.** A field is at risk iff `confidence < threshold` (default
  `field_review_confidence_threshold`), it hasn't been `edited`, and it isn't a presence-kind
  field (a boolean "is X present?" whose 0.0 confidence a reviewer can't fix).
- **Latest-run scan.** It picks each document's latest `PipelineRun` (the same pattern the
  overview aggregation uses), emits worst-first fields per document, and omits documents with no
  at-risk fields. The UI deep-links straight to a flagged field (path + grounding drive the
  jump-to-box).

---

## 10. Frontend

Vite + React 19. A **hand-rolled hash router** owns navigation: `src/lib/route.ts` is a pure,
unit-tested mapping between the location hash and a typed `Route` (parse / format / equality),
and `src/features/routing/` is the React seam (`useHashRoute` mirrors `window.location.hash`,
`RouteContext` shares it, `CopyLinkButton` copies the current deep link). `App.tsx`'s `Shell`
renders the pane from `route.view` and shows a header **Home / Admin** toggle; finer navigation
(which document, tab, field, case, or admin section) lives in the `Route` itself, so every place
is a shareable URL that restores on cold load. **Home is one unified upload entry** — one dropped
document runs the single-document workspace; several become a multi-document case.

### Pipeline state

`features/pipeline/usePipeline.ts` is a `useReducer` state machine shared via
`PipelineContext`. It owns the open document, per-engine OCR results, structure, decision,
the active engine, and the sequential auto-run. `useEngines` (`features/upload/`) fetches the
selectable engines and refetches on window focus.

### Workspace

- **Upload view** (`features/upload/`) — dropzone, doc-type + engine pickers (both collapse
  from pills to a searchable **Combobox** past a threshold), and the document library. The
  engine picker leads with an **"Auto"** option (`EngineSelect.tsx`) that omits the `engine`
  param so the doc type's routing chain ([§3a](#3a-per-doc-type-routing--fallback)) resolves.
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

### Cases

`features/case/` mirrors the single-document workspace for a multi-document case (§6).
`caseReducer.ts` is a pure state machine (shared via `CaseContext`) owning per-member
pipeline progress, the reconciliation + decision results, and the drill-down focus. The
views walk the flow: `ClassifyConfirmView` (auto-classify + confirm each file's type),
`CaseOverview` (members + per-member status), `ReconciliationView` (canonical fields with
multi-doc citations + conflict badges; clicking a field navigates across members),
`CaseDecisionPanel`, and `CaseMemberDrilldown` (open one member's inspector in place).
`CaseList` is the cases index; a shared `#/cases/<id>` link cold-loads a **read-only**
overview of the saved reconciliation/decision.

### Admin

`features/admin/AdminPanel.tsx` — a left sidebar over six deep-linkable sections:

- **Overview** (`OverviewSection.tsx`) — the **KPI dashboard** over `GET /overview`: accuracy
  (from eval runs), coverage (`doc_types_used` + status/decision breakdown bars), and 30-day
  throughput / maintenance **sparklines** (hand-rolled inline **SVG** `<polyline>`, no chart
  lib), plus the per-doc-type KPI table (`by_doc_type`).
- **Documents** — status filter chips (with counts) + search + pagination; row → workspace.
- **Corrections** — the cross-document edit log, grouped by document, with two lenses
  (a collapsible **accordion** and a **master–detail** split).
- **Review queue** (`ReviewQueueSection.tsx`) — the at-risk-field queue ([§9](#9-per-field-review-queue))
  from `GET /review-queue`; a flagged field deep-links into its document's inspector.
- **Configuration** — the doc-type manager (incl. the builder's **OCR-routing editor**:
  preferred engine + ordered fallbacks, saved via `PATCH /doc-types/{name}/routing`) and the
  OCR-model manager inline in one place.
- **Evaluation** (`EvalSection.tsx`) — the golden catalogue + persisted eval runs
  ([§8](#8-accuracy-evaluation-harness)) from the `/eval` routes.

---

## 11. Data model

`backend/app/models.py` (SQLModel → SQLite):

| Table | Purpose |
| --- | --- |
| `Document` | An uploaded document + ingestion metadata (filename, doc_type, status, pages). |
| `PipelineRun` | One run per document; `stage_results` (JSON) accumulates prescan/ocr/structure/decide. |
| `Case` | A case grouping N documents for cross-document reasoning; open pile or bound to a case type. |
| `CaseMembership` | Links a document to a case (`document_id` PK → a document belongs to at most one case). |
| `CaseRun` | One run per case; `stage_results` (JSON) accumulates reconcile/decide (mirrors `PipelineRun`). |
| `CaseTypeDefinitionRow` | Persisted case-type definition (built-in `ap_match` mirrored; custom rebuilt from JSON). |
| `DocTypeDefinitionRow` | Persisted doc-type definition (built-ins mirrored; custom rebuilt from JSON). Also carries the **OCR-routing columns** `preferred_ocr_engine` + `ocr_fallback_engines` (permissive; edited via `PATCH /doc-types/{name}/routing`). |
| `VlmEngineRow` | A connected VLM OCR engine (`key`, `label`, OpenRouter `model`, `enabled`). |
| `Template` | A doc-type-bound generation template ([§13](#13-document-generation-from-templates)); `mode` (`form`/`rich`), the source artifact, and either the AcroForm mapping (form) or `html_body` + `css` (rich). |
| `TemplateRevision` | One snapshot per template edit (manual or AI); powers the revision history + restore. |
| `FieldCorrectionRow` | One row per (document, field) reviewer edit: `original_value` → `new_value`, timestamps. |
| `EvalRunRow` | One scored evaluation run: `golden_id`/`doc_type`/`engine`/`provider`/`document_id`, the three headline scores (`overall_score`, `field_accuracy_exact`/`_normalized`), and the full `field_scores` / `collection_scores` JSON breakdown. |

On-disk per document: `backend/data/<doc_id>/` holds `original.<ext>`, `pages/`, `thumbs/`,
`prescan/`, `ocr/` (per-engine Markdown), and `structure/` artifacts. For spreadsheets it
instead holds `sheets.json` (the parsed grid, one entry per sheet) and no page images.

**Startup additive-column migration.** `db.init_db()` runs `SQLModel.metadata.create_all`
(which only creates *missing tables*) and then `_sync_additive_columns()`: for each table it
`PRAGMA table_info`-diffs the live SQLite columns against the model and issues an isolated
`ALTER TABLE … ADD COLUMN` for any that are missing (coarse affinity, JSON columns seeded with
a valid empty-container `DEFAULT`). So a schema-*adding* release — e.g. the routing columns on
`DocTypeDefinitionRow` — never breaks an existing `app.db`. It is additive-only: it never
drops, renames, or alters existing columns, and each ALTER is isolated so one hiccup can't
crash startup.

---

## 12. Testing

- **Backend** — `pytest`, fully offline (mock OCR engine + mock structuring/decision
  providers, no API key). `make test`; `make smoke` runs an offline end-to-end pass.
- **Frontend** — Node ≥ 22. `vitest` covers **pure logic only** (reducers, payload building,
  `pascalCase`↔backend `_pascal` parity — the test env is node, no jsdom). UI correctness is
  enforced via `pnpm build` (strict `tsc`) + `pnpm lint`.

---

## 13. Document generation from templates

`backend/app/pipeline/generation/` turns an **extracted** document into a filled **DOCX/PDF**.
A **`Template`** is bound to a doc type; the **mode is auto-detected from the uploaded source**
and the generation layer stays as stateless/single-purpose as the rest of the pipeline. Full
design: **[document-generation.md](./document-generation.md)**.

- **Form-fill** (fillable PDF) — `forms`/`mapper`/`generate`: enumerate AcroForm fields
  (**pypdf**), an AI/heuristic mapper binds each to an extracted field path, `generate` fills
  the form + stamps a signature image (**reportlab**).
- **Rich-HTML** (DOCX / non-fillable PDF) — `convert`/`binder`/`render`: source → editable HTML
  (**mammoth** / Docling, PyMuPDF fallback), a **Jinja-free** `bind_html` substitutes each
  `<span data-field="path">` with the document's value, then render to **PDF** (**WeasyPrint**)
  and/or **DOCX** (**html4docx**). The same bound HTML feeds both exporters.
- **AI assists** — `authoring_agent`/`template_edits` (the SSE, tool-using HTML/CSS editor);
  `rasterize`/`preview`/`qa_vision`/`qa` (pypdfium2 rasterization + the styled preview + the
  vision Fidelity loop); `lint` (placeholder ↔ doc-type consistency). Every edit snapshots a
  `TemplateRevision` (history + undoable restore).
- **Persistence** — `Template` + `TemplateRevision` SQLModel tables ([§11](#11-data-model)),
  served by `routes/templates.py`; the frontend is `src/features/templates/` (+ `editor/`).
- **Licensing** — all generation libs are permissive; new rasterization is **pypdfium2** (not
  the AGPL PyMuPDF). WeasyPrint needs system Pango + GDK-PixBuf; without them DOCX still works
  and PDF degrades gracefully. Installed as the `docgen` extra.
- **Known limitation** — TipTap+StarterKit flattens complex HTML on load, so rich-text
  editing + Save is lossy for styled layouts; the faithful paths are the **Preview** toggle
  (renders the persisted `html_body`) and the **AI edit** agent (writes raw HTML).


---

📚 **Docs:** [Index](./README.md) · **Architecture** · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)
