# REST API reference

All endpoints are served by the FastAPI app (`backend/app/main.py`), default
`http://localhost:8000`. Interactive docs are available at `/docs` (Swagger) and
`/redoc` when the backend is running. Responses are JSON; asset URLs are server-relative
(`/files/...`) and must be absolutized by the client.

Grouped by router. `{id}` / `{doc_id}` is a document id; `{name}` a doc-type name;
`{key}` an engine key.

---

## Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe (`{"status":"ok"}`). |

## Documents — `routes/documents.py`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/documents` | Upload a PDF/image (rasterized to pages) or a spreadsheet `.xlsx`/`.csv` (parsed to `sheets.json`, one page per sheet) → `DocumentDetail`. Optional `doc_type` form field. 415 on an unaccepted extension. |
| `GET` | `/documents` | List all documents (`DocumentSummary[]`). |
| `GET` | `/documents/{id}` | One document + its pages (`DocumentDetail`). |
| `DELETE` | `/documents` | Delete **all** documents (and their files). |
| `DELETE` | `/documents/{id}` | Delete one document. |

## Pipeline — `routes/pipeline.py` (prefix `/documents/{doc_id}`)

Each stage is persisted and independently re-runnable. `POST` runs the stage; `GET`
returns the last persisted result without recomputing.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/prescan` | Run pre-flight quality checks (body: `{deskew, clean}`) → `QualityReport`. |
| `GET` | `/prescan` | Persisted quality report. |
| `POST` | `/ocr?engine=` | Run OCR with `engine` (`docling` \| `mock` \| any enabled VLM key; default `OCR_DEFAULT_ENGINE`) → `OCRResult`. 400 on unknown/disabled engine. Spreadsheet docs ignore `engine` and always use the native `spreadsheet` parser. |
| `GET` | `/ocr?engine=` | Persisted OCR result for that engine. |
| `POST` | `/structure?doc_type=&provider=&ocr_engine=` | Structure the chosen engine's OCR into grounded fields → `StructuredResult`. |
| `GET` | `/structure` | Persisted structuring result. |
| `PATCH` | `/structure/field` | Apply a reviewer edit (`{path, value}`) — writes the value into the stored structure (pinning `original_value`, setting `edited`) and logs a correction → updated `StructuredResult`. |
| `POST` | `/decide` | Run rules + the decision agent → `DecisionResult` (`approve`/`flag`/`needs_review`). |
| `GET` | `/decide` | Persisted decision. |

`path` in `PATCH /structure/field` is dotted (e.g. `invoice_no`, `line_items.0.amount`).

## Doc types — `routes/doc_types.py` (prefix `/doc-types`)

> A custom type's `rule_definition` is a list of validation primitives. `POST`/`PUT`
> validate them (422 on a bad rule or unsafe formula) via `validate_custom_rule_dict`. For
> the full rule vocabulary and the expression DSL, see
> [validation-rules.md](./validation-rules.md).

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/doc-types` | List built-in + custom types (`DocTypeResponse[]`). |
| `GET` | `/doc-types/{name}` | One type's definition. |
| `POST` | `/doc-types` | Create a custom type (validated JSON; a blank label defaults to the name). |
| `PUT` | `/doc-types/{name}` | Full-replace a custom type (built-ins → 403). |
| `DELETE` | `/doc-types/{name}` | Delete a custom type (409 if documents still use it). |
| `POST` | `/doc-types/{name}/preview` | Dry-run a definition against sample text → `DocTypePreviewResponse`. |

## Doc-type wizard — `routes/doctype_assist.py` (prefix `/doc-types`)

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/doc-types/assist` | One Q&A turn → `{questions, spec_markdown, done, draft_doctype}`. |
| `POST` | `/doc-types/assist/ingest` | Upload a process/example doc → extracted text. |
| `POST` | `/doc-types/assist/annotate` | Spawn a Plannotator session over the spec → `{session_id, url}`. |
| `GET` | `/doc-types/assist/annotate/{session_id}` | Poll for the user's annotations. |
| `DELETE` | `/doc-types/assist/annotate/{session_id}` | Cancel a session. |

## OCR engines — `routes/engines.py` (prefix `/engines`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/engines` | Engines selectable at upload (docling + enabled VLMs) → `EngineInfo[]`. |
| `GET` | `/engines/catalog` | All connected VLM engines, enabled + disabled (`VlmEngineResponse[]`). |
| `GET` | `/engines/openrouter-models` | Image-capable OpenRouter models for the add-model dropdown (live, with curated fallback). |
| `POST` | `/engines` | Connect a VLM engine (`{label, model, key?, enabled?}`); `key` derived from the slug if omitted; 409 on duplicate. |
| `PATCH` | `/engines/{key}` | Enable/disable or relabel an engine. |
| `DELETE` | `/engines/{key}` | Disconnect an engine. |

## Corrections — `routes/corrections.py` (prefix `/corrections`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/corrections?document_id=` | Logged field corrections, newest first; optional per-document filter (`FieldCorrection[]`). |

## Overview — `routes/overview.py` (prefix `/overview`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/overview` | Consolidated admin counts: documents total + by status, decision breakdown, corrections total + corrected docs, doc-types, engines enabled, avg extraction confidence (`OverviewStats`). |

## Static files

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/files/...` | Serves `backend/data/` (page images, thumbnails, OCR markdown, artifacts, and `sheets.json` for spreadsheets). |

---

Response shapes are Pydantic models in `backend/app/schemas.py`; the TypeScript mirrors
live in `src/lib/types.ts` (+ `src/lib/doc-type-schema.ts`). The frontend client is
`src/lib/api.ts`.
