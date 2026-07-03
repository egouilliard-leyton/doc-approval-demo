# Multi-Document Cases — Design & Phase Plan

Status: **COMPLETE — all phases SHIPPED.** Backend Case foundation `19ce56c`;
cross-document reasoning (classify/reconcile/decide) `56bcf1f`; ap_match demo
completeness (po + delivery_note, vendor matching) `1fac578`; frontend (multi-doc
case UI + reconciliation) `ca5ffa8`; unified upload (one Home entry) `69c1d24`. Backend
483 tests, frontend 105 tests, all green; frontend live-verified end to end.
Author: brainstormed with the owner 2026-07-02.

## Problem

Today the whole system is keyed **1 document → 1 doc-type → 1 extraction result**. We
want to upload **multiple documents at once (possibly of different types)**, extract each,
and then **reason across them** so that each piece of information lands in the "correct
document and place", cross-checked between documents, feeding a single approval decision.

This is the multi-document version of what `doc-approval-demo` already does for one
document. The canonical use case is an **AP-style N-way match**: an invoice is approved
*because* its total matches the PO, its vendor matches the contract, and its line items
match the delivery note.

## Decisions locked with the owner

- **Product shape = reconcile into ONE decision** (not just grouped results). The documents
  are *sources* that jointly fill a shared set of **canonical fields**; disagreements drive
  the case verdict.
- **Conflict policy = flag for human review.** When candidate values disagree, the system
  never silently picks a winner. It surfaces all candidates with their sources and routes
  the case to `needs_review`. (Mirrors the existing single-doc `needs_review` path.)
- **Classification = auto-classify + confirm.** A new classifier pre-stage guesses each
  file's doc-type; the user reviews/corrects before extraction commits. (Frontend confirm
  step lands in the frontend phase; backend must expose the classify call + accept the
  confirmed types.)
- **Case shape = per-case choice of a DEFINED template OR an OPEN pile.** A defined "case
  type" carries the expected doc list + the canonical-field mapping. An open pile has no
  template; canonical fields are inferred from overlapping fields by name/kind.
- **Relationships 1:1 and 1:N both supported** via one abstraction: a canonical field is a
  **bag of grounded candidates** drawn from N documents. 1:1 is the single-candidate-per-doc
  special case of 1:N.

## Core new concept: the Case

A `Case` is an entity **above `Document`** that groups N documents and owns the
cross-document reasoning result.

```
Case ──┬── Document (invoice)   → StructuredResult
       ├── Document (PO)        → StructuredResult
       ├── Document (contract)  → StructuredResult
       └── Document (delivery)  → StructuredResult
                   │
                   ▼
       Case reasoning → reconciled canonical fields + cross-doc checks + one decision
```

## What we reuse vs build

- **Reuse as-is:** the extractor core (`DocTypeSpec → FlatExtraction → assemble →
  StructuredResult`) is stateless and doc-type-parameterized — per-document extraction
  needs **zero changes**; we call the existing pipeline once per doc. OCR, prescan,
  grounding, and the per-doc inspector are all reused.
- **Extend:** the rules engine → cross-document checks; the decision hybrid (deterministic
  rules hard-fail; LLM can't override) → case level; `Grounding`/`Citation` grow a
  `document_id` so a reconciled value cites *which* document + page + bbox it came from; the
  doc-type registry pattern → a parallel **case-type registry**.
- **Build new:** the `Case` entity + batch orchestration; the classifier stage; the
  reconciler (candidate-sets); the case-level frontend.

## Orchestration approach

Keep the current no-background-worker design. The client creates a case, fans out the
existing per-document stage calls (they already parallelize cleanly — each stage only
touches its own `stage_results` key), then calls a final server-side **case reconcile +
decide** endpoint. Minimal new backend surface.

## Existing seed to build on

Cross-document logic already exists in exactly one spot: `_prior_invoice_numbers`
(`routes/pipeline.py`) reaches across other documents' decided runs to catch duplicate
invoice numbers. The reconciler generalizes this "reach across documents" pattern.

---

# Phasing (for the orchestrated build)

Each phase is independently testable. Phases 1–2 are backend (pytest-gated); phase 3 is
frontend.

## Phase 1 — Backend Case foundation (THIS PHASE)

**Goal:** a `Case` entity + the plumbing to create cases, associate documents with them,
register case types, and read back a case that **groups** its documents' existing
`StructuredResult`s. **No reasoning yet** — this proves the data model + batch plumbing and
is fully unit-testable.

**In scope:**
1. **`Case` persistence** — a new table for cases, and a way to associate a `Document` with
   a case (either a nullable `case_id` on `Document` or a link table — architect decides,
   mirroring the existing schema conventions in `models.py`/`models/`). Idempotent,
   additive schema changes only (`IF NOT EXISTS` / guarded `ADD COLUMN`).
2. **Case CRUD + association API** — a new `routes/cases.py` (mirror `routes/documents.py`
   and `routes/doc_types.py` conventions): create a case (optionally with a case-type),
   list cases, get a case (with its documents + their statuses), associate/detach a
   document, delete a case. Existing single-file `POST /documents` should optionally accept
   a `case_id` so an uploaded document can join a case (mirror how `doc_type` is passed).
3. **Case-type registry** — a data-driven registry of case-type definitions parallel to the
   doc-type registry (`doc_types.py` + `DocTypeDefinitionRow`). A case-type definition
   carries: the expected member doc-types (with min/max cardinality for 1:1 vs 1:N) and a
   placeholder for the canonical-field mapping (the mapping is *consumed* in Phase 2 but the
   schema should carry it now). Seed at least one built-in case type (e.g. `ap_match` = 1
   invoice + 1 po + optional contract + optional delivery) mirroring how built-in doc-types
   are seeded in `main.py` lifespan.
4. **Case assembly (read model)** — a function + schema that, given a case, returns each
   member document's persisted `StructuredResult` (or its absence/status) grouped under the
   case. This is the "route & collate" view; it is the substrate Phase 2's reconciler reads.
5. **Schemas** — Pydantic response models in `schemas.py` for `Case`, `CaseDetail`,
   `CaseType`, and the assembled case view, mirroring the existing model style.
6. **Tests** — `backend/tests/test_cases.py` (+ registry tests) covering: case CRUD,
   document association/detachment, case-type registration + seeding, and case assembly
   grouping real per-doc structured results. Mirror `test_ingest.py` / `test_doc_types_api.py`.

**Out of scope for Phase 1 (do NOT build yet):**
- The classifier stage (Phase 2).
- The reconciler / candidate-sets / cross-doc checks / case decision (Phase 2).
- Any `document_id` additions to `Grounding`/`Citation` (Phase 2, when the reconciler needs
  provenance).
- All frontend work (Phase 3).
- Any change to the extractor core, OCR, prescan, or per-doc decision logic.

**Acceptance criteria:**
- A case can be created (open pile or with a case-type), documents associated, and the case
  read back with each document's status + structured result grouped under it.
- Built-in case type(s) seed on startup; custom case types can be registered from a row
  (even if a CRUD UI comes later, the registry + a create endpoint exist and are tested).
- `POST /documents` accepts an optional `case_id`.
- All new/changed behavior is covered by tests; full `pytest` suite is green.
- Only planned files changed.

## Phase 2 — Classifier + reconciler + case decision (backend)

Auto-classify endpoint; the candidate-set reconciler (normalize + tolerance compare per
kind: money/date/name; agreement → canonical value + citations; disagreement → conflict
check → `needs_review`); `document_id` added to `Grounding`/`Citation`; a case-level
decision that lifts the existing deterministic-checks-hard-fail + LLM-judgment hybrid to the
case, plus completeness checks for defined case types. Reuse `_prior_invoice_numbers` as the
template for reaching across documents.

## Phase 3 — Frontend

Multi-file dropzone; per-file classify + confirm UI; case overview (documents + per-doc
status); reconciliation view (canonical fields with multi-doc citations + conflict badges;
clicking a field navigates across documents); case decision panel. The deepest change:
`usePipeline` goes from a single `PipelineState` to a case holding `Record<docId,
PipelineState>` + a reconciliation result. A "case type" builder mirrors the existing
doc-type builder.
