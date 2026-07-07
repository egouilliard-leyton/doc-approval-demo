# Document Generation from Templates

Status: **COMPLETE — all phases SHIPPED.** Phase 0 scaffolding `f48444d` → Phase 5 polish
`228e502`; end-to-end smoke tests `e6f9a1b`; README `a44431a`; demo assets `b4bf906`; live
styled Preview toggle `5335468` + `5dd711a`; **Excel (.xlsx) mode `53b8118`**. Fully offline
for the core paths; the spreadsheet preview/PDF needs a system LibreOffice binary and degrades
gracefully without it. Built 2026-07.

Once a document has been **extracted**, this feature turns its fields into a filled,
downloadable **DOCX / PDF / Excel (.xlsx)**. You create a **Template** (tied to a doc type),
upload a source document that becomes the layout, bind its blanks to extracted field paths, and
*Generate* a filled artifact for any processed document of that type.

> For the pipeline that produces the extraction this fills from, see
> [ARCHITECTURE.md](./ARCHITECTURE.md). For the REST surface, see [API.md](./API.md). For a
> hands-on walkthrough, see [`demo/TESTING.md`](../demo/TESTING.md).

## Overview

A `Template` belongs to a doc type and carries everything needed to render a filled document.
The **mode is auto-detected from the source you upload**, so you never pick it by hand:

```
extracted Document ─┐
                    ├─▶ Template (doc-type-bound) ─▶ Generate ─▶ filled PDF / DOCX / XLSX
uploaded source ────┘        │
                    ┌────────┼──────────────────┐
              fillable PDF   DOCX / non-fillable   styled .xlsx
              → Form-fill     PDF → Rich-HTML       → Spreadsheet mode
```

All three modes share the same **field catalogue** (`GET /templates/{id}/catalogue`): the doc
type's extractable field paths (`vendor_name`, `total_amount`, `line_items.0.amount`, …),
which are what a binding points at. At generate time the values are pulled from the chosen
processed document's persisted `StructuredResult`. (Spreadsheet mode splits this: scalars come
from the scalar catalogue, while repeating line-item *tables* bind against a separate
list-catalogue — see [Spreadsheet mode](#spreadsheet-mode--a-styled-excel-workbook).)

## The two form/rich modes

### Form-fill — a fillable PDF (AcroForm)

Upload a **fillable PDF** and the source stage enumerates its AcroForm fields (**pypdf**).
An **AI/heuristic mapper** (`POST /templates/{id}/suggest-mapping`) proposes a binding from
each PDF form field to an extracted field path; you review and save the mapping. *Generate*
then fills the form with the document's values and, where a field is a signature, **stamps a
signature image** onto it (**reportlab**), returning a filled PDF.

- Deterministic where it can be: the heuristic mapper matches form-field labels to field
  paths by normalized name; the LLM leg only sharpens ambiguous ones and has an offline mock.
- Fields with no matching extracted value are left unmapped (e.g. an `approved` checkbox) —
  the mapper won't invent a binding.

### Rich-HTML — a DOCX or non-fillable PDF

Upload a **DOCX** (or a **non-fillable/formatted PDF**), or start blank. The source is
**converted to editable HTML** (**mammoth** for DOCX; **Docling** for PDF, with a **PyMuPDF**
fallback) and authored in a **TipTap** WYSIWYG editor. Placeholders are inserted from the
catalogue palette as `<span data-field="path">` chips (shown as `{{field}}` in the editor);
*Generate* renders **PDF** (**WeasyPrint**) and/or **DOCX** (**html4docx**).

Binding is **Jinja-free**: `bind_html` walks the stored `html_body`, finds each
`data-field` span, and substitutes the document's value in place — a data-attribute pass, not
a template-language render. This keeps the persisted HTML a valid, previewable document at
every step (no `{{ }}` syntax leaking into the layout) and means the same bound HTML feeds
both the WeasyPrint (PDF) and html4docx (DOCX) exporters.

## Spreadsheet mode — a styled Excel workbook

Upload a **styled `.xlsx`** and the source stage switches the template to
`TemplateMode.spreadsheet`. The workbook's formatting, formulas, column widths, and merges are
authored beforehand; you never edit its cells here — you **visually bind catalogue fields onto
cells** and let *Generate* fill a copy for any processed document. This is the third template
kind alongside form-fill and rich-HTML.

The flow is **upload → map → preview → export**:

1. **Upload.** `POST /templates/{id}/source` accepts the `.xlsx`, sets the mode, and
   **enumerates the per-sheet layout** (`enumerate_workbook_sheets` → one `SpreadsheetSheetMeta`
   per sheet: `name`, `max_row`, `max_col`, merged ranges, and set column widths). This metadata
   is persisted on `Template.spreadsheet_sheets` so the mapping UI has the layout without
   re-parsing the source. A new source resets any prior `cell_map` and sets `output_formats` to
   `["xlsx"]`. (The vision **Fidelity** check does *not* run for spreadsheets — the computed
   preview below is the spreadsheet equivalent.)
2. **Map.** The `SpreadsheetMappingGrid` renders a sheet's cells (`GET
   /templates/{id}/spreadsheet/cells?sheet=`, a merge-aware, capped grid) and you **click a cell,
   then click a field** to bind it. Two kinds of binding, persisted into `Template.cell_map`:
   - **Scalars** — a single catalogue field written into one cell, with an optional **suffix**.
     A numeric value keeps its number and the suffix is applied as an Excel **number format**
     (`#,##0.00" USD"`), so downstream formulas still see a number; a text value with a suffix is
     literally concatenated.
   - **Tables** — a repeating **line-item** field (from `GET
     /templates/{id}/spreadsheet/list-catalogue`) expanded **down rows** from an anchor cell. You
     pick which record fields go in which columns and in what **order**, plus a per-table
     **row mode** (see below).
3. **Preview.** `POST /templates/{id}/spreadsheet/preview?document_id=` fills a copy and returns
   a **formula-computed** grid — see the LibreOffice preview subsystem below.
4. **Export.** `POST /templates/{id}/generate?document_id=` writes the filled **`.xlsx`** and,
   when `output_formats` includes `pdf`, also a **PDF** (LibreOffice conversion; if that's
   unavailable the xlsx is still returned with a warning).

### The `cell_map` mapping representation

`Template.cell_map` (JSON) is the whole binding. Shape:

```jsonc
{
  "scalars": [
    { "sheet": "Invoice", "cell": "B2", "field_path": "vendor_name" },
    { "sheet": "Invoice", "cell": "B7", "field_path": "total_amount",
      "suffix": "USD", "is_signature": false }
  ],
  "tables": [
    { "sheet": "Invoice", "list_path": "line_items", "anchor_cell": "A11",
      "row_mode": "insert_row",
      "columns": [
        { "order": 0, "col": "A", "field_path": "description" },
        { "order": 1, "col": "C", "field_path": "amount", "suffix": "USD" }
      ] }
  ]
}
```

- A table `column`'s `field_path` is **record-relative**: a sub-model field name for a
  `list_composite` row (`line_items` → `description`, `amount`), or the `""` sentinel for a
  `list_scalar` collection (`parties`), where the record *is* the value.
- `is_signature` is **reserved** — signature stamping onto cells is a later build, so a scalar
  flagged `is_signature` is skipped (never written) this build.
- The **placeholder lint** ([below](#live-styled-preview--placeholder-lint)) extends to
  spreadsheets: every scalar `field_path` and each table column (`{list_path}.{column}`, or the
  bare `list_path` for the sentinel) is checked against the doc type's catalogue and surfaced as
  an advisory badge.

### The LibreOffice preview subsystem + fallback ladder

openpyxl reads formula **strings**, never their results, and a cell we just wrote has no cached
value — so a filled workbook read back with `data_only=True` shows `None` for every formula.
**LibreOffice headless (`soffice`) is the source of truth for computed values.**
`xlsx_preview.py` shells out to it:

- **Forced recalc-on-load.** Each invocation runs with a throwaway, **isolated
  `-env:UserInstallation` profile** seeded with a `registrymodifications.xcu` that sets both the
  ODF and OOXML recalc modes to *"always recalculate on load"* — without it, headless convert
  does not recompute and freshly written cells read back blank.
- **Isolation + bounding.** LibreOffice isn't concurrency-safe even with isolated profiles, so
  the `soffice` calls are serialized by a semaphore (`xlsx_recalc_concurrency`, default 1) and
  each is bounded by `xlsx_recalc_timeout_s`; the profile/work dir is always cleaned up.
- **sha256 disk cache.** A recompute is cached under
  `data/templates/<id>/preview_cache/<sha256(xlsx_bytes)>.xlsx`, so paginating a preview never
  re-runs the (slow) recalc for identical filled bytes.
- **Graceful fallback ladder — never hard-fails.** Every public function is a non-raising,
  degrading boundary. On *any* LibreOffice failure (missing binary, non-zero exit, timeout,
  absent output) the preview returns the **uncomputed** bytes and each formula cell shows its
  **raw formula string** flagged `computed=false` (the sheet/response `computed` flag goes
  `false`); the failure is not cached. PDF export returns `b""` and the generate route falls back
  to **xlsx-only** with a warning. The demo therefore works with no `soffice` installed — you
  just see formula strings instead of computed values.

### `insert_row` formula handling + the whole-column recommendation

A table's **row mode** decides how records beyond the anchor row are laid out:

- **`fill_next_empty_row`** (default) — write records straight into the anchor row and the rows
  below it, overwriting whatever is there. Simple; assumes the template left blank rows.
- **`insert_row`** — **insert** a fresh row per extra record and **clone the anchor row's style +
  formulas** into it. openpyxl's `insert_rows` copies nothing, so each inserted row is rebuilt:
  the anchor cell's `_style` is copied, and a **formula** cell is **translated** relative to its
  new row (via openpyxl's `Translator`), so a per-row `=qty*unit_price` follows each inserted
  line.

Inserting rows creates a formula hazard: a **bounded total below the table** like `=SUM(C7:C7)`
keeps referencing only the original anchor row and silently omits the inserted rows (openpyxl
shifts cell *positions* but never rewrites formula *text*). So after inserting, the engine
**auto-expands** any bounded same-sheet range whose columns intersect the table and whose end
row stopped at the anchor (`=SUM(C7:C7)` → `=SUM(C7:C10)`). Anything it can't safely fix raises
an upload/generate **warning** ("formula in *X* may not cover the new rows — verify in
preview"). **Whole-column totals (`=SUM(C:C)`) are recommended** — they carry no row bound, so
they always cover inserted rows and never warn; the UI surfaces this as a tip.

### Round-trip caveat — charts & images

The openpyxl round-trip preserves values, formulas, number formats, fonts, fills, borders,
merges, and column widths, but **charts, images, and pivots may not survive it**. An
**upload-time warning** tells you to verify the result in the preview before relying on it.

## The three AI assists (rich-HTML)

### AI edit — a streaming authoring agent

`POST /templates/{id}/agent` is a **tool-using authoring agent** that edits the template's
HTML/CSS from natural language ("make the header navy, right-align the totals, use a serif
body"). It streams over **SSE**, and its tools act directly on the template:
`set_html` / `set_css` / `insert_placeholder` / `list_available_fields` / `render_preview`.
Every edit it makes is snapshotted as a revision, so an AI restyle is as undoable as a manual
one. OpenRouter-backed, with an **offline mock provider** that applies a fixed restyle so the
mechanism is exercisable with no key.

### Fidelity — vision QA

`POST /templates/{id}/qa` renders the current template to **page images** (**pypdfium2**) and
asks a **vision model** to compare them against the uploaded example. Two modes:

- **source_pdf** — a side-by-side against the original you uploaded (does the render match the
  example's look?).
- **self-review** — for a DOCX source or a blank start (no comparable source PDF), the model
  critiques the render on its own.

It returns a verdict plus a **severity-coded discrepancy checklist**. The check **auto-runs
on source upload** (upload an example → the format is validated → the result is shown), and a
**"Send fixes to AI editor"** hand-off pipes the checklist straight into the AI-edit agent.
The vision leg has an offline mock.

### History + restore

Every edit — manual save or AI edit — snapshots a `TemplateRevision`.
`GET /templates/{id}/revisions` lists them; `POST /templates/{id}/revisions/{rev}/restore`
rolls the template back to one. **Restore is itself undoable** — it lands as a new revision,
so you can never lose a state by restoring.

## Live styled Preview + placeholder lint

- **Preview toggle** — the editor has an **Edit / Preview** switch. Preview renders the
  *persisted* `html_body` + `css` in a **sandboxed iframe**, so you see the styled document
  exactly as it will export (faithful to the WeasyPrint/DOCX output), not TipTap's in-editor
  approximation.
- **Placeholder ↔ doc-type consistency lint** — folded into `TemplateDetail.lint` as an
  **advisory badge**: it flags placeholders whose `data-field` path isn't in the bound doc
  type's catalogue (a typo, or a field the doc type no longer extracts). Advisory only — it
  never blocks generation.

## Known limitation — TipTap flattens complex HTML

**TipTap + StarterKit loads HTML into its own schema, dropping `div`s, classes, and tables it
doesn't model.** So for a complex styled layout, plain rich-text editing + *Save* is
**lossy** — typing in the editor and saving can strip styling the source came in with.

This is documented honestly rather than papered over. The **faithful** ways to view and change
a styled template are:

- the **Preview** toggle — renders the persisted `html_body`, so you always see the real
  styled document (not the flattened editor view); and
- the **AI edit** agent — it writes **raw HTML/CSS** via `set_html`/`set_css`, bypassing
  TipTap's schema entirely, so it can produce and preserve styling the WYSIWYG editor can't.

A **raw HTML/CSS code view** in the editor is the recommended future improvement — it would
give a direct, non-lossy way to hand-edit styled templates alongside the AI agent.

## Data model

`backend/app/models.py` (SQLModel → SQLite), additive to the existing schema:

| Table | Purpose |
| --- | --- |
| `Template` | A doc-type-bound template: `mode` (`form_fill`/`rich_html`/`spreadsheet`), the source artifact, and the mode's binding — the AcroForm mapping (form), `html_body` + `css` (rich), or `cell_map` + `spreadsheet_sheets` (spreadsheet) — plus the current state. |
| `TemplateRevision` | One snapshot per edit (manual or AI). Powers `GET /revisions` + restore; restore appends a new revision. |

Spreadsheet mode adds two **additive JSON columns** on `Template` (auto-migrated like the
existing map columns): `cell_map` (the field→cell mapping, [shape above](#the-cell_map-mapping-representation))
and `spreadsheet_sheets` (the per-sheet layout enumerated at source-upload time).

## Endpoints — `routes/templates.py` (prefix `/templates`)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/templates` | Create a template bound to a doc type. |
| `GET` | `/templates` | List templates. |
| `GET` | `/templates/{id}` | One template (`TemplateDetail`, incl. `lint`). |
| `PUT` | `/templates/{id}` | Update a template (html/css/mapping/**`cell_map`**/name). |
| `DELETE` | `/templates/{id}` | Delete a template. |
| `POST` | `/templates/{id}/source` | Upload the source document → **auto-detects the mode** (fillable PDF → form-fill; DOCX/PDF → rich-HTML, converted to HTML; **`.xlsx` → spreadsheet**, sheets enumerated) and auto-runs Fidelity (form/rich only). |
| `GET` | `/templates/{id}/catalogue` | The bound doc type's extractable field paths (binding targets). For a spreadsheet template this is **scalar-only** (`list_repeat=0`). |
| `GET` | `/templates/{id}/spreadsheet/sheets` | The per-sheet layout (`SpreadsheetSheetMeta[]`) enumerated at upload — for the mapping UI's sheet picker. |
| `GET` | `/templates/{id}/spreadsheet/cells?sheet=` | A capped, merge-aware grid of one sheet's non-empty cells (`SpreadsheetGrid`) for click-to-bind. |
| `GET` | `/templates/{id}/spreadsheet/list-catalogue` | The top-level **list fields** (+ record-relative columns) a table binding can expand down rows (`FieldListCatalogueEntry[]`). |
| `POST` | `/templates/{id}/spreadsheet/preview?document_id=` | A **formula-computed** preview of the filled workbook (`SpreadsheetPreviewResponse`); degrades to raw formula strings if LibreOffice is unavailable. |
| `POST` | `/templates/{id}/suggest-mapping` | AI/heuristic mapper suggests AcroForm-field → field-path bindings (form mode). |
| `POST` | `/templates/{id}/generate` | Fill the template from a chosen processed document → PDF and/or DOCX (form/rich), or **`.xlsx` + optional PDF** (spreadsheet). |
| `POST` | `/templates/{id}/agent` | **SSE**: the streaming, tool-using authoring agent edits html/css live. |
| `POST` | `/templates/{id}/qa` | Vision **Fidelity** check → verdict + severity-coded checklist. |
| `GET` | `/templates/{id}/revisions` | List revisions (edit history). |
| `POST` | `/templates/{id}/revisions/{rev}/restore` | Restore a revision (itself undoable). |

## Generation code — `backend/app/pipeline/generation/`

The generation layer is a set of small, single-purpose modules mirroring the pipeline's
elsewhere-stateless style:

| Module | Role |
| --- | --- |
| `catalogue` / `values` | The doc type's bindable field paths, and pulling a document's values for them. |
| `forms` / `mapper` / `generate` | AcroForm enumeration (pypdf), the field mapper, and the form fill + signature stamp (reportlab). |
| `convert` / `binder` / `render` | Source → editable HTML (mammoth/Docling/PyMuPDF); `bind_html` data-attribute binding; HTML → PDF (WeasyPrint) + DOCX (html4docx). |
| `authoring_agent` / `template_edits` | The SSE authoring agent and its HTML/CSS-editing tools. |
| `rasterize` / `preview` / `qa_vision` / `qa` | pypdfium2 rasterization, the styled-preview render, and the vision-QA loop. |
| `spreadsheet` | openpyxl core of the xlsx path: `enumerate_workbook_sheets` (sheet metadata), `read_template_grid` (mapping grid), `fill_spreadsheet` (write scalars + expand tables, clone/insert styled rows, translate + auto-expand formulas). |
| `xlsx_preview` | LibreOffice-headless subsystem: `recompute_workbook` (recalc + sha256 cache), `convert_to_pdf`, `read_computed_grid` — all non-raising, degrading boundaries. |
| `catalogue` (`list_field_catalogue`) | The top-level list fields (+ record-relative columns) a spreadsheet **table** binding targets. |
| `lint` | The placeholder ↔ doc-type consistency check (extended to spreadsheet `cell_map` paths). |

Frontend: `src/features/templates/` (+ `editor/` for the TipTap editor, placeholder palette,
Preview toggle, AI-edit / Fidelity / History tabs). Spreadsheet mode adds `SpreadsheetPanel`
(the map/preview shell), `SpreadsheetMappingGrid` (click-to-bind, merge-aware),
`SpreadsheetPreview` + the shared `SpreadsheetGridTable` (merge-aware grid render), and
`formatCell` (applies the number format in the preview).

## Tech stack & license notes

All generation libraries are **permissive** (BSD / MIT / Apache), installed as the backend
`docgen` extra (`uv sync --extra docgen`, already in `make install`):

- **pypdf** — AcroForm enumeration + fill.
- **reportlab** — signature-image stamping.
- **mammoth** — DOCX → HTML.
- **WeasyPrint** — HTML → PDF.
- **html4docx** — HTML → DOCX.
- **beautifulsoup4** — HTML parsing for binding/lint.
- **pypdfium2** — rasterizing a rendered PDF to page images for Fidelity/preview.
- **openpyxl** — reading/writing `.xlsx` in spreadsheet mode (**BSD**).
- **TipTap 3.x** (frontend) — the WYSIWYG editor.

Three deliberate choices:

- **Rasterization uses pypdfium2, not PyMuPDF.** PyMuPDF is AGPL; the new generation path
  avoids it, using the permissive pypdfium2 instead. (PyMuPDF stays only as the fallback in
  the pre-existing PDF→HTML conversion, not in any new rasterization.)
- **WeasyPrint needs system Pango + GDK-PixBuf** (`apt install libpango-1.0-0
  libgdk-pixbuf2.0-0`). Without them, **DOCX output still works** and **PDF degrades
  gracefully** — the feature never hard-crashes on a missing system library.
- **Spreadsheet formulas: LibreOffice is invoked as an external headless binary, not linked or
  bundled.** openpyxl (BSD) does the fill in-process; the formula recompute for preview/PDF
  shells out to the system `soffice` (`xlsx_soffice_path`, default `soffice` on PATH). This
  keeps the dependency at arm's length and licence-clean, and every `soffice` call degrades
  gracefully when the binary is absent ([fallback ladder](#the-libreoffice-preview-subsystem--fallback-ladder)).
  **[`xlsx-datafill`](https://www.npmjs.com/package/xlsx-datafill) (a JS library) was evaluated
  and deliberately *not* used** — its row-expansion idea was reimplemented in Python instead of
  taking on a Node dependency and a second templating model.

New settings (`backend/app/config.py`): `xlsx_soffice_path` (the binary), `xlsx_recalc_timeout_s`
(per-invocation timeout, default 60s), `xlsx_recalc_concurrency` (soffice semaphore size, default
1), `xlsx_max_table_rows` (per-table row cap, default 500).

## Offline tests

The core is **offline-tested** — WeasyPrint renders real PDFs and pypdfium2 rasterizes them for
real inside the tests; openpyxl fills real workbooks; only the LLM (authoring agent), vision
(Fidelity), and the LibreOffice formula recompute use mocks/skips, so `make test` needs no API
key. The spreadsheet **fill** is fully offline (openpyxl); the LibreOffice **recompute/PDF**
tests are **gated on `soffice`** and skip when it's absent (the degrading-fallback tests run
regardless). Full backend suite: **675 passed, 4 skipped** (`uv run --no-sync pytest tests/ -q`;
`soffice` present here, so the gated LibreOffice tests ran).

| File | Covers |
| --- | --- |
| `test_templates.py` | Template CRUD, revisions, restore, placeholder lint. |
| `test_generation_forms.py` / `_mapper.py` / `_fill.py` | AcroForm enumeration, field mapping, fill + signature stamp. |
| `test_generation_convert.py` / `_binder.py` / `_render.py` / `_rich.py` | DOCX/PDF → HTML, binding, HTML → PDF/DOCX, rich-HTML generate. |
| `test_authoring_agent.py` | The SSE authoring agent + its tools. |
| `test_generation_rasterize.py` / `_qa_vision.py` / `_qa.py` | The vision Fidelity loop. |
| `test_generation_lint.py` | Placeholder ↔ doc-type consistency (incl. spreadsheet `cell_map`). |
| `test_generation_spreadsheet.py` | openpyxl fill: scalars + suffix formats, table expansion, both row modes, `insert_row` style/formula cloning + bounded-total auto-expansion + residual warnings. |
| `test_generation_xlsx_preview.py` | LibreOffice recompute round-trip + sha256 cache + PDF (soffice-gated), and the non-raising degrading fallback (no soffice needed). |
| `test_smoke_e2e.py` | **End-to-end**: all three generation journeys (form-fill, rich-HTML, spreadsheet), top to bottom. |

## Demo launcher

`demo/run-demo.sh` is a **one-command launcher** on isolated ports (backend `:8077`, frontend
`:5188`), **mock AI by default** so every screen works with no key (pass `OPENROUTER_API_KEY=…`
for real AI edits + vision checks). Two ready sources ship in `demo/`:

- `demo/invoice-template.docx` — a formatted invoice → the **rich-HTML** flow.
- `demo/expense-form.pdf` — a fillable PDF → the **form-fill** flow.

Step-by-step walkthrough (~10 min), including both journeys, the Preview toggle, and the AI
assists: **[`demo/TESTING.md`](../demo/TESTING.md).**

> Use `http://localhost:5188` (not `127.0.0.1`) — the demo backend's CORS is pinned to the
> `localhost` origin.

> **Spreadsheet mode** works with any styled `.xlsx` you upload. For the **computed** preview
> and PDF export you need a system LibreOffice (`soffice` on PATH); without it the preview
> shows raw formula strings and generate returns the xlsx only — the flow never hard-fails.

---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Multi-document cases](./multi-document-cases.md) · [↑ Root README](../README.md)
