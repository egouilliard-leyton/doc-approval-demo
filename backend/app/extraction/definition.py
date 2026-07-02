"""Declarative document-type definitions and their generic interpreter.

A :class:`DocTypeDefinition` describes a document type as data — a list of
:class:`FieldDef` (each naming an extraction class, its kind, and how to coerce it),
the few-shot examples, the core field paths, and an optional prompt. :func:`build_spec`
turns that declaration into a :class:`~app.extraction.base.DocTypeSpec` by synthesising
the Pydantic field model (via ``pydantic.create_model``) and a generic ``assemble``
function. The assembler reuses the grounding/confidence helpers from
:mod:`app.extraction.base` verbatim, so a hand-written spec and its declarative
equivalent produce byte-identical output — this is the parity layer that lets the two
built-in types (invoice, contract) be expressed as data and future types be authored
without writing Python.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import create_model

from app.schemas import FieldValue

from .base import (
    DocTypeSpec,
    FlatExtraction,
    GroundingCtx,
    attr_field,
    ground_field,
    group_by_class,
    missing_field,
    presence_field,
    scalar_field,
    to_number,
    to_text,
)


# --- declarative definition dataclasses ---------------------------------------


@dataclass
class SubFieldDef:
    """One attribute of a composite field (a line-item column, a clause's notice).

    ``source="span"`` takes its value from the parent extraction's verbatim text;
    ``source="attribute"`` reads ``flat.attributes[attr_key or name]``.
    """

    name: str
    source: Literal["span", "attribute"]
    coerce: Literal["text", "number"] = "text"
    attr_key: str | None = None


@dataclass
class FieldDef:
    """One top-level field of a document type.

    ``cls`` is the extraction class the model emits for it; ``kind`` selects the
    assembly strategy. ``sub_fields`` is only meaningful for the composite kinds.
    """

    name: str
    kind: Literal[
        "scalar", "presence", "list_scalar", "list_composite", "composite", "signature"
    ]
    cls: str
    coerce: Literal["text", "number"] = "text"
    is_core: bool = False
    sub_fields: list[SubFieldDef] = field(default_factory=list)
    # Only meaningful for ``kind="list_scalar"``: collapses exact-normalized duplicate
    # items across merged sections (see ``structuring._dedup_list_scalar``). A no-op for
    # every other kind — the merge only consults it for list_scalar fields.
    dedup: bool = False


@dataclass
class ExampleExtraction:
    """One extraction inside a few-shot example (mirrors ``lx.data.Extraction``)."""

    cls: str
    text: str
    attributes: dict = field(default_factory=dict)


@dataclass
class ExampleData:
    """One few-shot example: a source text plus its expected extractions."""

    text: str
    extractions: list[ExampleExtraction] = field(default_factory=list)


@dataclass
class DocTypeDefinition:
    """A document type expressed declaratively, ready for :func:`build_spec`.

    ``prompt`` overrides the auto-generated prompt when non-empty (the built-in types
    carry their hand-tuned prompt verbatim); ``core_paths`` are the dotted field paths
    averaged into the overall extraction confidence.
    """

    name: str
    fields: list[FieldDef]
    core_paths: list[str]
    prompt: str = ""
    examples: list[ExampleData] = field(default_factory=list)


# Coercion name -> callable, shared by scalar/list/composite assembly so a definition
# only ever names a coercion ("text"/"number") rather than importing a function.
_COERCE: dict[str, Callable] = {"text": to_text, "number": to_number}


def _pascal(name: str) -> str:
    """Snake-case to a singular PascalCase model name.

    ``"line_items" -> "LineItem"``, ``"termination_clause" -> "TerminationClause"``:
    PascalCase each underscore-separated part, then drop a single trailing ``s`` so a
    collection field names its row model in the singular (``line_items`` -> ``LineItem``,
    matching the hand-written class ``structuring.py`` imports).
    """
    pascal = "".join(part.capitalize() for part in name.split("_"))
    return pascal[:-1] if pascal.endswith("s") else pascal


def _build_field_model(defn: DocTypeDefinition) -> tuple[type, dict[str, type]]:
    """Synthesise the top-level Pydantic field model and any composite sub-models.

    Returns ``(TopModel, composite_sub_models)`` where ``composite_sub_models`` maps
    each composite/list-composite field's ``cls`` to its generated sub-model. Every
    field is required (``(Type, ...)``) so absent values surface as explicit
    ``FieldValue(value=None)`` from the assembler rather than being dropped.
    """
    composite_sub_models: dict[str, type] = {}
    top_fields: dict[str, tuple] = {}
    for f in defn.fields:
        if f.kind in ("scalar", "presence"):
            top_fields[f.name] = (FieldValue, ...)
        elif f.kind in ("list_scalar", "signature"):
            # ``signature`` is a list[FieldValue] filled by the spatial post-pass, not
            # the LLM; it assembles to ``[]`` here (its ``cls`` is never emitted).
            top_fields[f.name] = (list[FieldValue], ...)
        elif f.kind in ("composite", "list_composite"):
            sub_model = create_model(
                _pascal(f.name),
                **{sf.name: (FieldValue, ...) for sf in f.sub_fields},
            )
            composite_sub_models[f.cls] = sub_model
            if f.kind == "composite":
                top_fields[f.name] = (sub_model, ...)
            else:
                top_fields[f.name] = (list[sub_model], ...)
        else:  # pragma: no cover - kind is a closed Literal
            raise ValueError(f"unknown field kind {f.kind!r} for {f.name!r}")
    top_model = create_model(_pascal(defn.name) + "Fields", **top_fields)
    return top_model, composite_sub_models


def _sub_values(
    flat: FlatExtraction,
    sub_fields: list[SubFieldDef],
    ctx: GroundingCtx,
    grounding,
    confidence: float,
) -> dict:
    """Build a composite sub-model's kwargs, sharing the parent span's grounding.

    A ``span`` sub-field takes the parent extraction's verbatim text (coerced); an
    ``attribute`` sub-field reads its column via :func:`attr_field`. Both reuse the
    grounding/confidence computed once for the parent row.
    """
    values: dict = {}
    for sf in sub_fields:
        if sf.source == "span":
            values[sf.name] = FieldValue(
                value=_COERCE[sf.coerce](flat.text),
                confidence=confidence,
                grounding=grounding,
            )
        else:
            values[sf.name] = attr_field(
                flat, sf.attr_key or sf.name, ctx, grounding, confidence, _COERCE[sf.coerce]
            )
    return values


def _make_assemble(
    fields: list[FieldDef], composite_sub_models: dict[str, type], top_model: type
) -> Callable[[list[FlatExtraction], GroundingCtx], object]:
    """Build the generic ``assemble(flats, ctx)`` for one definition.

    Dispatches per :class:`FieldDef` kind to the matching :mod:`base` helper so the
    grounding/confidence math is never reimplemented here, then constructs the
    synthesised top model.
    """

    def assemble(flats: list[FlatExtraction], ctx: GroundingCtx) -> object:
        grouped = group_by_class(flats)
        result: dict = {}
        for f in fields:
            if f.kind == "scalar":
                result[f.name] = scalar_field(grouped, f.cls, ctx, _COERCE[f.coerce])
            elif f.kind == "presence":
                result[f.name] = presence_field(grouped, f.cls, ctx)
            elif f.kind in ("list_scalar", "signature"):
                # ``signature`` fields carry no LLM-emitted ``cls``, so this assembles
                # to ``[]``; the structuring post-pass fills them from the detector.
                items: list[FieldValue] = []
                for flat in grouped.get(f.cls, []):
                    grounding, confidence = ground_field(flat, ctx)
                    items.append(
                        FieldValue(
                            value=_COERCE[f.coerce](flat.text),
                            confidence=confidence,
                            grounding=grounding,
                        )
                    )
                result[f.name] = items
            elif f.kind == "list_composite":
                sub_model = composite_sub_models[f.cls]
                rows: list = []
                for flat in grouped.get(f.cls, []):
                    grounding, confidence = ground_field(flat, ctx)
                    rows.append(
                        sub_model(**_sub_values(flat, f.sub_fields, ctx, grounding, confidence))
                    )
                result[f.name] = rows
            elif f.kind == "composite":
                sub_model = composite_sub_models[f.cls]
                cls_flats = grouped.get(f.cls)
                if not cls_flats:
                    result[f.name] = sub_model(**{sf.name: missing_field() for sf in f.sub_fields})
                else:
                    flat = cls_flats[0]
                    grounding, confidence = ground_field(flat, ctx)
                    result[f.name] = sub_model(
                        **_sub_values(flat, f.sub_fields, ctx, grounding, confidence)
                    )
        return top_model(**result)

    return assemble


def _make_examples_factory(examples: list[ExampleData]) -> Callable[[], list]:
    """Build the lazy few-shot factory (imports langextract only when the engine runs).

    Empty attribute dicts are passed as ``attributes=None`` so the generated examples
    are identical to the originals, which only set ``attributes`` when non-empty.
    """

    def factory() -> list:
        import langextract as lx

        return [
            lx.data.ExampleData(
                text=ex.text,
                extractions=[
                    lx.data.Extraction(
                        extraction_class=e.cls,
                        extraction_text=e.text,
                        attributes=(e.attributes or None),
                    )
                    for e in ex.extractions
                ],
            )
            for ex in examples
        ]

    return factory


def build_prompt(defn: DocTypeDefinition) -> str:
    """Generate a faithful LangExtract prompt from a definition's field list.

    Names the document type, lists the extraction classes (noting each composite's
    attribute names), then appends the standard verbatim/no-fabrication rules. Used for
    future UI-authored types; it is NOT consulted when ``defn.prompt`` is non-empty.
    """
    class_notes: list[str] = []
    for f in defn.fields:
        if f.sub_fields:
            attrs = ", ".join(sf.name for sf in f.sub_fields)
            class_notes.append(f"{f.cls} (with attributes {attrs})")
        else:
            class_notes.append(f.cls)
    classes = ", ".join(class_notes)
    return (
        f"Extract approval-relevant fields from this {defn.name}. "
        f"Use these extraction classes: {classes}.\n\n"
        "Rules:\n"
        "- Use the exact verbatim text from the source for each extraction_text (do not\n"
        "  paraphrase or reformat) so each field can be traced back to its location.\n"
        "- Only extract a field if it actually appears in the text. Do NOT infer, guess, or\n"
        "  fabricate. If a field is absent, simply emit no extraction for it."
    )


def build_spec(defn: DocTypeDefinition) -> DocTypeSpec:
    """Interpret a :class:`DocTypeDefinition` into a runnable :class:`DocTypeSpec`."""
    top_model, sub_models = _build_field_model(defn)
    return DocTypeSpec(
        prompt=(defn.prompt or build_prompt(defn)),
        examples_factory=_make_examples_factory(defn.examples),
        extraction_classes={f.cls for f in defn.fields},
        field_model=top_model,
        assemble=_make_assemble(defn.fields, sub_models, top_model),
        core_paths=defn.core_paths,
        signature_fields=[f.name for f in defn.fields if f.kind == "signature"],
        dedup_fields=[f.name for f in defn.fields if f.dedup],
    )
