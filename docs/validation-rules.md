# Validation rules reference

The catalogue of **validation rule primitives** a document type can declare, how they
behave, the safe expression DSL, and how to add a new one.

> **See also:** [ARCHITECTURE.md §5 (Rules & decision)](./ARCHITECTURE.md#5-rules--decision)
> for where rules sit in the pipeline · [API.md](./API.md) for the doc-types CRUD/preview
> surface · [VALIDATION-BRAINSTORM.md](./VALIDATION-BRAINSTORM.md)
> for the design rationale, the shipped/deferred status, and the cross-document roadmap.

---

## 1. What a rule is

A document type carries a **rule set** — a list of small declarative *primitives* stored
as JSON (`DocTypeDefinitionRow.rule_definition`) and interpreted at decision time. Each
primitive reads the extracted `fields` and emits one `Check(name, passed, detail, severity)`.
The decision agent reconciles the checks with the LLM's judgment; **deterministic rules are
authoritative** — the LLM explains but can never override a hard fail.

Rules are **data, not code**. Custom (user-built) types are validated JSON that can never
carry executable code — even the formula DSL (§4) is evaluated by a sandboxed interpreter,
never Python `eval`. Built-in `invoice`/`contract` types keep their rules in code and may
use the Tier-3 coded escape hatch; custom types cannot.

Where it lives:

| File | Role |
| --- | --- |
| `backend/app/rules/definition.py` | The primitive dataclasses + the `_interpret` interpreter + `build_ruleset`. |
| `backend/app/rules/base.py` | Field accessors (`fval`, `present`, `as_number`, `as_date`, `_node`). |
| `backend/app/rules/expression.py` | The sandboxed formula evaluator + list-aggregation helpers. |
| `backend/app/rules/formats.py` | The canned format/checksum validator registry. |
| `backend/app/serialization.py` | `_KIND_MAP` (kind ↔ dataclass) + `validate_custom_rule_dict` (save-time 422 gate). |
| `src/lib/doc-type-schema.ts` | The TypeScript mirror of every rule kind. |
| `src/features/doctypes/RuleListEditor.tsx` | The builder UI (one form per kind). |
| `backend/app/pipeline/doctype_schema_reference.py` | Renders these primitives into the Create-with-AI wizard's system prompt, introspected from `_KIND_MAP` — so the AI can author every kind below without a hand-maintained list. |

---

## 2. Severity & the missing-data convention

Every check carries a **severity** that steers the decision:

| Severity | Effect on the decision |
| --- | --- |
| `hard` | Forces `flag`. The LLM can explain it but never override it. |
| `review` | Caps the decision at `needs_review`. |
| `advisory` | A note in the trace; doesn't change the verdict on its own. |

**Missing-data convention.** Most value-based primitives **skip** (emit *no* check) when the
field they read is absent or unusable — they never manufacture a failure out of missing
data. *Presence* is a separate concern, expressed by the presence/cardinality primitives
(§3.4), which always emit a check. Each primitive's entry below notes whether it skips.

---

## 3. Primitive catalogue

23 kinds. The `kind` string is the JSON discriminator; the dataclass lives in
`rules/definition.py` (except the two Tier-3 hatches, which custom types can't serialize).

### 3.1 Equality & comparison

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `equality` | `EqualityRuleDef` | Field equals a literal or another field. `match_mode`: `exact` / `normalized` (case/trim/whitespace/accent toggles) / `regex` (full-match) / `fuzzy` (`difflib` ratio ≥ `fuzzy_threshold`). `negate` flips it. Skips on absent. |
| `set_membership` | `SetMembershipRuleDef` | Value ∈ an allowed list (exact-ci or substring-ci), literal or settings-sourced. |
| `threshold` | `ThresholdCompareRuleDef` | Numeric field `lte`/`gte`/`lt`/`gt` a threshold (literal or settings-sourced). Skips on absent/non-numeric. |
| `numeric_range` | `NumericRangeRuleDef` | `min ≤ value ≤ max` (either bound optional; ≥1 required). Skips on absent. |
| `percentage_tolerance` | `PercentageToleranceRuleDef` | `|value − reference| / |reference| ≤ pct` between two fields. Skips on absent or `reference == 0`. |

### 3.2 Arithmetic & aggregation

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `arithmetic` | `ArithmeticIdentityRuleDef` | `result == addend_a + addend_b` within a tolerance. Skips if any operand absent/non-numeric. |
| `aggregate` | `AggregateRuleDef` | `sum`/`count`/`min`/`max`/`avg` of a list field (optionally digging a `sub_field` from list-composite rows) compared (`eq` with tolerance, or `lte`/`gte`/`lt`/`gt`) against a value or another field. The canonical *total == Σ line_items.amount* check. |
| `expression` | `ExpressionRuleDef` | A sandboxed author-written formula that must evaluate truthy. See [§4](#4-the-expression-dsl). |

### 3.3 Dates

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `date_constraint` | `DateConstraintRuleDef` | Any of: `not_future`, `min`/`max` (ISO literals), `before_field_path`/`after_field_path` (ordering). All configured constraints must hold. Dates parsed best-effort (`base.as_date`); skips on unparseable input. |

### 3.4 Presence, dependency & cardinality (always emit a check)

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `presence` | `PresenceRuleDef` | The field carries a real value. |
| `field_dependency` | `FieldDependencyRuleDef` | If `antecedent` present then `consequent` required (implication). |
| `conditional_presence` | `ConditionalPresenceRuleDef` | If `condition_field` present (and, when set, `== equals`) then `required_field` must be present. Vacuously passes otherwise. |
| `mutual_exclusivity` | `MutualExclusivityRuleDef` | Of `field_paths`, `exactly_one` or `at_most_one` present. |
| `at_least_n_of` | `AtLeastNOfRuleDef` | At least `n` of `field_paths` present. |
| `required_together` | `RequiredTogetherRuleDef` | All-or-nothing: if any of `field_paths` present, all must be. |

### 3.5 Format & checksum

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `format` | `FormatRuleDef` | Field matches a canned validator: `iban` (mod-97), `luhn` (mod-10 checksum), `email`, `url`, `uuid`, `iso_country` (ISO 3166-1 alpha-2), `iso_currency` (ISO 4217 alpha-3), `digits`, `alphanumeric`. Best-effort structural checks (`rules/formats.py`), not registry lookups. Skips on absent. |

### 3.6 Text & semantic

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `contains` | `ContainsRuleDef` | Field text contains `any`/`all` of a keyword list (case-insensitive toggle). Skips on absent. |
| `length_bounds` | `LengthBoundsRuleDef` | Field string length within `[min_length, max_length]` (either optional; ≥1 required). Skips on absent. |
| `llm_advisory` | `LlmAdvisoryRuleDef` | A yes/no LLM judgment, **structurally capped at `review`** (a soft opinion can never hard-flag). Tier-3; degrades to a passing advisory if the model is unavailable. |

### 3.7 Confidence, provenance & signature

| `kind` | Dataclass | What it checks |
| --- | --- | --- |
| `field_confidence_floor` | `FieldConfidenceFloorRuleDef` | The field's per-field extraction confidence ≥ `floor` (the document-wide confidence gate exists separately). Skips when the field node is absent. |
| `grounded_on_page` | `GroundedOnPageRuleDef` | The field is grounded to a source page (has a grounding with a `page`), not just a value — fights hallucinated fields. A present-but-ungrounded field **fails**; an absent field skips. |
| `signature_presence` | `SignaturePresenceRuleDef` | At least `min_count` detected signatures in a `kind="signature"` list field (the YOLOv8 post-pass output). Empty list ⇒ count 0 (fails); absent field skips. |
| `uniqueness` | `UniquenessVsHistoryRuleDef` | Value not seen on a prior decided document (e.g. invoice number vs history). |

### 3.8 Tier-3 escape hatches (built-in types only)

| `kind` | Dataclass | Notes |
| --- | --- | --- |
| *(none)* | `CodedRuleDef` | A hand-written `(fields, ctx) -> Check | None`. **Not serializable** — stripped on the way to JSON, so custom types can never carry it. |
| `llm_advisory` | `LlmAdvisoryRuleDef` | Serializable; usable by custom types (see §3.6). |

---

## 4. The expression DSL

`ExpressionRuleDef` (`kind: "expression"`) lets an author write a small formula that must
evaluate truthy. It is the general escape valve for checks no dedicated primitive covers.

```
gross == net + tax
abs(total - sum_of("line_items", "amount")) <= 0.01
end_date > start_date
days_between(today(), doc_date) <= 90
is_present("iban") and matches(iban, "GB[0-9A-Z]+")
value in ["EUR", "USD"]
```

**Field access.** A bare name resolves to that field's value (`fval`). List fields are
reachable *only* through helper functions (never as raw objects), and `field("a.b")` reads a
dotted path (composite sub-fields).

**Helpers.** `sum_of` · `min_of` · `max_of` · `avg_of` · `count` (over a list field, with an
optional row `sub_field`) · `abs` · `round` · `len` (string length) · `lower` / `upper` /
`trim` · `matches(value, "regex")` · `days_between(a, b)` · `today()` · `to_date(x)` ·
`is_present("path")` · `field("path")`.

**Safety model** (`rules/expression.py`). The formula is parsed with `ast.parse` and walked
against a **default-deny node whitelist** — only constants, names, boolean/arithmetic/
comparison ops, and calls to the fixed helper table are allowed. `Attribute` and `Subscript`
are rejected, so the classic sandbox-escape gadget chains
(`().__class__.__bases__[0].__subclasses__()`, `x.__globals__`, …) are **unparseable**, not
merely blocked. `Pow`/`FloorDiv` are excluded (DoS), leading-underscore names are rejected,
and there are caps on expression length / node count / depth. The runtime **re-parses and
re-whitelists on every call** (it never trusts that save-time validation ran) and is wrapped
fail-soft so an evaluator bug can never reach the decision pipeline. A bad formula is
rejected at authoring time (422) by `validate_expression`; a runtime failure (missing field,
type error) **skips** rather than crashes.

---

## 5. Adding a new primitive

A new rule kind touches five places (mirror the nearest existing primitive):

1. **`backend/app/rules/definition.py`** — add the `@dataclass`, a branch in `_interpret()`
   (return `None` to skip), and add it to the `RuleDef` union + `__all__`.
2. **`backend/app/serialization.py`** — add the `_KIND_MAP` entry (kind string ↔ dataclass;
   `_BUILDER_MAP`/`_VALID_RULE_KINDS` derive automatically) and a branch in
   `validate_custom_rule_dict` for save-time validation. Note: only keys ending in `_path`
   are auto-checked against declared fields — a list field like `field_paths` or a row-level
   `sub_field` must be validated (or deliberately not) by hand.
3. **`src/lib/doc-type-schema.ts`** — add the interface + extend `RuleKind`/`RuleDef`.
4. **`src/features/doctypes/RuleListEditor.tsx`** — add the `RULE_KINDS` entry, a `blankRule`
   default, and a `RuleParams` form case (use only components already imported).
5. **Tests** — `backend/tests/test_rules_definition.py` (interpreter: pass/fail/skip),
   `backend/tests/test_serialization.py` (round-trip + validation rejections), and the
   evaluator's `test_rules_expression.py` / `test_rules_formats.py` if you touch those.

The **Create-with-AI wizard needs no change** — its prompt catalogue is generated from
`_KIND_MAP` + the dataclasses (`pipeline/doctype_schema_reference.py`), so a new primitive
appears automatically. `backend/tests/test_doctype_schema_reference.py` is the drift guard;
it fails if a kind is missing from the generated reference. (Do **not** hand-edit the kind
list into the wizard's system prompt.)

**Conventions to keep:** custom types never carry code; skip (don't fail) on missing data
unless the primitive is presence-shaped; reject non-numeric literals at validation time
(remember `bool` is an `int` subclass — check it first); leave the built-in invoice/contract
rule definitions untouched (their parity tests assert exact check-name sets).

---

## 6. Cross-document validations (not yet built)

Every primitive above is **single-document**. The **bundle** substrate they'd build on now
exists: multi-document **Cases** ship, and the case decision engine already runs cross-document
**conflict** (sources disagree → `needs_review`) and **completeness** checks in code
(`backend/app/case_decision.py`; see [multi-document-cases.md](./multi-document-cases.md)).
What's still not built is exposing cross-document checks — same value/date across a set,
bundle completeness, cross-references, same-signatory *matching* — as **configurable rule
primitives** authorable like the single-document kinds above (the planned
`CrossDocConsistencyRuleDef` / `BundleCompletenessRuleDef`). See
[VALIDATION-BRAINSTORM.md §0, §3, §9](./VALIDATION-BRAINSTORM.md) for the design.


---

📚 **Docs:** [Index](./README.md) · [Architecture](./ARCHITECTURE.md) · [API](./API.md) · [Roadmap](./ROADMAP.md) · **Validation rules** · [Large-doc extraction](./large-document-extraction.md) · [Signatures](./signature-extraction.md) · [Validation brainstorm](./VALIDATION-BRAINSTORM.md) · [↑ Root README](../README.md)
