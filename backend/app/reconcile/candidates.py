"""Candidate gathering: member documents' structured fields -> grounded candidates.

A canonical field is a **bag of grounded candidates** drawn from N member documents (the
1:1 / 1:N abstraction from the design doc). This module turns member documents into those
bags, two ways:

* :func:`gather_mapped` — for a DEFINED case type, following its ``canonical_fields``
  mapping (``{doc_type, field_path}`` sources).
* :func:`gather_open_pile` — for an OPEN pile (no case type), inferring canonical fields
  from top-level field names that overlap across ≥2 member documents.

This package deliberately does NOT import from ``app.pipeline`` (clean layering): the tiny
leaf walker below is reimplemented locally rather than reusing the structuring one, but it
uses the SAME leaf predicate (:func:`_is_field_value`) so the two never diverge.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import doc_types
from app.schemas import Grounding


@dataclass
class Candidate:
    """One grounded value drawn from a member document for a canonical field."""

    document_id: str
    doc_type: str
    field_path: str
    value: object
    confidence: float
    grounding: Grounding | None


def _is_field_value(node: object) -> bool:
    """A leaf FieldValue node (same predicate as ``pipeline.structuring._is_field_value``).

    Subset check (not exact): a leaf may also carry edit metadata once corrected.
    """
    return isinstance(node, dict) and {"value", "confidence", "grounding"} <= node.keys()


def _leaves(fields: object, prefix: str = "") -> list[tuple[str, dict]]:
    """Every leaf FieldValue node under ``fields`` as ``(dotted_path, node)``.

    Recurses dict keys and list indices into dotted paths, yielding EVERY leaf — present
    or null — unlike the structuring flattener which skips ungrounded leaves. A null field
    is still an explicit ``{value: None, ...}`` leaf, so it is yielded too (the reconciler
    keeps it in the candidate list but drops it from the agreement test).
    """
    out: list[tuple[str, dict]] = []
    if _is_field_value(fields):
        out.append((prefix, fields))  # type: ignore[arg-type]
        return out
    if isinstance(fields, list):
        for i, item in enumerate(fields):
            key = f"{prefix}.{i}" if prefix else str(i)
            out.extend(_leaves(item, key))
    elif isinstance(fields, dict):
        for name, value in fields.items():
            key = f"{prefix}.{name}" if prefix else name
            out.extend(_leaves(value, key))
    return out


def _grounding_of(node: dict) -> Grounding | None:
    """Parse a leaf node's ``grounding`` dict into a :class:`Grounding` (or None)."""
    raw = node.get("grounding")
    if isinstance(raw, dict):
        return Grounding(**raw)
    return None


def _member_fields(member: object) -> dict | None:
    """The dumped ``fields`` dict of a member's structured result, or None if absent."""
    structured = getattr(member, "structured", None)
    if structured is None:
        return None
    fields = getattr(structured, "fields", None)
    return fields if isinstance(fields, dict) else None


def _subtree(fields: dict, path: str) -> object | None:
    """Navigate a dotted ``path`` into ``fields``; None when any segment is missing.

    Never raises on a missing/partial path — a bad path degrades to an empty bag.
    """
    node: object = fields
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def gather_mapped(members: list, mapping_entry: list[dict]) -> list[Candidate]:
    """Candidates for one DEFINED-case-type canonical field, per its source mapping.

    ``mapping_entry`` is the list of ``{doc_type, field_path}`` sources for the field. For
    each source, every member of that doc-type (and only if the doc-type is registered —
    unregistered members like ``po``/``delivery_note`` are skipped defensively) contributes
    the leaves found under ``field_path``: a scalar path yields 0/1 candidates, a list path
    (e.g. ``parties``) yields one per item (the 1:N case).
    """
    out: list[Candidate] = []
    for source in mapping_entry:
        source_type = source.get("doc_type")
        field_path = source.get("field_path")
        if not source_type or not field_path or not doc_types.is_registered(source_type):
            continue
        for member in members:
            if getattr(member, "doc_type", None) != source_type:
                continue
            fields = _member_fields(member)
            if fields is None:
                continue
            subtree = _subtree(fields, field_path)
            if subtree is None:
                continue
            for path, node in _leaves(subtree, prefix=field_path):
                out.append(
                    Candidate(
                        document_id=getattr(member, "document_id", ""),
                        doc_type=source_type,
                        field_path=path,
                        value=node.get("value"),
                        confidence=float(node.get("confidence", 0.0) or 0.0),
                        grounding=_grounding_of(node),
                    )
                )
    return out


def _open_pile_key(path: str) -> str:
    """Join key for open-pile inference: a dotted path with list indices stripped.

    ``line_items.0.amount`` -> ``line_items.amount``; ``total`` -> ``total``; ``parties.0``
    -> ``parties``. So the SAME conceptual field lines up across documents regardless of
    which row index it occupies.
    """
    return ".".join(part for part in path.split(".") if not part.isdigit())


def gather_open_pile(members: list) -> dict[str, list[Candidate]]:
    """Infer canonical fields for an OPEN pile from fields overlapping across documents.

    Every member's leaves are bucketed by their index-stripped join key. A join key becomes
    canonical only when it carries ≥1 NON-NULL leaf in ≥2 DISTINCT member documents — a
    genuinely shared, cross-referenced field. The returned bags keep every candidate
    (including nulls) so the reconciler lists them; keys are returned in first-seen order.
    """
    bags: dict[str, list[Candidate]] = {}
    docs_with_value: dict[str, set[str]] = {}
    for member in members:
        fields = _member_fields(member)
        if fields is None:
            continue
        document_id = getattr(member, "document_id", "")
        doc_type = getattr(member, "doc_type", None) or ""
        for path, node in _leaves(fields):
            key = _open_pile_key(path)
            value = node.get("value")
            bags.setdefault(key, []).append(
                Candidate(
                    document_id=document_id,
                    doc_type=doc_type,
                    field_path=path,
                    value=value,
                    confidence=float(node.get("confidence", 0.0) or 0.0),
                    grounding=_grounding_of(node),
                )
            )
            if value is not None:
                docs_with_value.setdefault(key, set()).add(document_id)

    return {
        key: candidates
        for key, candidates in bags.items()
        if len(docs_with_value.get(key, set())) >= 2
    }
