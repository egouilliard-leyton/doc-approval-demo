# REST API reference

All endpoints are served by the FastAPI app (`backend/app/main.py`), default
`http://localhost:8000`. Interactive docs are available at `/docs` (Swagger) and
`/redoc` when the backend is running. Responses are JSON; asset URLs are server-relative
(`/files/...`) and must be absolutized by the client.

Grouped by router. `{id}` / `{doc_id}` is a document id; `{name}` a doc-type name;
`{key}` an engine key. The staged `/documents/{doc_id}/…` routes drive the pipeline one
stage at a time; **`POST /extract`** is the one-call black-box entry that runs the whole
pipeline and returns the final result.

---

## Health

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Liveness probe (`{"status":"ok"}`). |

## Documents — `routes/documents.py`

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/documents` | Upload a PDF/image (rasterized to pages) or a spreadsheet `.xlsx`/`.csv` (parsed to `sheets.json`, one page per sheet) → `DocumentDetail`. Optional `doc_type` and `case_id` form fields (a `case_id` joins the document to that case). 415 on an unaccepted extension. |
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
| `POST` | `/classify?ocr_engine=&provider=` | Advisory: guess the document's doc-type from its persisted OCR text → `ClassifyResult`. 409 if OCR hasn't run. Deliberately **not** persisted, doesn't advance status, and has no `GET` twin (auto-classify + confirm). Used by the multi-document case flow. |
| `POST` | `/structure?doc_type=&provider=&ocr_engine=` | Structure the chosen engine's OCR into grounded fields → `StructuredResult`. |
| `GET` | `/structure` | Persisted structuring result. |
| `PATCH` | `/structure/field` | Apply a reviewer edit (`{path, value}`) — writes the value into the stored structure (pinning `original_value`, setting `edited`) and logs a correction → updated `StructuredResult`. |
| `POST` | `/decide` | Run rules + the decision agent → `DecisionResult` (`approve`/`flag`/`needs_review`). Re-running this **invalidates & deletes any prior signature** (a seal must not outlive its approval). |
| `GET` | `/decide` | Persisted decision. |
| `POST` | `/sign?provider=` | Seal the **approved** PDF with a real PAdES signature → `SignResult`; advances the doc to `signed`. `400` non-PDF · `409` not decided · `409` decision ≠ `approve`. See [digital-signing.md](./digital-signing.md). |
| `GET` | `/sign` | Persisted signing result. `404` if never signed. |
| `POST` | `/validate-signature?provider=` | Re-verify the signature (signed PDF if present, else the original) → `SignatureValidation`. |

`path` in `PATCH /structure/field` is dotted (e.g. `invoice_no`, `line_items.0.amount`).

## Extract (black-box) — `routes/extract.py` (prefix `/extract`)

One synchronous call runs the **whole** single-document pipeline (upload → prescan → ocr
→ [classify] → structure → decide) on a single `PipelineRun` and returns the final result.
It reuses the staged pipeline functions + the `routes/pipeline.py` persistence helpers (not
the route handlers), so a black-box run lands stage results identical to driving the
`/documents/{id}/…` routes by hand.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/extract` | Multipart `file` + form params `doc_type?`, `ocr_engine?`, `run_prescan` (default true), `deskew` (default true), `clean` (default false), `classify_provider?`, `structuring_provider?`, `decision_provider?` → `ExtractionResult` (`document_id`, `doc_type`, `classify?`, `prescan?`, `structured`, `decision`, `warnings`). An empty `doc_type` **auto-classifies**; an explicit `ocr_engine` (or a spreadsheet) pins that one engine, else the doc type's routing chain resolves. Stage `HTTPException`s propagate with their status (415/413/400/422/504). |
| `POST` | `/extract/batch` | Multipart `files[]` + the same form params → `BatchExtractionResult` (`items[]`, `succeeded`, `failed`). **Sequential by design** (the duplicate-invoice dedup scan reads other documents' committed decisions); always HTTP 200, with each `BatchExtractionItem` isolating one file's outcome (`document_id` when the upload succeeded, then `result` **or** `error`+`error_status`). |

## Cases — `routes/cases.py` + `routes/case_pipeline.py` (prefix `/cases`)

A **case** groups N documents and reconciles their extractions into one cross-checked
decision. Members are the existing single-document pipeline results; the case adds
reconcile + decide on top. Design: [multi-document-cases.md](./multi-document-cases.md).

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/cases` | Create a case — an open pile or one bound to a registered case type (`{case_type?, label?}`; 422 on an unknown `case_type`) → `CaseDetail`. |
| `GET` | `/cases` | List cases, newest first (`CaseSummary[]`). |
| `GET` | `/cases/{case_id}` | A case with its member documents + their grouped structured results (`CaseDetail`). 404 if missing. |
| `DELETE` | `/cases/{case_id}` | Delete a case (its documents survive, becoming caseless; only the links are removed). |
| `POST` | `/cases/{case_id}/documents/{doc_id}` | Associate a document with the case (reassigns it from any prior case) → `CaseDetail`. |
| `DELETE` | `/cases/{case_id}/documents/{doc_id}` | Detach a document from the case (the document survives). |
| `POST` | `/cases/{case_id}/reconcile` | Reconcile members into the case's canonical fields and persist → `CaseReconciliation`. |
| `GET` | `/cases/{case_id}/reconcile` | Persisted reconciliation (404 if none). |
| `POST` | `/cases/{case_id}/decide?provider=` | Decide a reconciled case (`approve`/`flag`/`needs_review`), persisted → `CaseDecisionResult`. Reads the persisted reconcile (409 if not run first); deterministic cross-document checks run in code, LLM opt-in via `?provider=llm`. |
| `GET` | `/cases/{case_id}/decide` | Persisted case decision. |

## Case types — `routes/case_types.py` (prefix `/case-types`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/case-types` | List built-in + custom case types (`CaseTypeResponse[]`). |
| `GET` | `/case-types/{name}` | One case type's definition (404 if missing). |
| `POST` | `/case-types` | Create a custom case type (expected members + canonical-field mapping; 409 on a duplicate name) → `CaseTypeResponse`. |
| `DELETE` | `/case-types/{name}` | Delete a custom case type (built-ins → 403; 409 if cases still use it). |

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
| `PATCH` | `/doc-types/{name}/routing` | Update **only** the OCR-routing columns (`{preferred_ocr_engine?, ocr_fallback_engines[]}`) → `DocTypeResponse`. Allowed for **built-ins too** — routing is a pipeline concern orthogonal to the read-only definition. Engine names aren't validated here (unknown/disabled ones are skipped when the chain resolves). |
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
| `GET` | `/corrections/export?doc_type=&shape=raw\|examples&include_text=` | Export the correction log as newline-delimited JSON (`application/x-ndjson`, download). `shape=raw` (default): one line per correction, newest first. `shape=examples`: one training-style row per document (the reviewer-approved `fields`; when `include_text=true`, also the OCR text they were read from). |

## Overview — `routes/overview.py` (prefix `/overview`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/overview` | Consolidated admin counts: documents total + by status, decision breakdown, corrections total + corrected docs, doc-types, engines enabled, avg extraction confidence — plus the KPI-dashboard extension: `doc_types_used`, `accuracy` (`AccuracySummary`: `latest_overall_score`, `latest_line_item_score`, `eval_runs_total`, `doc_types_evaluated`), 30-day `throughput` + `maintenance` (`TimeSeries` `{window_days, buckets[{date, count}]}`), and `by_doc_type[]` (`DocTypeKpi` per resolved type: `documents`, `pct_of_total`, `avg_extraction_confidence`, `decisions`, `corrections_total`/`corrected_documents`, `latest_accuracy`(+`_engine`), `latest_line_item_score`, `eval_runs`) (`OverviewStats`). |

## Review queue — `routes/review_queue.py` (prefix `/review-queue`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/review-queue?threshold=&doc_type=` | Documents with **at-risk** extracted fields, worst-first → `ReviewQueueResponse` (`threshold`, `total_at_risk_fields`, `documents[]`). Each `ReviewQueueDocument` carries `document_id`, `filename`, `doc_type`, `status`, `last_decision`, `at_risk_count`, `lowest_confidence`, and `fields[]` (`ReviewQueueField` `{path, value, confidence, grounding}`, `path` matching the `PATCH /structure/field` grammar). |

A field is **at risk** iff `confidence < threshold` (default `field_review_confidence_threshold`),
it hasn't been `edited`, and it isn't a presence-kind field. Scans each document's latest run;
documents with zero at-risk fields are omitted.

## Evaluation — `routes/evaluation.py` (prefix `/eval`)

Accuracy-evaluation harness: score a golden fixture's expected extraction against a real
structuring result. Scoring is pure (`app.evaluation.scorer`); runs persist as `EvalRunRow`.

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/eval/goldens` | The golden catalogue, compact, sorted by id (`EvalGoldenSummary[]`). |
| `GET` | `/eval/goldens/{golden_id}` | One golden's full expected values (`EvalGoldenDetail`); 404 if unknown. |
| `POST` | `/eval/run` | Score a golden and persist the run — body `{golden_id, engine="mock", provider="mock", document_id?}` → `EvalRunResult`. With `document_id`, re-scores that document's persisted structure stage (404 if absent); otherwise runs OCR + structuring over the golden's sample first. |
| `GET` | `/eval/runs?golden_id=&doc_type=&engine=` | Persisted eval runs, newest first (`EvalRunSummary[]`). |
| `GET` | `/eval/runs/{run_id}` | One run in full detail (`EvalRunResult`); 404 if unknown. |

`EvalRunResult` scores: `overall_score`, `field_accuracy_exact` / `field_accuracy_normalized`,
`field_scores[]` (per scalar/dotted field: `expected`/`actual`/`kind`/`exact_match`/`normalized_match`),
and `collection_scores` (per collection field: `row_precision`/`row_recall`/`row_f1`,
`cell_accuracy`, `line_item_score = row_f1 × cell_accuracy`, `matched`/`n_expected`/`n_actual`).

## Templates — `routes/templates.py` (prefix `/templates`)

The template generator (create / author / `POST /templates/{id}/generate` a filled PDF or DOCX
from a document's structured fields) has its own router; the signing-relevant endpoint is below.

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/templates/{id}/outputs/{output_id}/sign?provider=` | Seal a **generated** output PDF with a real PAdES signature → `GeneratedSignResult`; writes `<output_id>-signed.pdf` beside the output. `404` template/output missing · `400` unknown provider. See [digital-signing.md](./digital-signing.md#4-signing-a-generated-document-the-outbound-flow). |

## Static files

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/files/...` | Serves `backend/data/` (page images, thumbnails, OCR markdown, artifacts, `sheets.json` for spreadsheets, and generated/signed template outputs). |

---

Response shapes are Pydantic models in `backend/app/schemas.py`; the TypeScript mirrors
live in `src/lib/types.ts` (+ `src/lib/doc-type-schema.ts`). The frontend client is
`src/lib/api.ts`.


---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · **API** · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)
