# Large-document extraction accuracy

How the structuring stage extracts the right fields from the right places in a **long,
multi-page document** — instead of flattening every page into one window and hoping the
extractor and its blind sliding window find each field. Three layered changes, all inside
`backend/app/pipeline/structuring.py` + `extraction/base.py`, none of which disturb the
single-page / mock / spreadsheet paths.

> Context: the base structuring stage (providers, table-feeding, corrections) is in
> [ARCHITECTURE.md §4](./ARCHITECTURE.md#4-structuring). This doc covers the accuracy work
> layered on top. For the image-region path (signatures) see
> [signature-extraction.md](./signature-extraction.md).

---

## The problem

The original stage concatenated **all** pages' text into one blob, ran LangExtract's fixed
sliding window over it once, and grounded each extracted value with `str.find` (first match).
On a 1-page invoice that's fine. On a 30-page contract it breaks two ways:

1. **Grounding mis-anchors.** A token like `Total`, a date, or a vendor name recurs on many
   pages; first-match `str.find` snaps the field to page 1, giving the wrong citation page and
   the wrong OCR-confidence multiplier.
2. **The extractor has no localisation.** A blind 8 KB window must find each field in a huge
   haystack; recall drops on the fields that live deep in the document.

The fixes below address each, plus the two edge cases they surface.

---

## 1. Proximity-aware grounding

`_ground()` / `_find_nearest()` in `extraction/base.py`.

LangExtract returns a **full-document-global** char offset for every extraction (verified: both
exact and fuzzy alignments carry a global `char_interval`). So instead of trusting only exact
offset quotes and otherwise falling back to the *first* `str.find`, `_ground` re-anchors to the
occurrence **nearest the provider's hint**:

```python
_find_nearest(text, full_text, hint)   # occurrence minimising (abs(start-hint), start)
```

- With a hint → the nearest occurrence (ties broken toward the earlier offset); a re-anchored
  match reports `alignment="partial"`.
- No hint (the offline `mock` provider) → first match, `alignment="exact"` — today's behaviour,
  unchanged.

Crucially, `_ground` treats its `full_text`/`char_start` as **relative to whatever text the
caller supplies** — it never assumes the whole document. That's what makes section-local
grounding (below) a drop-in.

On the frontend, `normalizeForMatch` (`src/lib/grounding.ts`) was reordered so markdown
scaffolding (`|` pipes, `--`+ runs) is stripped **before** the final whitespace-collapse — so a
table-row snippet re-anchors onto its value cells while real identifiers (`PO-9911`,
`#INV-3337`) are preserved.

## 2. Section-aware extraction

`run_structuring` no longer flattens. For the `langextract` provider it partitions the document
into **sections**, extracts each against its own grounded substrate, and merges:

```
run_structuring (langextract)
  → _build_sections(ocr_result, struct_text, page_offsets)   # partition
  → for each section:
        GroundingCtx(full_text=section.text, page_offsets=section.page_offsets)  # REAL page nums
        _structure_langextract(spec, section.text)
        spec.assemble(sec_flats, section_ctx)                # unchanged assembler, per section
  → _merge_section_fields(models, dedup_fields=spec.dedup_fields)
  → _apply_grounding_fallback(fields_model, ctx)             # §4
```

**Section sources** are the structure the OCR engine *already* emits — no new dependency, no
tree-building LLM call:

| Engine | Section boundary |
|---|---|
| `docling` | `OCRBlock.label ∈ {section_header, title}` (excludes `page_header`/`page_footer`; unknown labels degrade to "no heading") |
| VLM (markdown) | `^#{1,6}\s` heading lines in `page.text` |
| `spreadsheet` / `mock` | never sectioned (bypass) |

**Merge** (`_merge_section_fields`, dispatches on the Python value shape, so no
`definition.py` coupling): a scalar `FieldValue` takes the first section (document order) that
grounded it; a list concatenates; a composite is selected **whole** from the first grounded
section (never merged per sub-field — that would graft one clause's attribute onto another's
span). A single section makes the merge a no-op.

**Why this is the accuracy win, not just a refactor:** section-aligned chunking never splits a
heading's content across two disjoint sliding-window calls, and grounding a value within one
section collapses the repeated-token ambiguity that broke first-match `str.find`. On the
sample contract it surfaced two parties from the signature block the flat path missed.

## 3. Cross-section list dedup

Sectioning can extract the *same* entity from two sections — e.g. a contract's `parties` from
both the intro (`Acme Robotics Inc.`) and the signature block (`ACME ROBOTICS INC. (Provider)`).
Blanket dedup would be wrong (`line_items` legitimately repeats), so dedup is **opt-in per
field**:

- `FieldDef(dedup=True)` → surfaced as `DocTypeSpec.dedup_fields` by `build_spec` (mirrors
  `signature_fields`). Enabled for contract `parties` and `key_dates`; **off** for `line_items`.
- `_dedup_list_scalar` collapses list items whose **normalized** value repeats, keeping the
  first in document order (with its grounding). Normalization = casefold → strip trailing role
  parenthetical `(Provider)`/`(Customer)` → strip punctuation → collapse whitespace. **Exact
  match after normalization only — never fuzzy.** Composite rows and non-string items pass
  through untouched (a defensive no-op if `dedup=True` is ever set on a `list_composite`).

## 4. Whole-document grounding fallback

Section-local grounding is tighter, but a value whose verbatim span **spilled into a neighbour
section** can come back anchored to nothing (`governing_law` in the sample). After merge,
`_apply_grounding_fallback` re-grounds any **unanchored text leaf** against the whole document:

```python
# "unanchored" = grounding is None OR grounding.char_start is None
#   (ground_field ALWAYS returns a Grounding object; an unfound span has char_start=None,
#    alignment="ungrounded" — so the guard checks char_start, not just `is None`)
_reground_leaf(fv, ctx)   # ctx == the whole-document GroundingCtx already built in run_structuring
```

- Only **text** values are attempted (`isinstance(fv.value, str)`) — a presence field's `False`
  or a number's stringified value could coincidentally match unrelated text, so those never
  enter the fallback.
- Section-local grounding **always wins**: only an unanchored leaf is touched, and only if the
  whole-doc attempt actually finds it. On any path where `ctx` is the same substrate the leaf
  already failed against (mock / single-section), the retry is a no-op — so the pass is safe to
  call unconditionally.

Net effect: a field is grounded section-locally when possible, whole-document as a fallback —
never worse than the old flat path. On the sample this took overall extraction confidence from
85 % to 100 % (the recovered field stops dragging the mean).

---

## Configuration (`backend/app/config.py`)

| setting | default | purpose |
|---|---|---|
| `structuring_sectioning` | `True` | master kill switch — `False` forces the single-blob path always |
| `structuring_max_char_buffer` | `8000` | LangExtract window **and** the "doc already fits one window → don't section" gate |
| `structuring_section_min_chars` | `500` | a raw section shorter than this coalesces into a neighbour |
| `structuring_max_sections` | `40` | circuit breaker — more candidate sections than this → whole-document fallback + a warning |
| `structuring_extraction_passes` | `2` | LangExtract passes (per section) |

**When does a doc actually split?** Only when it has ≥2 detected headings **and** its text
exceeds `structuring_max_char_buffer`. A small contract (a few KB) stays single-section — set
`STRUCTURING_MAX_CHAR_BUFFER=1000` to exercise sectioning on the sample docs. When a split
happens, `StructuredResult.warnings` carries `"document split into N sections for extraction"`.

## Backward compatibility

The `mock`, `spreadsheet`, header-less, and small-doc paths reproduce the pre-change output
**byte-for-byte** — proven by the pre-existing suite passing unchanged. `_build_sections` returns
a single section (reusing the caller's `struct_text`/`page_offsets` verbatim) for every gate, and
`_merge_section_fields([single])` / `_apply_grounding_fallback` on an already-grounded model are
genuine no-ops. Adding `dedup` to `FieldDef` and `dedup_fields` to `DocTypeSpec` is additive +
defaulted (`build_spec` is the only construction site), and `serialization.dict_to_extraction_defn`
round-trips the new key (defaulting `False`) so custom DB types load cleanly.

## Testing

`backend/tests/test_sectioning.py` (offline, no network) covers heading detection, every
`_build_sections` gate, the merge tie-breaks (scalar / list / composite atomic + the
missing-attribute Frankenstein guard), dedup (collapse + opt-in-off + composite no-op +
normalization negatives), and the grounding fallback (recovers a genuinely-unanchored text leaf;
leaves anchored / presence / numeric / missing leaves untouched). `test_grounding.py` covers the
proximity anchoring. `test_extraction_definition.py` asserts `dedup_fields == {parties, key_dates}`
for contract and `[]` for invoice.

## Dev-server note

Running the backend for a real (non-mock) pipeline needs the optional extras and a reload config
that ignores the pipeline's own writes:

```bash
uv sync --extra ocr --extra langextract --extra agent --extra signatures   # once
# the Makefile dev/dev-backend targets now use:
uv run --no-sync uvicorn app.main:app --reload --reload-dir app --port 8000
```

`--no-sync` stops `uv run` re-syncing away the extras; `--reload-dir app` stops WatchFiles
reloading mid-run when the pipeline writes to `backend/data`.

## Known follow-ups

- `_merge_field`'s scalar tie-break uses `grounding is not None`, which (same object-always-non-None
  subtlety as §4) prefers the first section that *extracted* a value over the first that *anchored*
  it. Largely masked by the §4 fallback; a small fix would prefer an anchored section.
- Section overlap (a few chars of neighbour context) would improve extraction recall on
  boundary-straddling fields, at the cost of offset/page-mapping complexity.
- Surface the `"document split into N sections"` warning in the inspector UI
  (`StructuredResult.warnings` is not rendered today).
- Benchmark the page-count / structure crossover where sectioning beats the flat path.
- Cross-page consistency rules (line-items-sum-to-total across pages, date monotonicity) — see
  the [validation backlog](./validation-rules.md).
