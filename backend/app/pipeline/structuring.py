"""Phase 4 structuring stage: OCR text -> validated, grounded, approval-relevant JSON.

Two providers behind one entrypoint, mirroring the OCR layer's discipline:

* ``langextract`` — LangExtract pointed at OpenRouter (OpenAI-compatible). Imported
  lazily so the app boots and tests run without the optional dep.
* ``mock`` — deterministic, offline; its spans are located in the real OCR
  ``full_text`` so grounding + page mapping are genuinely exercised in tests.

Source grounding, per-field + overall confidence (with OCR confidence propagated),
and a documented Docling-table fallback live here; the per-doc-type taxonomy and
assembly live in ``app/extraction``.
"""

from __future__ import annotations

import bisect
import dataclasses
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from time import perf_counter

from pydantic import BaseModel

from app.config import settings
from app.extraction import get_extraction_definition, get_spec
from app.extraction.base import FlatExtraction, GroundingCtx, ground_field
from app.extraction.definition import _augment_examples_factory, build_correction_examples
from app.models import Document, DocumentStatus
from app.schemas import (
    FieldCorrection,
    FieldValue,
    Grounding,
    OCRPage,
    OCRResult,
    OCRTable,
    StructuredResult,
)
from app import storage

PROVIDERS = {"langextract", "mock"}


def run_structuring(
    doc: Document,
    ocr_result: OCRResult,
    doc_type: str,
    provider: str = "",
    corrections: list[FieldCorrection] | None = None,
) -> StructuredResult:
    """Structure a document's OCR text into a validated, grounded result."""
    provider = provider or settings.structuring_provider
    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown structuring provider '{provider}'. Available: {', '.join(sorted(PROVIDERS))}"
        )

    spec = get_spec(doc_type)
    # Active-learning loop: fold a doc type's past reviewer corrections into the
    # few-shot examples so the extractor stops repeating the same mistakes. NO-OP for
    # the mock provider, an empty correction list, or the disabled flag — in every one
    # of those cases ``spec`` stays byte-identical to today's.
    if provider != "mock" and settings.few_shot_corrections_enabled and corrections:
        defn = get_extraction_definition(doc_type)
        examples = build_correction_examples(corrections, defn, settings.few_shot_max_examples)
        if examples:
            spec = dataclasses.replace(
                spec,
                examples_factory=_augment_examples_factory(spec.examples_factory, examples),
            )
    # Feed the extractor the page text PLUS each page's table markdown: OCR engines
    # (Docling especially) keep tables out of ``full_text``, so invoice numbers,
    # dates and totals live only in the tables. Grounding uses the same augmented
    # text + matching page offsets so spans still map back to their page.
    struct_text, page_offsets = _build_structuring_text(ocr_result)
    ctx = GroundingCtx(
        full_text=struct_text, ocr_result=ocr_result, page_offsets=page_offsets
    )

    start = perf_counter()
    if provider == "mock":
        # Mock stays single-blob: deterministic offline coverage never sections.
        flats = _structure_mock(doc_type, struct_text)
        fields_model = spec.assemble(flats, ctx)
        artifact: str | None = None
        model = "mock"
    else:
        # Section-aware extraction: partition the document into heading-delimited
        # sections and extract each against its own grounded substrate, then merge.
        # A single section (small / header-less / spreadsheet / kill-switched doc)
        # reproduces today's whole-document call byte-for-byte.
        sections, section_warning = _build_sections(ocr_result, struct_text, page_offsets)
        if len(sections) == 1:
            flats, artifact = _structure_langextract(spec, struct_text)
            fields_model = spec.assemble(flats, ctx)
        else:
            models: list = []
            all_flats: list[FlatExtraction] = []
            for section in sections:
                section_ctx = GroundingCtx(
                    full_text=section.text,
                    ocr_result=ocr_result,
                    page_offsets=section.page_offsets,
                )
                sec_flats, _ = _structure_langextract(spec, section.text)
                models.append(spec.assemble(sec_flats, section_ctx))
                ctx.warnings.extend(section_ctx.warnings)
                all_flats.extend(sec_flats)
            fields_model = _merge_section_fields(models, dedup_fields=set(spec.dedup_fields))
            artifact = _artifact_jsonl(all_flats)
            ctx.warnings.append(
                f"document split into {len(sections)} sections for extraction"
            )
        if section_warning is not None:
            ctx.warnings.append(section_warning)
        model = settings.structuring_model
    latency_ms = int((perf_counter() - start) * 1000)

    # Recovery pass: re-ground any ungrounded text leaf against the WHOLE document (the
    # ``ctx`` built above). Mutates ``fields_model`` in place; a no-op outside the
    # sectioned case whose section-local substrate could miss a spilled span.
    _apply_grounding_fallback(fields_model, ctx)

    # Optional fallback: backfill missing core fields from persisted Docling tables.
    fields_model, fallback_used = _backfill_from_tables(fields_model, ocr_result, doc_type, ctx)

    # Optional spatial post-pass: detect + crop signatures for any signature field.
    fields_model, _ = _detect_signatures(fields_model, spec, doc, ocr_result, ctx)

    fields = fields_model.model_dump(mode="json")
    extraction_confidence = _overall_confidence(fields, spec.core_paths)
    grounding_map = _flatten_grounding(fields)

    warnings = list(ctx.warnings)
    if ocr_result.avg_confidence is None:
        warnings.append(
            f"OCR engine '{ocr_result.engine_name}' exposes no confidence; "
            "field confidence is alignment-only"
        )
    if extraction_confidence < settings.extraction_confidence_warn:
        warnings.append(f"low overall extraction confidence ({extraction_confidence:.2f})")

    raw_artifact_url: str | None = None
    if artifact is not None:
        storage.save_structure_artifact(doc.id, artifact)
        raw_artifact_url = storage.structure_artifact_url(doc.id)

    return StructuredResult(
        document_id=doc.id,
        status=DocumentStatus.structured,
        doc_type=doc_type,
        provider=provider,
        model=model,
        ocr_engine=ocr_result.engine_name,
        fields=fields,
        extraction_confidence=extraction_confidence,
        grounding_map=grounding_map,
        warnings=warnings,
        latency_ms=latency_ms,
        fallback_used=fallback_used,
        raw_artifact_url=raw_artifact_url,
    )


# --- providers ----------------------------------------------------------------


def _build_structuring_text(
    ocr_result: OCRResult,
) -> tuple[str, list[tuple[int, int]]]:
    """Augment each page's text with its table markdown, returning (text, offsets).

    Mirrors ``build_page_offsets`` (pages joined by ``"\\n\\n"``, +2 per joiner) but
    on the augmented per-page text, so a span's char offset still maps to its page.
    A page with no tables reproduces ``page.text`` exactly, so this is a no-op for
    engines/text that carry no tables (e.g. the mock provider).
    """
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page in ocr_result.pages:
        text = page.text
        tables_md = [t.markdown for t in page.tables if t.markdown]
        if tables_md:
            text = f"{text}\n\n" + "\n\n".join(tables_md)
        offsets.append((page.page, cursor))
        parts.append(text)
        cursor += len(text) + 2  # +2 for the "\n\n" page joiner
    return "\n\n".join(parts), offsets


# --- section-aware extraction --------------------------------------------------
#
# Instead of flattening every page into one window before extraction, partition the
# document into SECTIONS along the headings the OCR engine already emits, run the
# spec's ``assemble`` once per section against a section-scoped ``GroundingCtx``, then
# merge the per-section field models. Small / mock / spreadsheet / header-less docs
# fall back to the single-blob path, byte-for-byte. Grounding is substrate-relative
# (see ``extraction/base._ground``), so a section's local text + local offsets ground
# exactly as the whole document would. Guiding principle: accuracy over cost.

# Docling heading labels that open a new section. Running headers/footers
# (``page_header``/``page_footer``) are deliberately excluded — they are not section
# starts. Any label outside this set is a non-heading, so an unknown/renamed label
# simply yields "no heading" -> safe single-section fallback.
_HEADING_LABELS = {"section_header", "title"}

# A markdown ATX heading line (``# ``..``###### ``) for engines whose page text is raw
# markdown (VLMs emit one block/page labelled ``text`` but ``page.text`` carries ``#``).
_MD_HEADING = re.compile(r"^#{1,6}\s+")

# Cross-section list dedup (opt-in per ``FieldDef.dedup``). ``_TRAILING_ROLE_PAREN``
# strips a trailing role annotation like `` (Provider)`` a party name may carry in one
# section but not another; ``_DEDUP_PUNCTUATION`` strips remaining punctuation so
# `"Acme Robotics Inc."` and `"ACME ROBOTICS INC. (Provider)"` collapse to one key.
_TRAILING_ROLE_PAREN = re.compile(r"\s*\([^)]*\)\s*$")
_DEDUP_PUNCTUATION = re.compile(r"[^\w\s]")


@dataclass
class Section:
    """One contiguous slice of a document, ready to extract on its own.

    ``pages`` is the inclusive ``(first, last)`` REAL page range the slice spans.
    ``text`` is the section-local substrate handed to the extractor and used for
    grounding; ``page_offsets`` maps each REAL page number to its start offset WITHIN
    ``text`` (``char_to_page`` only needs ascending cursors, so real page numbers work
    directly as keys). Tables are not carried here — they are folded into ``text`` by
    ``_join_section_text`` and also handled document-wide by ``_backfill_from_tables``.
    """

    title: str | None
    pages: tuple[int, int]
    text: str
    page_offsets: list[tuple[int, int]]


def _join_section_text(
    page_units: list[tuple[int, list[str]]],
    page_tables: dict[int, list[OCRTable]],
) -> tuple[str, list[tuple[int, int]]]:
    """Join a section's per-page units + tables, mirroring ``_build_structuring_text``.

    ``page_units`` is ``[(real_page_no, [unit_text, ...]), ...]`` in document order;
    ``page_tables`` maps a real page number to the tables folded onto it. The exact
    conventions of ``_build_structuring_text`` are reproduced so a section's substrate
    is consistent with the whole-document one: units within a page joined by ``"\\n"``,
    a page's non-empty table markdown appended after ``"\\n\\n"`` then joined by
    ``"\\n\\n"``, and pages joined by ``"\\n\\n"`` (so the offset cursor advances by +2
    per page joiner). This is the single place section offset arithmetic lives, and the
    returned ``page_offsets`` keys are the REAL page numbers.
    """
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page_no, units in page_units:
        text = "\n".join(units)
        tables_md = [t.markdown for t in page_tables.get(page_no, []) if t.markdown]
        if tables_md:
            text = f"{text}\n\n" + "\n\n".join(tables_md)
        offsets.append((page_no, cursor))
        parts.append(text)
        cursor += len(text) + 2  # +2 for the "\n\n" page joiner
    return "\n\n".join(parts), offsets


def _detect_docling_headings(ocr_result: OCRResult) -> list[tuple[int, int, str | None]]:
    """Boundaries from Docling block labels: ``(page_no, block_index, title)``.

    Walks each page's blocks in document order; a boundary opens at every block whose
    ``label`` is a heading (:data:`_HEADING_LABELS`). When the document begins with
    non-heading content, an implicit doc-start boundary (``title=None``) is emitted for
    the leading preamble; when it begins with a heading, that heading is the first
    boundary. ``title`` is the heading block's verbatim text (``None`` for the implicit
    doc-start). Returns fewer than two entries when there is nothing worth splitting.
    """
    boundaries: list[tuple[int, int, str | None]] = []
    at_start = True
    for page in ocr_result.pages:
        for idx, block in enumerate(page.blocks):
            first = at_start
            at_start = False
            if block.label in _HEADING_LABELS:
                boundaries.append((page.page, idx, block.text))
            elif first:
                boundaries.append((page.page, idx, None))  # leading preamble
    return boundaries


def _detect_markdown_headings(ocr_result: OCRResult) -> list[tuple[int, int, str | None]]:
    """Boundaries from ``#`` heading lines: ``(page_no, line_index, title)``.

    For engines whose ``page.text`` is raw markdown (VLMs). Splits each page's text on
    ``"\\n"`` and opens a boundary at every line matching :data:`_MD_HEADING`; the
    ``title`` is the heading text with its ``#`` markers stripped. As in the Docling
    detector, a document that starts with non-heading content emits an implicit
    doc-start boundary (``title=None``) for the leading preamble.
    """
    boundaries: list[tuple[int, int, str | None]] = []
    at_start = True
    for page in ocr_result.pages:
        for idx, line in enumerate(page.text.split("\n")):
            first = at_start
            at_start = False
            if _MD_HEADING.match(line):
                boundaries.append((page.page, idx, line.lstrip("#").strip()))
            elif first:
                boundaries.append((page.page, idx, None))  # leading preamble
    return boundaries


def _detect_headings(ocr_result: OCRResult) -> list[tuple[int, int, str | None]]:
    """Dispatch heading detection on the OCR engine that produced ``ocr_result``.

    Docling exposes structural labels; spreadsheets have no prose to section (their
    content lives in tables) so they never split; everything else (VLMs) is treated as
    markdown text.
    """
    if ocr_result.engine_name == "docling":
        return _detect_docling_headings(ocr_result)
    if ocr_result.engine_name == "spreadsheet":
        return []
    return _detect_markdown_headings(ocr_result)


def _docling_units(ocr_result: OCRResult) -> tuple[list[tuple[int, str]], dict[int, int]]:
    """Flatten Docling blocks into ``[(page_no, block_text), ...]`` + per-page starts.

    The returned ``page_starts`` maps each page to the flat index of its first block
    (recorded even for a block-less page, so a page that carries only tables still has
    an anchor for folding). Boundaries reference ``page_starts[page] + block_index``.
    """
    order: list[tuple[int, str]] = []
    page_starts: dict[int, int] = {}
    for page in ocr_result.pages:
        page_starts[page.page] = len(order)
        for block in page.blocks:
            order.append((page.page, block.text))
    return order, page_starts


def _markdown_units(ocr_result: OCRResult) -> tuple[list[tuple[int, str]], dict[int, int]]:
    """Flatten markdown page text into ``[(page_no, line), ...]`` + per-page starts.

    Mirrors :func:`_docling_units` but at line granularity, so a markdown section owns a
    contiguous line sub-range. ``page.text.split("\\n")`` round-trips through
    ``"\\n".join`` so a section covering all of a page reproduces ``page.text`` exactly.
    """
    order: list[tuple[int, str]] = []
    page_starts: dict[int, int] = {}
    for page in ocr_result.pages:
        page_starts[page.page] = len(order)
        for line in page.text.split("\n"):
            order.append((page.page, line))
    return order, page_starts


def _partition_sections(
    pages: list[OCRPage],
    order: list[tuple[int, str]],
    page_starts: dict[int, int],
    boundaries: list[tuple[int, int, str | None]],
) -> list[Section]:
    """Cut the flat unit stream into :class:`Section`s at the detected boundaries.

    Each boundary owns the contiguous unit sub-range up to the next boundary. Units are
    regrouped per page (preserving order) and each section's text/offsets are built via
    :func:`_join_section_text`. A page's tables are folded into whichever section covers
    the START of that page (the section active at the page's first unit), matching the
    document-wide table conventions of ``_build_structuring_text``.
    """
    bpos = [page_starts.get(pno, 0) + off for (pno, off, _t) in boundaries]

    def section_of(pos: int) -> int:
        # bpos is ascending (boundaries are in document order); the owning section is
        # the last boundary at or before pos.
        return max(0, bisect.bisect_right(bpos, pos) - 1)

    n = len(boundaries)
    units: list[dict[int, list[str]]] = [dict() for _ in range(n)]
    page_order: list[list[int]] = [[] for _ in range(n)]
    tables: list[dict[int, list[OCRTable]]] = [dict() for _ in range(n)]

    def _touch(sec: int, page_no: int) -> None:
        if page_no not in units[sec]:
            units[sec][page_no] = []
            page_order[sec].append(page_no)

    for pos, (page_no, unit) in enumerate(order):
        sec = section_of(pos)
        _touch(sec, page_no)
        units[sec][page_no].append(unit)

    for page in pages:
        if not any(t.markdown for t in page.tables):
            continue
        anchor = page_starts.get(page.page)
        if anchor is None:  # pragma: no cover - every page is recorded in page_starts
            continue
        sec = section_of(anchor)
        _touch(sec, page.page)  # ensure the page shows up even if it has no units here
        tables[sec][page.page] = page.tables

    sections: list[Section] = []
    for i in range(n):
        page_units = [(pno, units[i][pno]) for pno in page_order[i]]
        text, offsets = _join_section_text(page_units, tables[i])
        pnos = [pno for pno, _ in page_units]
        page_range = (min(pnos), max(pnos)) if pnos else (pages[0].page, pages[0].page)
        sections.append(
            Section(title=boundaries[i][2], pages=page_range, text=text, page_offsets=offsets)
        )
    return sections


def _merge_two_sections(a: Section, b: Section) -> Section:
    """Fuse two adjacent sections, rebasing ``b``'s offsets past ``a``'s text.

    The joined text uses the same ``"\\n\\n"`` boundary as the page joiner, so
    ``char_to_page`` still sees ascending cursors over real page numbers. The surviving
    title is ``a``'s (the earlier slice), falling back to ``b``'s when ``a`` is the
    implicit preamble — titles are section metadata only and never reach ``assemble``.
    """
    shift = len(a.text) + 2  # +2 for the "\n\n" joiner
    text = f"{a.text}\n\n{b.text}"
    offsets = a.page_offsets + [(pno, off + shift) for pno, off in b.page_offsets]
    title = a.title if a.title is not None else b.title
    return Section(title=title, pages=(a.pages[0], b.pages[1]), text=text, page_offsets=offsets)


def _coalesce_sections(sections: list[Section]) -> list[Section]:
    """Fold each too-short raw section into a neighbor (forward, or back if last).

    A section whose text is shorter than ``structuring_section_min_chars`` is not worth
    its own extraction pass, so it is merged forward into the next section (or backward
    into the previous when it is the last). Runs to a fixed point so a chain of short
    slices collapses cleanly; a lone remaining section is returned untouched.
    """
    result = list(sections)
    i = 0
    while len(result) > 1 and i < len(result):
        if len(result[i].text) >= settings.structuring_section_min_chars:
            i += 1
            continue
        if i + 1 < len(result):
            result[i : i + 2] = [_merge_two_sections(result[i], result[i + 1])]
        else:  # the last section is too short -> merge backward
            result[i - 1 : i + 1] = [_merge_two_sections(result[i - 1], result[i])]
            i -= 1
    return result


def _build_sections(
    ocr_result: OCRResult, struct_text: str, page_offsets: list[tuple[int, int]]
) -> tuple[list[Section], str | None]:
    """Partition a document into sections, or fall back to one whole-document section.

    Returns ``(sections, warning)``. Exactly ONE section — reusing ``struct_text`` and
    ``page_offsets`` verbatim so output is byte-identical to the single-blob path — is
    returned when any gate holds: sectioning is switched off, the engine is a
    spreadsheet, fewer than two headings were detected, or the whole document already
    fits one extraction window (``<= structuring_max_char_buffer``). Otherwise the
    document is cut at the detected boundaries, short raw sections are coalesced into a
    neighbor, and — if that still leaves more than ``structuring_max_sections`` slices —
    the circuit breaker returns the single whole-document section plus a warning string
    (the second tuple element; ``None`` in every other case).
    """
    pages = ocr_result.pages
    first_page = pages[0].page if pages else 1
    last_page = pages[-1].page if pages else 1

    def _whole() -> list[Section]:
        return [
            Section(
                title=None,
                pages=(first_page, last_page),
                text=struct_text,
                page_offsets=page_offsets,
            )
        ]

    if not settings.structuring_sectioning:
        return _whole(), None
    if ocr_result.engine_name == "spreadsheet":
        return _whole(), None

    boundaries = _detect_headings(ocr_result)
    headings = [b for b in boundaries if b[2] is not None]
    if len(headings) < 2:
        return _whole(), None  # nothing to split
    if len(struct_text) <= settings.structuring_max_char_buffer:
        return _whole(), None  # already fits one window; skip even with headings

    if ocr_result.engine_name == "docling":
        order, page_starts = _docling_units(ocr_result)
    else:
        order, page_starts = _markdown_units(ocr_result)
    sections = _coalesce_sections(_partition_sections(pages, order, page_starts, boundaries))

    if len(sections) > settings.structuring_max_sections:
        warning = (
            f"section detection found {len(sections)} candidate sections "
            f"(> {settings.structuring_max_sections}); using whole-document extraction"
        )
        return _whole(), warning
    return sections, None


def _normalize_for_dedup(value: str) -> str:
    """Normalization key for exact-match list dedup — NEVER fuzzy/substring.

    Two items collapse only when this returns the SAME string. Order matters:
    (1) ``casefold`` for case-insensitivity; (2) strip a trailing role annotation like
    `` (Provider)`` (a party may carry a role in one section but not another); (3) strip
    remaining punctuation; (4) collapse internal whitespace. The paren-strip MUST precede
    the punctuation-strip: otherwise the ``(`` / ``)`` are gone first and the annotation
    text survives inside the key. As a side effect date separators are stripped too
    (``"2024-09-15" -> "20240915"``), which is harmless — dedup is exact-key only, so it
    still never conflates two distinct dates.

    ``"Acme Robotics Inc."`` and ``"ACME ROBOTICS INC. (Provider)"`` both normalize to
    ``"acme robotics inc"``; ``"Acme Robotics"`` normalizes to ``"acme robotics"`` — a
    DIFFERENT key, so a shorter prefix is never treated as a duplicate.
    """
    text = value.casefold()
    text = _TRAILING_ROLE_PAREN.sub("", text)
    text = _DEDUP_PUNCTUATION.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _dedup_list_scalar(items: list) -> list:
    """Collapse exact-normalized duplicate ``FieldValue`` items, keeping the FIRST.

    Keeps the first item per :func:`_normalize_for_dedup` key in document order, with its
    grounding/confidence untouched. DEFENSIVE: any element that is not a ``FieldValue``
    carrying a ``str`` value is passed through unchanged and does NOT seed the seen-set —
    so a misconfigured composite/non-text list degrades to a no-op rather than crashing or
    silently dropping rows (dedup is only ever opted into for ``kind="list_scalar"``).
    """
    seen: set[str] = set()
    out: list = []
    for item in items:
        if not (isinstance(item, FieldValue) and isinstance(item.value, str)):
            out.append(item)  # not a text leaf -> pass through, never dedup
            continue
        key = _normalize_for_dedup(item.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_section_fields(models: list, dedup_fields: set[str] | None = None) -> object:
    """Merge per-section field-model instances into one, dispatching on value shape.

    Generic over any ``DocTypeSpec.field_model`` instance (no ``definition.py`` coupling)
    by recursing on the Python value: a ``list`` field CONCATENATES items from every
    section in document order; a :class:`FieldValue` leaf takes the FIRST section whose
    ``grounding is not None`` (falling back to the first section's value when every
    section is ungrounded — ``grounding is None`` is the universal "found nothing"
    signal, so a ``presence`` field's absent ``FieldValue(value=False, grounding=None)``
    correctly loses to a later grounded ``True``); a nested ``BaseModel`` (a composite
    field) takes the FIRST section whose composite is grounded, WHOLE — sub-fields are
    never merged across sections (that would graft one clause's attribute onto another's
    span). A single model is returned unchanged so the single-section path is a no-op.

    ``dedup_fields`` names the list_scalar fields opted into cross-section dedup (from
    ``spec.dedup_fields``): after those fields concatenate, exact-normalized duplicate
    items are collapsed keeping the first (see :func:`_dedup_list_scalar`). Opt-in and
    off by default — a field not named here keeps every concatenated item.
    """
    if len(models) == 1:
        return models[0]
    dedup_fields = dedup_fields or set()
    template = models[0]
    merged = {
        name: _merge_field([getattr(m, name) for m in models], dedup=name in dedup_fields)
        for name in type(template).model_fields
    }
    return type(template)(**merged)


def _merge_field(values: list, dedup: bool = False):
    """Merge one field's value across sections per the :func:`_merge_section_fields` rules."""
    first = values[0]
    if isinstance(first, list):
        out: list = []
        for v in values:
            out.extend(v)
        return _dedup_list_scalar(out) if dedup else out
    if isinstance(first, FieldValue):
        for v in values:
            if v.grounding is not None:
                return v
        return first  # all sections ungrounded -> keep the first
    if isinstance(first, BaseModel):
        # Composite field (e.g. contract's termination_clause): pick the FIRST section
        # whose composite is grounded, WHOLE — never merge per sub-field. A composite's
        # sub-fields are populated atomically together (all share the parent span's
        # grounding) or all missing together, EXCEPT that a source="attribute" sub-field
        # the model omitted comes back as missing_field() (grounding=None) even when the
        # composite exists. Recursing per sub-field would then graft that attribute from a
        # different section's clause — a Frankenstein composite. So select atomically.
        for v in values:
            if any(
                getattr(getattr(v, name), "grounding", None) is not None
                for name in type(v).model_fields
            ):
                return v
        return first  # every section's composite is ungrounded -> keep the first
    return first  # pragma: no cover - field models are FieldValue/list/BaseModel only


# --- whole-document grounding fallback ---------------------------------------


def _apply_grounding_fallback(model: BaseModel, ctx: GroundingCtx) -> None:
    """Recovery pass: re-ground any ungrounded text leaf against the whole document.

    Section-aware extraction grounds each field against its own section's local
    substrate; a span whose context spilled into an adjacent section can come back
    with a value but ``grounding=None``. Walk the assembled field tree (scalar /
    composite / list_scalar / list_composite) and re-attempt ``ground_field`` against
    ``ctx`` — the WHOLE-DOCUMENT GroundingCtx. Mutates ``model`` in place. Section-local
    grounding always wins: only an UNANCHORED ``FieldValue`` (no grounding, or a
    ``Grounding`` whose ``char_start is None``) is touched, and only when the whole-doc
    attempt actually finds it. Safe to call on every path:
    re-finding a not-found span against the same substrate is a no-op, so this is
    idempotent outside the sectioned case it targets.
    """
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, FieldValue):
            setattr(model, name, _reground_leaf(value, ctx))
        elif isinstance(value, BaseModel):
            _apply_grounding_fallback(value, ctx)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, FieldValue):
                    value[i] = _reground_leaf(item, ctx)
                elif isinstance(item, BaseModel):
                    _apply_grounding_fallback(item, ctx)


def _reground_leaf(fv: FieldValue, ctx: GroundingCtx) -> FieldValue:
    """Whole-document grounding fallback for one leaf; unchanged unless it newly grounds.

    Only TEXT values (``isinstance(fv.value, str)``) currently ungrounded are attempted:
    a presence field's ``value=False`` or a numeric field's stringified value could
    coincidentally match unrelated text and attach a spurious grounding, so those are
    left untouched. Reuses ``ground_field`` (never reimplements ``_ground``) via a
    throwaway ``FlatExtraction`` from the coerced value.

    "Ungrounded" here means UNANCHORED, i.e. no ``Grounding`` at all OR a ``Grounding``
    whose ``char_start is None`` — because ``ground_field`` always returns a ``Grounding``
    object (an unfound span yields ``char_start=None, alignment="ungrounded"``), never
    Python ``None``. Guarding only on ``grounding is not None`` would skip exactly the
    section-spill case this pass exists to recover.
    """
    anchored = fv.grounding is not None and fv.grounding.char_start is not None
    if anchored or not isinstance(fv.value, str) or fv.value == "":
        return fv
    grounding, confidence = ground_field(FlatExtraction(cls="_fallback", text=fv.value), ctx)
    if grounding.char_start is None:  # whole-doc attempt also failed -> leave as-is
        return fv
    return fv.model_copy(update={"grounding": grounding, "confidence": confidence})


def _structure_langextract(spec, full_text: str) -> tuple[list[FlatExtraction], str]:
    """Run LangExtract against OpenRouter and normalize to FlatExtraction[]."""
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set; the langextract provider needs it.")

    import langextract as lx  # lazy: optional dep
    from langextract.factory import ModelConfig

    config = ModelConfig(
        model_id=settings.structuring_model,
        provider="openai",
        provider_kwargs={
            "api_key": settings.openrouter_api_key,
            "base_url": settings.structuring_base_url,
        },
    )
    annotated = lx.extract(
        text_or_documents=full_text,
        prompt_description=spec.prompt,
        examples=spec.examples_factory(),
        config=config,
        max_char_buffer=settings.structuring_max_char_buffer,
        extraction_passes=settings.structuring_extraction_passes,
    )

    flats: list[FlatExtraction] = []
    for e in annotated.extractions:
        interval = getattr(e, "char_interval", None)
        cs = getattr(interval, "start_pos", None) if interval is not None else None
        ce = getattr(interval, "end_pos", None) if interval is not None else None
        flats.append(
            FlatExtraction(
                cls=e.extraction_class,
                text=e.extraction_text or "",
                attributes=dict(getattr(e, "attributes", None) or {}),
                char_start=cs,
                char_end=ce,
            )
        )
    return flats, _artifact_jsonl(flats)


def _structure_mock(doc_type: str, full_text: str) -> list[FlatExtraction]:
    """Deterministic, offline extractions whose spans live in the mock OCR text.

    For invoices: grounds vendor/invoice_no/total/line_item against the real
    ``full_text`` (so page mapping runs for real), emits an intentionally ungrounded
    ``currency``, and OMITS ``po_number`` to prove the null + low-confidence path.

    The ``po`` and ``delivery_note`` branches emit values that AGREE with the invoice /
    contract happy path so a full four-document ap_match case reconciles cleanly offline:
    the PO's ``total`` / ``vendor`` mirror the invoice's ("$1,234.56" / "MOCK INVOICE") and
    it supplies the ``po_number`` the invoice omits; the delivery note carries plausible
    grounded values (it is a completeness-only member, so it feeds no canonical field).
    """
    if doc_type == "invoice":
        return [
            FlatExtraction(cls="vendor", text="MOCK INVOICE"),
            FlatExtraction(cls="invoice_no", text="page 1"),
            FlatExtraction(cls="total", text="$1,234.56"),
            FlatExtraction(cls="currency", text="USD"),  # absent in OCR text -> ungrounded
            FlatExtraction(
                cls="line_item",
                text="$1,234.56",
                attributes={
                    "desc": "Mock Widget",
                    "qty": "1",
                    "unit_price": "1234.56",
                    "amount": "1234.56",
                },
            ),
            # po_number deliberately omitted.
        ]
    if doc_type == "po":
        return [
            # A PO-shaped number the invoice branch omits, so the case's po_number canonical
            # field has exactly one non-null source (the PO) and trivially agrees.
            FlatExtraction(cls="po_number", text="PO-1001"),  # absent in OCR text -> ungrounded
            FlatExtraction(cls="vendor", text="MOCK INVOICE"),  # matches the invoice vendor
            FlatExtraction(cls="order_date", text="page 1"),
            FlatExtraction(cls="total", text="$1,234.56"),  # matches invoice total + contract value
            FlatExtraction(
                cls="line_item",
                text="$1,234.56",
                attributes={
                    "desc": "Mock Widget",
                    "qty": "1",
                    "unit_price": "1234.56",
                    "amount": "1234.56",
                },
            ),
        ]
    if doc_type == "delivery_note":
        return [
            FlatExtraction(cls="delivery_note_no", text="DN-1001"),  # absent in OCR text -> ungrounded
            FlatExtraction(cls="delivery_date", text="page 1"),
            FlatExtraction(cls="vendor", text="MOCK INVOICE"),  # matches the invoice vendor
            FlatExtraction(
                cls="line_item",
                text="$1,234.56",
                attributes={"desc": "Mock Widget", "qty": "1"},  # received quantity
            ),
        ]
    return [
        FlatExtraction(cls="party", text="MOCK INVOICE"),
        FlatExtraction(cls="effective_date", text="page 1"),
        # A deterministic monetary value grounded in the mock OCR text ("Total: $1,234.56"),
        # so an invoice/contract case can exercise a real total_amount reconciliation.
        FlatExtraction(cls="total_value", text="$1,234.56"),
    ]


# --- confidence + grounding aggregation --------------------------------------


def _is_field_value(node: object) -> bool:
    # Subset check (not exact): a FieldValue may also carry edit metadata
    # (``edited``/``original_value``) once a reviewer corrects it.
    return isinstance(node, dict) and {"value", "confidence", "grounding"} <= node.keys()


def _node_confidence(node: object) -> float | None:
    """Recursive confidence of a dumped field node (FieldValue / list / composite)."""
    if _is_field_value(node):
        return float(node["confidence"])  # type: ignore[index]
    if isinstance(node, list):
        vals = [c for c in (_node_confidence(x) for x in node) if c is not None]
        return sum(vals) / len(vals) if vals else 0.0  # empty list = missing -> drags down
    if isinstance(node, dict):
        vals = [c for c in (_node_confidence(v) for v in node.values()) if c is not None]
        return sum(vals) / len(vals) if vals else None
    return None


def _overall_confidence(fields: dict, core_paths: list[str]) -> float:
    """Mean confidence over the doc type's core fields (missing ones count as 0)."""
    confs: list[float] = []
    for path in core_paths:
        node = fields.get(path)
        c = _node_confidence(node)
        if c is not None:
            confs.append(c)
    return round(sum(confs) / len(confs), 4) if confs else 0.0


def _walk_leaves(fields: dict, prefix: str = "") -> Iterator[tuple[str, dict]]:
    """Yield ``(dotted_path, raw FieldValue dict)`` for every leaf FieldValue.

    Shared recursion behind both the grounding-only view (``_flatten_grounding``)
    and the full flattening (``flatten_field_values``). The dotted-path grammar is
    identical to the original grounding flattener: descending into a list appends
    ``.{i}`` (the item index) and descending into a dict appends ``.{key}``.
    """
    if _is_field_value(fields):
        yield prefix, fields
        return
    if isinstance(fields, list):
        for i, item in enumerate(fields):
            yield from _walk_leaves(item, f"{prefix}.{i}" if prefix else str(i))
    elif isinstance(fields, dict):
        for key, value in fields.items():
            yield from _walk_leaves(value, f"{prefix}.{key}" if prefix else key)


def _flatten_grounding(fields: dict, prefix: str = "") -> dict[str, Grounding]:
    """Flatten every grounded field into dotted-path -> Grounding for the hover UI."""
    out: dict[str, Grounding] = {}
    for path, node in _walk_leaves(fields, prefix):
        grounding = node["grounding"]
        if grounding is not None:
            out[path] = Grounding(**grounding)
    return out


def flatten_field_values(fields: dict) -> dict[str, dict]:
    """Flatten every leaf into dotted-path -> raw ``FieldValue`` dict.

    Public counterpart to ``_flatten_grounding`` (which keeps only the grounding
    view): the review-queue route consumes the full leaf nodes (value, confidence,
    edited flag, grounding) keyed by the same dotted paths the PATCH endpoint uses.
    """
    return dict(_walk_leaves(fields))


# --- Docling table fallback (minimal, best-effort) ---------------------------

# Confidence cap for values recovered from a table row rather than the extractor.
_TABLE_BACKFILL_CONFIDENCE = 0.5


def _table_cell(value: str | None, grounding: Grounding) -> FieldValue:
    """A low-confidence ``FieldValue`` for a cell backfilled from a Docling table."""
    if value is None:
        return FieldValue(value=None, confidence=0.0, grounding=None)
    return FieldValue(value=value, confidence=_TABLE_BACKFILL_CONFIDENCE, grounding=grounding)


def _backfill_from_tables(fields_model, ocr_result: OCRResult, doc_type: str, ctx: GroundingCtx):
    """Backfill empty invoice line items from persisted Docling tables (no re-OCR).

    Reuses the OCR result's table markdown (present when the OCR engine was Docling).
    Filled fields get capped low confidence + ``partial`` alignment. No tables, or a
    non-invoice doc type, makes this a no-op so fields stay explicitly null.
    """
    if doc_type != "invoice" or fields_model.line_items:
        return fields_model, False

    tables = [t for page in ocr_result.pages for t in page.tables if t.markdown]
    if not tables:
        return fields_model, False

    from app.extraction.invoice import LineItem  # local import avoids an import cycle

    items = []
    for table in tables:
        for row in _parse_md_table(table.markdown):
            numbers = [c for c in row if _looks_numeric(c)]
            if not row or not numbers:
                continue
            grounding = Grounding(page=table.page, snippet=row[0], alignment="partial")
            items.append(
                LineItem(
                    desc=_table_cell(row[0], grounding),
                    qty=FieldValue(value=None, confidence=0.0, grounding=None),
                    unit_price=FieldValue(value=None, confidence=0.0, grounding=None),
                    amount=_table_cell(numbers[-1], grounding),
                )
            )

    if not items:
        return fields_model, False

    fields_model.line_items = items
    ctx.warnings.append(f"backfilled {len(items)} line item(s) from Docling tables (low confidence)")
    return fields_model, True


# --- signature detection post-pass (spatial, best-effort) --------------------


def _detect_signatures(fields_model, spec, doc: Document, ocr_result: OCRResult, ctx: GroundingCtx):
    """Locate + crop signatures over the page images and fill any signature field.

    Best-effort: gated by ``settings.signature_detection_enabled`` and the doc type
    declaring a ``kind="signature"`` field. Skips spreadsheets (no page image). A missing
    model, missing optional deps, or any detector error is swallowed into ``ctx.warnings``
    — the signature field stays ``[]`` and structuring never fails. Returns
    ``(fields_model, detected_any)``.
    """
    if not (settings.signature_detection_enabled and spec.signature_fields):
        return fields_model, False
    if storage.is_spreadsheet(doc.mime):
        return fields_model, False

    from PIL import Image  # local import mirrors the lazy provider imports
    from app.pipeline import signature_detector

    detected_any = False
    try:
        for field_name in spec.signature_fields:
            values: list[FieldValue] = []
            for page_no in range(1, doc.page_count + 1):
                page_path = storage.page_path(doc.id, page_no)
                if not page_path.exists():
                    continue
                detections = signature_detector.detect_signatures(page_path)
                if not detections:
                    continue
                with Image.open(page_path) as page_image:
                    page_image.load()
                    for index, det in enumerate(detections):
                        crop = signature_detector.crop_signature(
                            page_image, det.bbox, settings.signature_crop_padding_px
                        )
                        storage.save_signature_crop(doc.id, page_no, index, crop)
                        image_url = storage.signature_crop_url(doc.id, page_no, index)
                        values.append(
                            FieldValue(
                                value=True,
                                confidence=round(float(det.confidence), 4),
                                grounding=Grounding(
                                    page=page_no,
                                    alignment="exact",
                                    bbox=(
                                        float(det.bbox[0]),
                                        float(det.bbox[1]),
                                        float(det.bbox[2]),
                                        float(det.bbox[3]),
                                    ),
                                    image_url=image_url,
                                ),
                            )
                        )
            setattr(fields_model, field_name, values)
            detected_any = detected_any or bool(values)
    except signature_detector.SignatureDetectorUnavailable as exc:
        ctx.warnings.append(f"signature detection unavailable: {exc}")
        return fields_model, False
    except Exception as exc:  # noqa: BLE001 - never let the post-pass break structuring
        ctx.warnings.append(f"signature detection failed: {exc}")
        return fields_model, False
    return fields_model, detected_any


def _parse_md_table(markdown: str) -> list[list[str]]:
    """Parse a markdown table into rows of trimmed cells, skipping the separator row."""
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and all(set(c) <= {"-", ":"} and c for c in cells):
            continue  # separator row like | --- | --- |
        rows.append(cells)
    return rows[1:] if rows else rows  # drop the header row


def _looks_numeric(text: str) -> bool:
    cleaned = text.strip().replace(",", "").replace("$", "").replace("€", "").replace("£", "")
    if not cleaned:
        return False
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def _artifact_jsonl(flats: list[FlatExtraction]) -> str:
    """Serialize flat extractions as JSONL for the debug/demo artifact."""
    lines = [
        json.dumps(
            {
                "class": f.cls,
                "text": f.text,
                "attributes": f.attributes,
                "char_start": f.char_start,
                "char_end": f.char_end,
            }
        )
        for f in flats
    ]
    return "\n".join(lines)
