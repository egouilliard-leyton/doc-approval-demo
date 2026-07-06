# Roadmap & work log

Where the project has been, what it does today, and what's next. For *how* it works see
[ARCHITECTURE.md](./ARCHITECTURE.md); for the REST surface see [API.md](./API.md).

---

## Shipped

### Foundations — the approval pipeline
The core POC: ingest a document, then run four persisted, re-runnable stages —
**pre-scan → OCR → structure → decide**. Deterministic business rules run in code; the LLM
explains but can never override a hard fail; low confidence caps at `needs_review`. Local
SQLite + filesystem, no cloud.

### Configurable document types (Phases 1–5 + AI wizard)
Doc types became **data, not code**:
- Declarative field definitions + a generic extraction interpreter (`build_spec`).
- A declarative rule format over a fixed primitive vocabulary + generic interpreter.
- DB persistence of custom types (`DocTypeDefinitionRow`) + a CRUD/preview API.
- A frontend builder UI + dynamic doc-type picker.
- Offline test coverage (vitest, backend smoke, browser E2E).
- **Create-with-AI wizard** — a stateless agent designs a type conversationally (ingesting
  process/example docs, refining a Markdown spec, Plannotator annotation) and emits a
  validated definition.

### Configurable validation model
The rule layer grew from 6 primitives to a broad **single-document validation surface** — 23
declarative kinds, each wired end-to-end (interpreter + serialization + save-time 422
validation + builder UI + AI-wizard authoring + tests), all as *data, not code*:
- **Equality & comparison** — `equality` (exact/normalized/regex/**fuzzy** with a threshold
  slider), `numeric_range`, `percentage_tolerance`.
- **Arithmetic & aggregation** — `aggregate` (*total == Σ line_items*), and an
  **`expression`** kind: a **sandboxed formula DSL** (default-deny AST interpreter, no `eval`;
  helpers like `sum_of`/`days_between`/`matches`).
- **Dates** — `date_constraint` (not-future / min-max / field ordering).
- **Presence & cardinality** — `conditional_presence`, `mutual_exclusivity`, `at_least_n_of`,
  `required_together`.
- **Format/checksum** — `format` (IBAN, Luhn, email, UUID, ISO country/currency, …).
- **Text & provenance** — `contains`, `length_bounds`, `field_confidence_floor`,
  `grounded_on_page`, and `signature_presence` (over the signature post-pass).

Cross-document validations (same value/date across a set, bundle completeness, signature
*matching*) still aren't **configurable rule primitives** — though the bundle substrate they'd
build on now ships (see **Multi-document cases** below), so what's deferred is exposing them as
authorable kinds (see the backlog and
[validation-rules.md §6](./validation-rules.md#6-cross-document-validations-not-yet-built)).
Full catalogue: **[validation-rules.md](./validation-rules.md)**.

### Multi-VLM OCR (data-driven engine registry)
OCR VLMs became data-driven, the same way doc types are:
- Generic `VLMEngine(name, model)`; the registry resolves static engines (`docling`/`mock`)
  or an enabled `VlmEngineRow` from the DB. `qwen-vl` is seeded on boot.
- `/engines` CRUD API + a **settings dialog** to connect/enable/disable models. The
  add-model dropdown is populated **live** from OpenRouter's image-capable model list (with
  a curated fallback), or accepts any pasted slug.
- Connecting a new model is a row, not a code change.

### Spreadsheet (CSV/XLSX) extraction
Spreadsheets became a first-class input on a **native, non-image path**:
- Ingest parses the workbook (openpyxl / `csv`) into `sheets.json`, **one page per sheet**;
  no rasterization, and pre-scan is skipped.
- A built-in **`spreadsheet` engine** (not OCR/VLM) emits one block per non-empty cell whose
  bbox encodes the **grid coordinate** `(col, row)`, plus the sheet as table markdown — so
  structuring, grounding, rules and the decision stage are all unchanged (an invoice extracts
  straight from an `.xlsx`, no new doc type).
- The inspector renders an **interactive grid** (`GridViewer`) with per-sheet tabs; each
  grounded field highlights its **source cell** and shows an **A1 reference** (`Invoice!B2`).
- A **mock-extraction hint** shows when structuring used the offline `mock` provider (its
  placeholder fields don't match the sheet).

### Interactive inspector
- **Table-aware structuring** — table markdown is fed to the extractor (Docling keeps tables
  out of `full_text`), so invoice numbers, dates and totals extract correctly; grounding
  still maps each field to its page.
- **Color-coded, click-to-locate highlighting** — every grounded field is boxed on the page
  in a stable color; the same color keys its entry in the panel; clicking a field jumps to
  its page and flashes its box. Tables render as tables.
- **Engine Compare** — per-engine roster with on-demand runs + a two-pane A/B transcription
  diff.

### Large-document extraction accuracy
Extracting the right fields from the right places in **long, multi-page** documents, instead of
flattening every page into one blind window:
- **Proximity-aware grounding** — a repeated token (`Total`, a date) re-anchors to the occurrence
  nearest the extractor's offset hint instead of the first `str.find`, fixing wrong-page citations.
- **Section-aware extraction** — the document is partitioned into sections along the headings the
  OCR engine already emits (Docling `section_header`/`title` labels, or `#` markdown headings),
  extracted per section against its own grounded substrate, then merged. No new dependency
  (PageIndex/embeddings were evaluated and rejected — Docling already emits the structure).
- **Cross-section list dedup** (opt-in per field) — collapses the same entity extracted from two
  sections (e.g. `parties` from the intro + signature block); `line_items` stays un-deduped.
- **Whole-document grounding fallback** — a field whose span spilled across a section boundary is
  re-grounded against the full document; section-local grounding still wins.
- Small / mock / spreadsheet / header-less docs are byte-for-byte unchanged. Full design:
  **[large-document-extraction.md](./large-document-extraction.md)**.

### Signature detection
Located + cropped handwritten-signature extraction, layered onto the text-grounded pipeline:
- A doc type declares a `kind="signature"` field (contracts do); structuring runs a **best-effort
  YOLOv8-ONNX spatial post-pass** over the page PNGs (`_detect_signatures`), independent of the OCR
  engine. Each detection becomes a `FieldValue` carrying a pixel `bbox` + a saved crop URL.
- Additive/optional throughout — `Grounding.bbox`/`FieldValue.image_url` default to `None`, the
  frontend gained a bbox highlight fast-path + crop thumbnail, and the whole thing is a **graceful
  no-op** without the optional deps or model weights (structuring still succeeds).
- **Calibrated on a real-document eval** (confidence floor 0.45, in the measured gap between true
  signatures and noise); tuned for typed/printed documents. Fully-handwritten / degraded historical
  scans are a documented model ceiling. Full design + accuracy:
  **[signature-extraction.md](./signature-extraction.md)**.

### Outbound digital signing (PAdES)
The opposite direction from signature *detection*: **produce** a real cryptographic seal on a
document we're about to send, not find ink on one we received.
- Seals a PDF with a real **PAdES-B-B** (optional **-B-T** via a TSA) signature whose embedded
  CMS validates against a trust chain — applied to an **approved inbound document**
  (`/documents/{id}/sign`) *or* a **generated template output**
  (`/templates/{id}/outputs/{output_id}/sign`), the *Solicitud de Transmisión* you transmit.
- A **visible** stamp (default) drawn **at the template's signature marker** (`<img
  data-signature>`) — or a configurable corner when there's none — over the always-present
  cryptographic signature.
- Server-held **demo seal** (self-signed CA + leaf, `pyhanko`); a `mock` provider covers the
  offline suite. Re-deciding invalidates a prior seal. Full design + custody/security notes:
  **[digital-signing.md](./digital-signing.md)**.

### Human-in-the-loop corrections
- **Inline field editing** (`PATCH /documents/{id}/structure/field`) — correct any extracted
  value; the model's original is pinned and the edit is logged (`FieldCorrectionRow`).
- **Status + review** — a green/amber status dot per field (as-extracted vs edited) and a
  **Corrections** dialog (original → final + the field's source box on the document).
- **Optional currency** — money-like numeric fields render with the document's currency when
  one was extracted; other extractions are untouched.

### Admin panel
A consolidated **Admin** area (header Home/Admin toggle + left sidebar):
- **Overview** — KPI cards + status/decision breakdowns (`GET /overview`).
- **Documents** — status filter chips (with counts) + search + pagination; open → workspace.
- **Corrections** — cross-document edit log grouped by document, with **accordion** and
  **master–detail** lenses.
- **Configuration** — doc-type + OCR-model managers inline in one place.

### Multi-document cases
Uploading became **multi-document**: drop several files on Home and they form a **case**, the
cross-checked counterpart to the single-document pipeline.
- **Unified upload** — Home is one entry: one dropped document runs the single-document
  workspace; several become a case. The header toggle is now **Home / Admin** (the old
  separate Workspace and Cases tabs are gone).
- **The `Case` entity** groups N documents; each is **auto-classified (confirm before commit)**,
  extracted with the existing per-document pipeline, then **reconciled** into shared canonical
  fields — agreements yield a cited value, disagreements route the case to `needs_review`.
- **One case decision** lifts the deterministic-checks-hard-fail + advisory-LLM hybrid to the
  case level, with completeness checks for defined **case types** (e.g. `ap_match`).
- New backend surface (`/cases`, `/case-types`, case reconcile/decide, a `/classify` stage) +
  a case-level frontend (`src/features/case/`). Full design:
  **[multi-document-cases.md](./multi-document-cases.md)**.

### Shareable deep links
Every navigable place got a **real, shareable hash URL** that updates the address bar and
restores on cold load (browser back/forward included).
- A **hand-rolled hash router** — no `react-router`. The core is a pure, unit-tested mapping
  between the location hash and a typed `Route` (`src/lib/route.ts` + `route.test.ts`); the
  React seam and a **Copy link** button (on the document, case, and admin headers) live in
  `src/features/routing/`.
- Grammar covers home, a document (`?tab=…&field=…`), the cases list + one case (`?member=…`),
  and the admin sections (incl. `config/doctype/<name>` and `eval?run=<id>`).

### Accuracy / benchmark evaluation harness
"Is the extraction actually right?" became measurable, not a vibe:
- A **golden-set scorer** (`app.evaluation`) grades a structuring result against known-good
  expected outputs (`backend/golden/*.json`) — **per scalar field** (exact *and* normalized match)
  and, the headline metric for invoices, **line-item / table-row accuracy** (matched vs expected
  vs extracted rows).
- Any OCR **engine** can be run over the same goldens (`run_and_score`), or an existing document's
  persisted structure re-scored in place (`score_existing`); every scored run is persisted as an
  `EvalRunRow` so engines can be compared and regressions tracked.
- New **Admin → Accuracy** section (deep-linkable, `#/admin/eval?run=<id>`) with per-engine
  **Run** buttons and an **expected-vs-actual** drill-in that opens the source document.
- API: `GET /eval/goldens`, `GET /eval/goldens/{id}`, `POST /eval/run`, `GET /eval/runs`,
  `GET /eval/runs/{id}`.

### Active-learning loop (corrections → labels → few-shot)
The corrections log became training signal, two ways:
- **JSONL label export** (`GET /corrections/export?shape=raw|examples[&doc_type=][&include_text=]`)
  streams the log as ground-truth labels — `raw` = one line per correction, `examples` = one
  reviewer-approved record per document (optionally with the OCR text it was read from). Export
  controls live in the Corrections admin section.
- **Few-shot self-improvement** — a doc type's past *scalar-field* corrections are turned into
  `label: value` examples (`build_correction_examples`, deduped newest-first, capped at
  `few_shot_max_examples`) and injected into that type's extraction prompt, so it stops repeating
  the same mistakes. Bounded and per-doctype; a **no-op** for the `mock` provider, with no
  corrections, or when `few_shot_corrections_enabled=false` (the spec stays byte-identical).

### Per-field review queue
Surfaces the individual **low-confidence fields** worth a human's attention, not just whole docs:
- `GET /review-queue[?threshold=][&doc_type=]` scans each document's latest structuring result,
  flattens it to leaf fields, and returns those with `confidence < threshold` (default
  `field_review_confidence_threshold`) that a reviewer **hasn't already edited** and that aren't
  **presence-kind** fields — grouped by document, worst-first.
- New **Admin → Review queue** section; clicking a field deep-links straight to it in the
  inspector (`#/documents/{id}?field=…`) to correct in place — which then feeds the few-shot loop.

### Black-box extraction API
One call in, structured data out — for automated pipelines with zero UI interaction:
- `POST /extract` runs the **whole** single-document pipeline (upload → prescan → OCR →
  [classify] → structure → decide) synchronously and returns the structured fields, the decision,
  and a `document_id`. `POST /extract/batch` runs N files sequentially with **per-file failure
  isolation** (always HTTP 200).
- `doc_type` may be omitted to **auto-classify**; `ocr_engine` omitted to use doc-type routing.
- It **reuses** the exact stage functions + persistence as the staged routes (no stage
  re-implemented), so every `/extract` run lands a normal, **inspectable** document in the UI.
  Exercisable from FastAPI's Swagger UI at `/docs`.

### Per-doctype OCR routing + external adapter
OCR-engine selection became a per-doc-type policy, and the engine set became genuinely pluggable:
- **Routing + fallback chain** — a doc type can declare a `preferred_ocr_engine` +
  ordered `ocr_fallback_engines`; `resolve_engine_chain` builds the chain and `run_ocr_chain`
  advances on error / empty output / sub-threshold confidence, recording the engine that actually
  ran. Set it (built-ins included) via `PATCH /doc-types/{name}/routing`.
- The upload picker gains an **"Auto — use doc-type routing"** option that leaves the engine
  unset so routing decides.
- **External-service adapter** — a built-in **`digibot`** engine wraps any external document-AI
  service (Rossum/proprietary) behind the same `OCREngine` interface (POST page image → map JSON
  back), configured via `DIGIBOT_ENDPOINT`/`DIGIBOT_API_KEY` and a **graceful no-op** (hidden from
  the picker, clean 400) when unset.

### KPI dashboard
The Admin → Overview dashboard grew from raw counts into **four program KPIs**, all reading from
data the other features already produce (additive fields on `GET /overview`):
- **Precision** — accuracy from the eval harness (overall + line-item).
- **Coverage** — documents per doc type.
- **Throughput** — documents/day, a 30-day sparkline.
- **Maintenance** — corrections/day.
- Plus a **per-doc-type table** (documents, avg confidence, decisions, corrections, latest
  accuracy). All existing overview cards are untouched.

### Document generation from templates (2026-07)
An extracted document became a **filled, downloadable DOCX/PDF**. A **Template** (bound to a
doc type) is built from an uploaded source whose **mode is auto-detected**, shipped across 6
phases (Phase 0 scaffolding → Phase 5 polish):
- **Form-fill** — a fillable **PDF (AcroForm)**: fields enumerated (**pypdf**), an AI/heuristic
  mapper suggests bindings to extracted field paths, *Generate* fills + optionally **stamps a
  signature image** (**reportlab**) → filled PDF.
- **Rich-HTML** — a **DOCX / non-fillable PDF** converted to editable HTML (**mammoth** /
  Docling, PyMuPDF fallback), authored in a **TipTap** editor with `<span data-field>`
  placeholders, rendered to **PDF** (**WeasyPrint**) and/or **DOCX** (**html4docx**) via a
  **Jinja-free** data-attribute binder.
- **AI edit** — a streaming **SSE** authoring agent (`POST /templates/{id}/agent`), tool-using
  (`set_html`/`set_css`/`insert_placeholder`/…), edits the HTML/CSS live from natural language;
  every edit is a revision.
- **Fidelity (vision QA)** — `POST /templates/{id}/qa` renders to page images (**pypdfium2**)
  and a vision model checks the render against the uploaded example (or self-reviews),
  returning a severity-coded checklist; **auto-runs on source upload**.
- **History + restore** — every edit snapshots a `TemplateRevision`; restore is itself
  undoable. Plus a **placeholder ↔ doc-type lint** and a **live styled Preview toggle**.
- All generation libs are **permissive** (new rasterization is **pypdfium2**, *not* the AGPL
  PyMuPDF); WeasyPrint needs system Pango/GDK-PixBuf (DOCX works without them, PDF degrades
  gracefully). **122 backend tests, fully offline** (real WeasyPrint/pypdfium2, mock LLM/vision).
- **Known limitation (documented honestly):** TipTap+StarterKit flattens complex HTML on load,
  so plain rich-text editing + Save is **lossy** for styled layouts — the faithful paths are the
  **Preview** toggle and the **AI edit** agent (raw HTML). A raw HTML/CSS code view is the
  recommended next step. Full design: **[document-generation.md](./document-generation.md)**.

### Robustness fixes
- **Self-healing additive-column migration at startup** (`_sync_additive_columns`) — a generic,
  idempotent pass that `ALTER TABLE ADD COLUMN`s any SQLModel column missing from the live SQLite
  table, so an existing dev DB no longer breaks after a schema-adding release. Additive only
  (never drops/renames), each ALTER isolated so one hiccup never crashes boot.
- **OCR routing settable on built-in doc types** — `PATCH /doc-types/{name}/routing` touches only
  the routing columns (orthogonal to the read-only definition), so `invoice`/`contract`/`po`/
  `delivery_note` can be routed too without a code change.

---

## Backlog / ideas

Not built yet — candidate next steps, roughly ordered by value.

- **Per-cell bounding boxes (image tables)** — spreadsheets already ground to individual
  cells; for **image/PDF** docs, highlights are still per-table (Docling exposes only a
  table-level bbox). Cell-level grounding there would let each table field box its own cell.
- **Corrections that survive re-runs** — today re-running Structure clears `edited` flags
  (the log persists). Optionally re-apply prior corrections, or diff old vs new extraction.
- **Overview depth** — the KPI dashboard now ships the trend charts (30-day throughput /
  maintenance sparklines) and per-doc-type correction counts; still open: decision/confidence
  columns in the Documents table and date-range filters.
- **Batch actions** — multi-select in the Documents table (re-run a stage, re-decide, delete).
- **Auth & multi-user** — the app is single-user/local today (Plannotator is loopback-only).
  A deployed version needs auth, per-user data, and a native in-app annotation layer.
- **Cross-document validation _primitives_** — the **bundle** substrate now exists (Cases ship,
  and the case decision engine already runs cross-document conflict + completeness checks in
  code). Still open: exposing cross-document checks — same value/date across a set, bundle
  completeness, cross-references, same-signatory *matching* — as **configurable rule primitives**
  authorable like the single-document kinds. Design in
  [validation-rules.md §6](./validation-rules.md#6-cross-document-validations-not-yet-built)
  and [VALIDATION-BRAINSTORM.md §3](./VALIDATION-BRAINSTORM.md).
- **Export** — download a decision + citations as a PDF/JSON audit record.
- **Confidence calibration** — use the corrections log to measure and tune per-field
  confidence.
- **Signing depth** — **PAdES-B-LT / B-LTA** (embedded revocation + archive timestamps for
  long-term validation), **remote per-signer signing** (pyHanko `ExternalSigner`, each signer
  holds their own key), a **Stirling-PDF** external provider, and an inbound
  `digital_signature_valid` rule primitive. See
  [digital-signing.md § For the next agent](./digital-signing.md#for-the-next-agent).

---

## Non-goals (for the POC)

- Cloud storage / managed DB — intentionally local (SQLite + filesystem) for a zero-setup demo.
- Overriding deterministic rules with the LLM — rules stay authoritative and auditable by design.
- A heavy frontend test harness — UI is validated by `tsc` + lint; only pure logic is unit-tested.


---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · **Roadmap** · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · [Digital signing](./digital-signing.md) · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)
