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
validation + builder UI + tests), all as *data, not code*:
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
*matching*) are deferred — they need the multi-document/bundle substrate (see the backlog and
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

### Human-in-the-loop corrections
- **Inline field editing** (`PATCH /documents/{id}/structure/field`) — correct any extracted
  value; the model's original is pinned and the edit is logged (`FieldCorrectionRow`).
- **Status + review** — a green/amber status dot per field (as-extracted vs edited) and a
  **Corrections** dialog (original → final + the field's source box on the document).
- **Optional currency** — money-like numeric fields render with the document's currency when
  one was extracted; other extractions are untouched.

### Admin panel
A consolidated **Admin** area (header Workspace/Admin toggle + left sidebar):
- **Overview** — KPI cards + status/decision breakdowns (`GET /overview`).
- **Documents** — status filter chips (with counts) + search + pagination; open → workspace.
- **Corrections** — cross-document edit log grouped by document, with **accordion** and
  **master–detail** lenses.
- **Configuration** — doc-type + OCR-model managers inline in one place.

---

## Backlog / ideas

Not built yet — candidate next steps, roughly ordered by value.

- **Per-cell bounding boxes (image tables)** — spreadsheets already ground to individual
  cells; for **image/PDF** docs, highlights are still per-table (Docling exposes only a
  table-level bbox). Cell-level grounding there would let each table field box its own cell.
- **Corrections that survive re-runs** — today re-running Structure clears `edited` flags
  (the log persists). Optionally re-apply prior corrections, or diff old vs new extraction.
- **Overview depth** — decision/confidence columns in the Documents table; date-range
  filters; simple trend charts; correction-rate per doc type (an extraction-quality signal).
- **Batch actions** — multi-select in the Documents table (re-run a stage, re-decide, delete).
- **Auth & multi-user** — the app is single-user/local today (Plannotator is loopback-only).
  A deployed version needs auth, per-user data, and a native in-app annotation layer.
- **Cross-document validations** — same value/date across a set of documents, bundle
  completeness, cross-references, and same-signatory *matching*. Needs a **bundle** concept
  (multiple documents' extractions evaluated together) that the multi-document extraction &
  configuration work builds first. Design in
  [validation-rules.md §6](./validation-rules.md#6-cross-document-validations-not-yet-built)
  and [VALIDATION-BRAINSTORM.md §3](./VALIDATION-BRAINSTORM.md).
- **Export** — download a decision + citations as a PDF/JSON audit record.
- **Confidence calibration** — use the corrections log to measure and tune per-field
  confidence.

---

## Non-goals (for the POC)

- Cloud storage / managed DB — intentionally local (SQLite + filesystem) for a zero-setup demo.
- Overriding deterministic rules with the LLM — rules stay authoritative and auditable by design.
- A heavy frontend test harness — UI is validated by `tsc` + lint; only pure logic is unit-tested.
