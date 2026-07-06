# Document Generation from Templates

Status: **COMPLETE — all phases SHIPPED.** Phase 0 scaffolding `f48444d` → Phase 5 polish
`228e502`; end-to-end smoke tests `e6f9a1b`; README `a44431a`; demo assets `b4bf906`; live
styled Preview toggle `5335468` + `5dd711a`. 122 backend tests, fully offline. Built
2026-07.

Once a document has been **extracted**, this feature turns its fields into a filled,
downloadable **DOCX / PDF**. You create a **Template** (tied to a doc type), upload a source
document that becomes the layout, bind its blanks to extracted field paths, and *Generate*
a filled artifact for any processed document of that type.

> For the pipeline that produces the extraction this fills from, see
> [ARCHITECTURE.md](./ARCHITECTURE.md). For the REST surface, see [API.md](./API.md). For a
> hands-on walkthrough, see [`demo/TESTING.md`](../demo/TESTING.md).

## Overview

A `Template` belongs to a doc type and carries everything needed to render a filled document.
The **mode is auto-detected from the source you upload**, so you never pick it by hand:

```
extracted Document ─┐
                    ├─▶ Template (doc-type-bound) ─▶ Generate ─▶ filled PDF / DOCX
uploaded source ────┘        │
                    ┌────────┴─────────┐
              fillable PDF        DOCX / non-fillable PDF
              → Form-fill mode    → Rich-HTML mode
```

Both modes share the same **field catalogue** (`GET /templates/{id}/catalogue`): the doc
type's extractable field paths (`vendor_name`, `total_amount`, `line_items.0.amount`, …),
which are what a binding points at. At generate time the values are pulled from the chosen
processed document's persisted `StructuredResult`.

## The two modes

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
| `Template` | A doc-type-bound template: `mode` (`form`/`rich`), the source artifact, the AcroForm mapping (form mode) or `html_body` + `css` (rich mode), and the current state. |
| `TemplateRevision` | One snapshot per edit (manual or AI). Powers `GET /revisions` + restore; restore appends a new revision. |

## Endpoints — `routes/templates.py` (prefix `/templates`)

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/templates` | Create a template bound to a doc type. |
| `GET` | `/templates` | List templates. |
| `GET` | `/templates/{id}` | One template (`TemplateDetail`, incl. `lint`). |
| `PUT` | `/templates/{id}` | Update a template (html/css/mapping/name). |
| `DELETE` | `/templates/{id}` | Delete a template. |
| `POST` | `/templates/{id}/source` | Upload the source document → **auto-detects the mode** (fillable PDF → form-fill; DOCX/PDF → rich-HTML, converted to HTML) and **auto-runs Fidelity**. |
| `GET` | `/templates/{id}/catalogue` | The bound doc type's extractable field paths (binding targets). |
| `POST` | `/templates/{id}/suggest-mapping` | AI/heuristic mapper suggests AcroForm-field → field-path bindings (form mode). |
| `POST` | `/templates/{id}/generate` | Fill the template from a chosen processed document → PDF and/or DOCX. |
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
| `lint` | The placeholder ↔ doc-type consistency check. |

Frontend: `src/features/templates/` (+ `editor/` for the TipTap editor, placeholder palette,
Preview toggle, AI-edit / Fidelity / History tabs).

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
- **TipTap 3.x** (frontend) — the WYSIWYG editor.

Two deliberate choices:

- **Rasterization uses pypdfium2, not PyMuPDF.** PyMuPDF is AGPL; the new generation path
  avoids it, using the permissive pypdfium2 instead. (PyMuPDF stays only as the fallback in
  the pre-existing PDF→HTML conversion, not in any new rasterization.)
- **WeasyPrint needs system Pango + GDK-PixBuf** (`apt install libpango-1.0-0
  libgdk-pixbuf2.0-0`). Without them, **DOCX output still works** and **PDF degrades
  gracefully** — the feature never hard-crashes on a missing system library.

## Offline tests

The whole feature is **fully offline-tested** — WeasyPrint renders real PDFs and pypdfium2
rasterizes them for real inside the tests; only the LLM (authoring agent) and vision (Fidelity)
legs use deterministic mocks, so `make test` needs no API key. **122 backend tests pass.**

| File | Covers |
| --- | --- |
| `test_templates.py` | Template CRUD, revisions, restore, placeholder lint. |
| `test_generation_forms.py` / `_mapper.py` / `_fill.py` | AcroForm enumeration, field mapping, fill + signature stamp. |
| `test_generation_convert.py` / `_binder.py` / `_render.py` / `_rich.py` | DOCX/PDF → HTML, binding, HTML → PDF/DOCX, rich-HTML generate. |
| `test_authoring_agent.py` | The SSE authoring agent + its tools. |
| `test_generation_rasterize.py` / `_qa_vision.py` / `_qa.py` | The vision Fidelity loop. |
| `test_generation_lint.py` | Placeholder ↔ doc-type consistency. |
| `test_smoke_e2e.py` | **End-to-end**: both generation journeys, top to bottom. |

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

---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Multi-document cases](./multi-document-cases.md) · [↑ Root README](../README.md)
