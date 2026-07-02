# Validation Model — Brainstorm

> 📖 **Looking for how to *use* the shipped rules?** See the
> **[Validation rules reference](./validation-rules.md)** — the catalogue of every primitive,
> the expression DSL, and how to add a new one. This document is the *design rationale* and
> the shipped/deferred status behind it.

> Status: **brainstorm / not built yet.** Depends on the *multi-document extraction & configuration* work landing first (the interesting validations are cross-document).
>
> Goal: let a doc-type author (and, later, a bundle/package author) declare **validations** the way they already declare extraction fields and rule primitives. This doc is a big idea-dump to prune together — not a spec.

---

## Implementation status

The **entire single-document validation surface is shipped** — 21 declarative rule primitives, each wired end-to-end (interpreter + serialization + save-time validation + builder UI + tests), all inside the existing "rules as data" engine. Built-in invoice/contract rule sets are untouched; the full suite passes (backend 429, frontend build + 41).

**Shipped primitives** (in `backend/app/rules/definition.py` unless noted):
`PresenceRuleDef` · `ThresholdCompareRuleDef` · `ArithmeticIdentityRuleDef` · `SetMembershipRuleDef` · `FieldDependencyRuleDef` · `UniquenessVsHistoryRuleDef` (pre-existing) · **`EqualityRuleDef`** (exact/normalized/regex/fuzzy + threshold slider) · **`DateConstraintRuleDef`** · **`ExpressionRuleDef`** (sandboxed formula DSL — `rules/expression.py`) · **`AggregateRuleDef`** · **`NumericRangeRuleDef`** · **`PercentageToleranceRuleDef`** · **`FormatRuleDef`** (IBAN/checksum/email/UUID/ISO — `rules/formats.py`) · **`ConditionalPresenceRuleDef`** · **`MutualExclusivityRuleDef`** · **`AtLeastNOfRuleDef`** · **`RequiredTogetherRuleDef`** · **`ContainsRuleDef`** · **`LengthBoundsRuleDef`** · **`FieldConfidenceFloorRuleDef`** · **`GroundedOnPageRuleDef`** · **`SignaturePresenceRuleDef`** · plus the two Tier-3 hatches (`CodedRuleDef`, `LlmAdvisoryRuleDef`).

**Deferred — cross-document (§3), and *only* because the substrate doesn't exist yet:** same-value/date across docs, bundle completeness, cross-references, roll-ups, and same-signatory *matching*. These need a **bundle** — a set of documents' extractions available together (§0) — which is the *multi-document extraction & configuration* work slated to be built first. Building them now would be dead scaffolding or a bundle model that collides with that effort. Once the bundle substrate lands, the natural next primitives are `CrossDocConsistencyRuleDef` and `BundleCompletenessRuleDef` (§6 sketch), and fuzzy matching (already shipped) pays off most there.

**Smaller deferred single-doc items:** fuzzy examples generated from the author's own documents (vs the static table); a stronger similarity metric than `difflib`; an `edited-field` provenance primitive; language/script detection.

---

## 0. Terminology (plain-language)

A few terms used throughout — worth pinning down because the whole design hinges on the difference.

- **Document type** — what you configure *today*: one kind of document (an invoice, a contract, a passport). It has its own field list and its own rule primitives. A validation on a document type looks at **one document in isolation** — "this invoice's total equals net + tax."

- **Bundle type** (a.k.a. package / dossier / case) — a **named set of documents that belong together and are reviewed as a unit**. Example: a "New client onboarding" bundle = 1 passport + 1 proof-of-address + 1 bank mandate. This concept **doesn't exist in the code yet** — it arrives with the multi-document work. A bundle type would declare *which* document types it expects and *how many* of each, and it's the natural home for validations that span more than one document ("the name on the passport matches the name on the bank mandate"). Think of it as: a document type is a *form*, a bundle type is a *checklist of forms that must agree with each other*.

  So "is validation scoped to a doc type or a bundle type?" really means: *does this check look at one document, or at the relationship between several?* Single-document checks (§2) live on the document type; cross-document checks (§3) live on the bundle type.

- **Bundle-level decision** — today each document gets its own verdict (`approve` / `needs_review` / `flag`). Once documents are reviewed as a bundle, the *bundle as a whole* also needs a verdict. A "names don't match across the pack" failure isn't really about any single document — the passport is fine, the mandate is fine, but **together they disagree**. That failure has nowhere to attach at the document level; it needs a verdict that belongs to the bundle. That bundle-wide verdict is what "bundle-level decision" means, and the reviewer UI would show it above the per-document results.

---

## 1. Where this fits in what already exists

Today rules live in `backend/app/rules/definition.py` as declarative **primitives** interpreted into `Check`s:

| Existing primitive | What it does | Scope |
|---|---|---|
| `PresenceRuleDef` | field carries a real value | single doc |
| `ThresholdCompareRuleDef` | numeric field `lte/gte/lt/gt` a threshold | single doc |
| `ArithmeticIdentityRuleDef` | `result == a + b ± tolerance` | single doc |
| `SetMembershipRuleDef` | value ∈ allowed list (ci, exact/substring) | single doc |
| `FieldDependencyRuleDef` | if A present then B required | single doc |
| `UniquenessVsHistoryRuleDef` | value not seen on a prior decided doc | **cross-doc (history)** |
| `CodedRuleDef` / `LlmAdvisoryRuleDef` | Tier-3 escape hatches | either |

Every primitive returns a `Check(name, passed, detail, severity)` where **severity ∈ {hard, review, advisory}**:
- `hard` → forces `flag` (LLM can explain, never override)
- `review` → caps decision at `needs_review`
- `advisory` → soft signal

**Design principle to keep:** validations are *data*, interpreted by a generic engine, with two escape hatches (coded + LLM). New validation ideas should mostly become **new primitives**, not new bespoke code. The two genuinely new engine capabilities the ideas below need are:

- **A. A cross-document scope** — validate a *set* of documents, not one. New `DecisionContext`-like input: the sibling docs in the bundle.
- **B. An expression/formula evaluator** — for ranges, arithmetic between arbitrary fields, dates, string transforms. A small safe DSL (no `eval`).

---

## 2. Single-document validations (extend today's engine)

### 2.1 Equality / exact-match
- **Exact equals** a constant. Toggles: case-insensitive, trim whitespace, ignore punctuation, unicode-normalize (accents), collapse internal whitespace.
- **One-of a set** (already `SetMembershipRuleDef`, but expose the `exact_ci` vs `substring_ci` toggle + a new `regex` match mode in the UI).
- **Not-equals / not-in blocklist** (e.g. status must not be "VOID").
- **Regex match** — field matches a pattern (IBAN, VAT id, SIREN, postal code, email, phone).
- **Checksum/format validators** — ✅ **SHIPPED** as `FormatRuleDef` (`backend/app/rules/formats.py`): a picklist of canned validators — IBAN mod-97, mod-10 checksum, email, URL, UUID, ISO 3166 country code, ISO 4217 currency code, digits, alphanumeric. Each is total (never raises). Best-effort structural checks, not registry lookups. Extensible: add a `Callable[[str], bool]` to the registry.

### 2.2 Numeric / quantitative
- **Range**: `min ≤ value ≤ max` (literal or expression bounds). Generalizes `ThresholdCompareRuleDef`.
- **Arithmetic identity** beyond `a+b`: `total == sum(line_items[].amount)`, `net + tax == gross`, `qty * unit_price == line_total`. → needs the expression evaluator + list aggregation.
- **Aggregate over a list**: `sum`, `count`, `min`, `max`, `avg` of a repeated field, compared to a scalar field (invoice total vs. Σ line items — a very common real check).
- **Percentage tolerance**: `|a - b| / b ≤ 5%` (softer than absolute tolerance).
- **Sign / positivity**: amount > 0, discount ≤ 0, etc.
- **Precision**: exactly 2 decimal places; integer-only.

### 2.3 Dates & time
- **Parse & validity**: field is a real date; not in the future; not before some epoch.
- **Range**: date within `[start, end]` — literals, *or* relative (`within 30 days of today`, `≤ 90 days after invoice_date`).
- **Ordering**: `start_date < end_date`, `signature_date ≥ contract_date`, `due_date > issue_date`.
- **Freshness / staleness**: document dated within the last N days (e.g. proof-of-address ≤ 3 months old — classic KYC).
- **Duration**: `end - start` within an allowed span (contract term 12–36 months).
- **Business-calendar**: falls on a business day, within a fiscal year/quarter.

### 2.4 Presence / dependency / conditional — ✅ **SHIPPED**
- **Conditional presence** — `ConditionalPresenceRuleDef`: if `condition_field` is present (optionally `== equals`) then `required_field` must be present (e.g. country==FR ⇒ vat_number required).
- **Mutual exclusivity** — `MutualExclusivityRuleDef`: `exactly_one` or `at_most_one` of `field_paths` present.
- **At-least-N-of** — `AtLeastNOfRuleDef`: at least `n` of `field_paths` present.
- **Required-together** — `RequiredTogetherRuleDef`: if any of `field_paths` present, all must be.

### 2.5 Text / semantic (LLM-advisory territory)
- ✅ **SHIPPED** — **Contains / mentions** a required clause or keyword — `ContainsRuleDef` (any/all of a keyword list, case-insensitive toggle).
- **Semantic equivalence**: "does the payment-terms text mean Net-30?" → `LlmAdvisoryRuleDef` (already exists).
- **Language / script** of the document matches expectation. *(not yet built)*
- ✅ **SHIPPED** — **Length bounds** on a text field — `LengthBoundsRuleDef` (min/max character length).

### 2.6 Confidence / provenance gates
- ✅ **SHIPPED** — Per-**field** confidence floor — `FieldConfidenceFloorRuleDef` (the document-wide gate still exists separately).
- ✅ **SHIPPED** — **Grounded-on-page** requirement — `GroundedOnPageRuleDef`: a field must carry a grounding with a page, not just a value (fights hallucinated fields). Uses the existing grounding stack.
- **Edited-field** signal: field was corrected by a reviewer → downstream caution. *(not yet built — the `edited` flag exists on FieldValue; a small follow-up primitive.)*

---

## 3. Cross-document validations (the new category)

This is what multi-doc extraction unlocks and where your examples mostly live. A **bundle** = a set of documents submitted together (e.g. an onboarding pack: ID + proof of address + bank statement + signed mandate). Validations run **across** the set.

### 3.1 Consistency / agreement across docs
- **Same value everywhere**: the *holder name* is identical across all docs (your headline example). Toggles reused from §2.1: case-insensitive, accent-fold, ignore titles (Mr/Mme), fuzzy-match threshold (Levenshtein / token-set ratio) because OCR and legal-vs-common names differ.
- **Same date across docs**, or **all dates within a window** of each other.
- **Same reference/id** (contract number, order number) appears on every doc that should carry it.
- **Address agreement** across ID + proof-of-address + bank statement (with a fuzzy/structured address comparison).
- **Amount reconciliation across docs**: invoice total == PO total == payment amount.
- **Currency agreement** across a bundle.

### 3.2 Completeness of the bundle
- **Required document types present**: bundle must contain ≥1 of each declared type (has an invoice AND a PO AND a delivery note).
- **Cardinality**: exactly one signed mandate; 1–N invoices; at most one of X.
- **No duplicates**: same invoice appearing twice (hash / fuzzy dedupe across the set).
- **Coverage**: every line item on the delivery note appears on an invoice.

### 3.3 Cross-reference / relational
- **Foreign-key style**: `invoice.po_number` must match the `po_number` of *some* PO in the bundle.
- **Roll-up**: sum of all invoice totals ≤ the framework-contract ceiling.
- **Sequence / no-gaps**: statement periods are contiguous (no missing month).

### 3.4 Signature & visual (signature *detection* shipped; matching deferred)
- ✅ **SHIPPED** — **Signature detection**: located + cropped signatures via the YOLOv8-ONNX post-pass ([signature-extraction.md](./signature-extraction.md)).
- ✅ **SHIPPED** — **Signature present** on the docs that require one — `SignaturePresenceRuleDef` (at least `min_count` detected signatures in a `kind="signature"` list field; reads the post-pass output). Same-signatory *matching* remains deferred (§9 — cross-doc + a similarity model).
- **Same signatory**: signature on doc A visually matches doc B (similarity score + threshold; human-review band in the middle).
- **Signature ↔ named party**: the signature block name matches the extracted party name.
- **Stamp / seal present** (company stamp, notary seal).
- **Photo/face match** (ID photo vs. selfie) — probably out of scope / sensitive, flag as its own decision.
- **Handwriting-vs-print**, initials on every page, etc.

> Signature *matching* (not just present/absent) has real accuracy and licensing caveats — see the library research in **§9** before committing to an approach.

### 3.5 Cross-document history (generalize what exists)
- Today's `UniquenessVsHistoryRuleDef` is invoice-number vs. prior decided docs. Generalize to **any field, any prior scope** (this reviewer, this counterparty, all-time).

---

## 4. The expression / formula layer (capability B)

> **What's a DSL?** DSL = *Domain-Specific Language*: a tiny, purpose-built mini-language for one narrow job — think Excel formulas, or the search box in Gmail. It is **not** a general programming language; it only knows about *your* documents and fields and a handful of safe operations (add, compare, "is this date within 90 days"). The point of a DSL here is that a validation like "the total must equal net + tax" is really just a little formula, and instead of writing new code for every possible check, we let the author *type the formula* (or click it together in a builder) and the engine evaluates it safely.
>
> So the open question "DSL-first or builder-UI-first?" means: **do we start by letting authors type formulas as text (powerful, but they have to learn the mini-language), or start with a point-and-click builder that writes the formula for them (friendlier, but only covers the shapes we build buttons for)?** Most likely both eventually — a builder for common cases, with raw formulas as an "advanced" escape hatch — the question is just which comes first.

Several ideas above collapse into "let the author write a small formula." Rather than a primitive per shape, offer a constrained **expression validator** (the DSL):

```
# examples the DSL should express
gross == net + tax                      # arithmetic identity
abs(total - sum(line_items[].amount)) <= 0.01
end_date > start_date
days_between(today(), doc_date) <= 90
lower(trim(holder_name)) == lower(trim(id.holder_name))   # cross-doc
value in ["EUR", "USD"]
matches(vat_number, "^FR[0-9A-Z]{2}[0-9]{9}$")
```

Design notes:
- **Safe evaluator only** — no Python `eval`. A tiny AST-walking interpreter (like the existing declarative interpreter) or a vetted lib. This mirrors the "reject non-serializable rule kinds" stance already in `serialization.py`.
- **Typed helpers**: `sum/min/max/avg/count`, `days_between`, `today`, `lower/upper/trim/normalize`, `matches(regex)`, `abs`, `round`.
- **Field references** by the same dotted path accessors (`fval`) the engine already uses; cross-doc refs need a namespace (e.g. `docs.invoice.total`, `all(docs).holder_name`).
- Every expression still produces a `Check` with a severity — the formula is just the `passed` computation. So it slots into the existing agent reconciliation untouched.

**Open question:** expose the raw DSL to authors, or keep a friendly builder UI that *generates* expressions (safer, discoverable) with the DSL as an "advanced" escape hatch? Probably both, mirroring primitives + Tier-3.

> ✅ **SHIPPED** — `ExpressionRuleDef` is live (`backend/app/rules/expression.py`): a sandboxed AST evaluator (default-deny node whitelist — no `Attribute`/`Subscript`, so gadget chains are unparseable; DoS caps on length/nodes/depth; re-parsed on every run, never trusting save-time validation; fail-soft to skip). Helpers: `sum_of/min_of/max_of/avg_of/count`, `abs/round/len/lower/upper/trim`, `matches`, `days_between/today/to_date`, `is_present/field`. Exposed in the builder as a **Formula** textarea with a helper hint (the "both" answer — DSL engine + a UI field for it). Also shipped as friendly dedicated primitives so authors don't *have* to write formulas: `AggregateRuleDef` (total == Σ line_items), `NumericRangeRuleDef`, `PercentageToleranceRuleDef`.

---

## 5. Cross-cutting concerns to decide

- **Severity per validation.** Keep the `hard / review / advisory` model. Each new validation should let the author pick. (E.g. "same name" might be `review`, "signature missing" `hard`.)
- **Missing-data behavior.** Today most primitives *skip* (no check) when a field is absent, so they never fail on missing data — presence is a separate rule. Preserve that; make skip-vs-fail an explicit toggle per validation (some authors *want* "absent ⇒ fail").
- **Where do cross-doc results attach?** To the bundle, to each doc, or both? A "same name" failure is about the *set* — the decision surface / UI needs a bundle-level view, not just per-doc.
- **Grounding & explainability.** A failing cross-doc check should cite *which* docs/fields disagreed (reuse citations/grounding). "Name mismatch: `SMITH` on invoice p.1 vs `SMYTH` on ID p.1."
- **Fuzzy vs. exact — DECIDED & SHIPPED (single-doc):** `EqualityRuleDef` now has a `fuzzy` match mode with a tunable `fuzzy_threshold` slider (0.6–1.0) in the builder, backed by stdlib `difflib.SequenceMatcher` (no new dependency). Fuzzy composes with the normalization toggles. The slider shows the static example table below as its guide. **Still deferred:** (a) generating the examples from the author's *own* recent documents rather than the static table; (b) a stronger similarity metric than difflib (token-set / Levenshtein / Jaro-Winkler via `rapidfuzz`) if difflib proves too crude on real names/addresses; (c) fuzzy on the not-yet-built cross-document consistency check. The author is never forced to pick fuzzy *or* exact — they dial it. Sketch of the slider and the examples it surfaces (using name matching):

  | Threshold | Mode | Accepts as "same" | Rejects | Feel |
  |---|---|---|---|---|
  | `1.00` | Exact | `Jean Dupont` = `Jean Dupont` | `Jean Dupont` ≠ `jean dupont` | Strictest — byte-for-byte |
  | `0.98` | Normalized | `jean  dupont` = `Jean Dupont` (case/space/accents folded) | `Jean Dupont` ≠ `Jean Dupond` | Ignores formatting only |
  | `0.90` | Fuzzy (tight) | `Jean Dupond` ≈ `Jean Dupont` (1-char OCR slip) | `Jean Dupont` ≠ `J. Dupont` | Tolerates OCR noise |
  | `0.80` | Fuzzy (loose) | `J. Dupont` ≈ `Jean Dupont`; `Dupont Jean` ≈ `Jean Dupont` | `Jean Dupont` ≠ `Pierre Dupont` | Tolerates abbreviations / word order |
  | `0.60` | Fuzzy (very loose) | `Jon Dupont` ≈ `Jean Dupont` | `Jean Dupont` ≠ `Jean Martin` | Risky — starts accepting real differences |

  Implementation notes: the "normalized" band is the case/accent/whitespace toggles from §2.1; the "fuzzy" band is a string-similarity ratio (token-set / Levenshtein). The examples in the table would ideally be **generated from the author's own recent documents** where possible, not canned, so the preview is realistic for their data. The same slider generalizes to addresses and amounts (with number-aware distance) — the concept is one control, live preview, per validation.
- **Ordering / dependencies.** Should some validations short-circuit others (skip cross-doc checks if the bundle is incomplete)?
- **Performance / cost.** LLM-advisory and signature-similarity checks are expensive; batch and cache. Keep deterministic checks first, LLM last (current engine already leans deterministic-first).
- **Localization.** Names, dates, numbers, addresses are locale-dependent (date formats, decimal separators, name order). Comparisons must normalize by locale.
- **Testing.** Every primitive today is unit-tested with a `_test_fn` hook for the LLM path. New primitives + the expression evaluator need the same offline-testable shape.

---

## 6. Suggested data-model sketch (to react to, not final)

Mirror the existing declarative pattern — new `ValidationDef` primitives alongside the rule primitives, or folded into the rule list:

```python
@dataclass
class EqualityRuleDef:              # §2.1
    name: str
    field_path: str
    expected: str | None            # literal, or...
    expected_field: str | None      # ...another field (single or cross-doc)
    severity: Severity
    case_insensitive: bool = False
    trim: bool = False
    normalize_accents: bool = False
    match_mode: Literal["exact", "regex", "fuzzy"] = "exact"
    fuzzy_threshold: float = 1.0

@dataclass
class DateConstraintRuleDef:        # §2.3
    name: str
    field_path: str
    severity: Severity
    not_future: bool = False
    min: str | None = None          # literal date or relative expr
    max: str | None = None
    before_field: str | None = None
    after_field: str | None = None

@dataclass
class CrossDocConsistencyRuleDef:   # §3.1 — the headline
    name: str
    field_path: str                 # same path evaluated on every doc in scope
    scope: Literal["all", "by_type"] = "all"
    severity: Severity
    comparison: Literal["exact", "normalized", "fuzzy"] = "normalized"
    fuzzy_threshold: float = 0.9

@dataclass
class BundleCompletenessRuleDef:    # §3.2
    name: str
    required_types: list[str]
    cardinality: dict[str, tuple[int, int | None]]  # type -> (min, max)
    severity: Severity

@dataclass
class ExpressionRuleDef:            # §4 — the general escape valve
    name: str
    expression: str                 # safe DSL
    severity: Severity

@dataclass
class SignatureMatchRuleDef:        # §3.4 — pending signature extraction
    name: str
    scope: Literal["all", "by_type"]
    severity: Severity
    similarity_threshold: float = 0.8
    review_band: tuple[float, float] = (0.6, 0.8)  # middle → needs_review
```

Cross-doc primitives need the engine to pass **the bundle** into the interpreter — extend `DecisionContext` (or a new `BundleContext`) with `sibling_docs: list[StructuredResult]`.

---

## 7. Priority cut (a starting proposal)

**Build first (high value, low new-machinery):**
1. ✅ **SHIPPED** — `EqualityRuleDef` with normalization toggles (your "exactly this, lowercase toggle"). exact/normalized/regex modes + negate. Fuzzy deferred (see §5). Cross-field refs use the `_path` suffix (`expected_field_path`).
2. `CrossDocConsistencyRuleDef` for name/date/reference (your headline "same name / same date"). *Blocked on the bundle-type concept (§0).*
3. ✅ **SHIPPED** — `DateConstraintRuleDef` (ranges + ordering + not-future). Dates parsed best-effort by a stdlib `as_date()` — ambiguous formats like `05/02/2024` assume US MM/DD and unparseable dates skip the rule (a known limitation; the long-term fix is a `coerce: date` extraction-time normalizer).
4. Aggregate arithmetic (total == Σ line items) via a small expression eval.

4b. ✅ **SHIPPED** — Aggregate arithmetic (`total == Σ line_items`) as `AggregateRuleDef`, plus `NumericRangeRuleDef` and `PercentageToleranceRuleDef`.

**Build next (needs new capability):**
5. ✅ **SHIPPED** — `ExpressionRuleDef` — the general formula layer (safe sandboxed DSL, see §4).
6. `BundleCompletenessRuleDef` — required types + cardinality + dedupe. *Blocked on the bundle-type concept (§0).*

**Build when dependencies land:**
7. `SignatureMatchRuleDef` (waits on signature extraction).
8. Format/checksum library (IBAN/VAT/etc.) — nice-to-have, mostly independent.

---

## 8. Open questions for us

1. Is validation scoped to a **doc type**, a **bundle type**, or both? (See §0 — single-doc checks live on the doc type, cross-doc checks on the bundle type. The real question is how much we build before the bundle-type concept exists.)
2. DSL-first or builder-UI-first for formulas? (See §4 for what this means — probably both, question is ordering.)
3. ~~How much fuzzy matching~~ — **DECIDED (§5): both exact and fuzzy, as a configurable threshold slider with live examples.** Remaining sub-question: which similarity metric (token-set ratio vs. Levenshtein vs. Jaro-Winkler) as the default.
4. Do cross-doc failures produce a **bundle-level decision** separate from per-doc decisions? (See §0 for what "bundle-level" means. Leaning yes — a bundle needs its own verdict.)
5. Signature matching — **researched (§9): present/absent for v1, similarity as human-review-assist only.** Remaining sub-question: self-host the SigNet feature extractor vs. a commercial API, given the GPDS non-commercial licensing caveat.

---

## 9. Signature-matching library research (for §3.4)

Findings from a scan of the offline-signature-verification landscape, weighted toward accuracy and whether it's usable in a commercial product.

**The important framing first:** the academic work is built for a *different* problem than ours. It's tuned for **skilled-forgery detection** — "is this signature, claimed to be Alice's, a genuine Alice or a forger imitating Alice?" — on **clean, pre-cropped** signature images. Our problem is **writer-independent 1:1 matching on noisy scanned crops** — "is the scribble on the mandate the same person as the scribble on the passport?" Benchmark numbers (EER ~1.7–7%) will **not** carry over to messy real documents. Treat any published accuracy as an optimistic ceiling.

| Option | What it is | Accuracy signal | License / cost | Fit for us |
|---|---|---|---|---|
| **luizgh/sigver** (SigNet) | PyTorch feature extractor + writer-dependent classifiers; the de-facto reference impl | SigNet paper: EER ~1.7–7% on GPDS/CEDAR (clean data) | Code BSD-3, **but pretrained weights trained on GPDS = non-commercial only** ⚠️ | Best-known model, but the license caveat is a blocker for a commercial product unless we retrain on a commercially-usable dataset |
| **fastforwardlabs/signver** | Pairwise genuine/forgery library, exactly our "compare two" shape | Experimental | Apache-ish, **unmaintained** | Nice API shape, but not something to depend on in prod |
| Siamese/SigNet re-impls (Aftaab99, Yash-10, etc.) | Convolutional Siamese nets, CEDAR-trained | 76–97% depending on dataset/paper (cross-dataset GPDS→CEDAR ~96.9% in one study) | Mixed / educational | Good references to *train our own*, not drop-in |
| Siamese-Transformer (few-shot) | 2024 SOTA architecture | Claimed **1.72% EER on GPDS-160** vs prior 6.97% | Research paper, no maintained package | Direction to watch; not productizable today |
| Commercial APIs | Hosted signature-verification services | Vendors claim 95%+ but independent comparison data is thin | Per-call cost, data leaves our infra | Fastest path if accuracy matters and we accept the cost/privacy tradeoff |

**Recommendation for v1:**
1. **Ship "signature present / absent"** — this is reliable, low-risk, and covers a lot of real value (a required signature is simply missing).
2. **Treat "same signatory" as review-assist, never auto-decide** — compute a similarity score, show it to the reviewer with the two crops side-by-side, and use a **review band** (e.g. high score → advisory pass, low → advisory concern, middle → `needs_review`). Do **not** let it hard-flag.
3. **If we do build matching:** self-hosting a Siamese/SigNet feature extractor keeps data private and is the sound long-term path, but **budget for training on a commercially-licensed dataset** (the best pretrained weights are GPDS-encumbered). A commercial API is the shortcut if we accept per-call cost and sending signature crops off-box.

**Sources:** [luizgh/sigver](https://github.com/luizgh/sigver) · [fastforwardlabs/signver](https://github.com/fastforwardlabs/signver) · [SigNet paper (arXiv 1707.02131)](https://arxiv.org/pdf/1707.02131) · [Aftaab99/OfflineSignatureVerification](https://github.com/Aftaab99/OfflineSignatureVerification) · [Yash-10 siamese impl](https://github.com/Yash-10/signature-verification-siamese-network) · [Siamese-Transformer few-shot (2024)](https://www.researchgate.net/publication/378536334_Siamese-Transformer_Network_for_Offline_Handwritten_Signature_Verification_using_Few-shot) · [Cross-dataset generalization (arXiv 2510.17724)](https://arxiv.org/html/2510.17724v1)


---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · [Roadmap](./ROADMAP.md) · [Validation rules](./validation-rules.md) · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · **Validation brainstorm** · [↑ Root README](../README.md)
