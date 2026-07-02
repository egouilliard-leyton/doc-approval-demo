"""Case reconciliation: candidate bags -> canonical fields + agreement + citations.

Given a case's member documents (each with its persisted ``StructuredResult``), this
gathers a bag of grounded candidates per canonical field (mapped for a defined case type,
inferred for an open pile) and reconciles each bag into a single :class:`CanonicalFieldResult`.

The agreement test is the **grouped-by-document exists-match** algorithm — deliberately NOT
flat pairwise across every candidate:

* Candidates are grouped BY DOCUMENT. Nulls are kept in the listed candidates but dropped
  from the agreement test.
* 0 non-empty documents -> no value, ``agreement=True`` (a missing signal is not a
  conflict).
* 1 non-empty document -> trivially agrees; the value is that document's first candidate.
* >=2 non-empty documents -> agreement holds iff EVERY document-pair has at least one
  cross-group matching candidate pair (under the field's inferred kind). This is what makes
  a scalar-vs-list field (invoice ``vendor`` vs contract ``parties``) reconcile: the vendor
  only has to match SOME party, not every party. Any pair with zero matches -> a conflict.

A conflict never silently picks a winner: ``agreement=False`` + a ``conflict_detail`` listing
each document's values, so the case routes to human review (the locked conflict policy).
"""

from __future__ import annotations

from itertools import combinations

from app.config import settings
from app.schemas import (
    CanonicalFieldResult,
    CandidateInfo,
    CaseReconciliation,
    Citation,
)

from .candidates import Candidate, gather_mapped, gather_open_pile
from .tolerance import infer_kind, values_agree


def reconcile_case(case, case_type_defn, members: list) -> CaseReconciliation:
    """Reconcile a case's member documents into its canonical fields.

    ``case`` is the case record (``id`` / ``case_type``); ``case_type_defn`` is the resolved
    :class:`~app.case_type_definition.CaseTypeDefinition` for a defined case, or ``None`` for
    an open pile; ``members`` are the case's assembled members (each with ``document_id``,
    ``doc_type`` and an optional ``structured`` result). Never raises on missing/partial
    data — a missing field / doc-type / path degrades to an absent (empty) bag.
    """
    member_count = len(members)
    structured_count = sum(
        1 for m in members if getattr(m, "structured", None) is not None
    )
    warnings: list[str] = []

    canonical_fields: list[CanonicalFieldResult] = []
    if case_type_defn is not None:
        # Defined case type: follow its canonical_fields mapping (every declared field is
        # listed, even when no member supplies it).
        for name, mapping_entry in case_type_defn.canonical_fields.items():
            bag = gather_mapped(members, mapping_entry)
            canonical_fields.append(_reconcile_field(name, bag))
    else:
        # Open pile: infer canonical fields from fields overlapping across >=2 documents.
        for name, bag in gather_open_pile(members).items():
            canonical_fields.append(_reconcile_field(name, bag))

    return CaseReconciliation(
        case_id=getattr(case, "id", ""),
        case_type=getattr(case, "case_type", None),
        status="reconciled",
        canonical_fields=canonical_fields,
        member_count=member_count,
        structured_count=structured_count,
        warnings=warnings,
    )


def _reconcile_field(name: str, candidates: list[Candidate]) -> CanonicalFieldResult:
    """Reconcile one canonical field's candidate bag (see the module docstring)."""
    kind = infer_kind(name, [c.value for c in candidates])

    # Group by document, preserving first-seen (document) order. Nulls stay in the listed
    # candidates but are excluded from the agreement test.
    by_doc: dict[str, list[Candidate]] = {}
    for cand in candidates:
        by_doc.setdefault(cand.document_id, []).append(cand)
    non_empty_docs = [
        doc for doc, cands in by_doc.items() if any(c.value is not None for c in cands)
    ]

    agreement = True
    conflict_detail: str | None = None
    value: object = None

    if len(non_empty_docs) == 1:
        value = _first_non_null(by_doc[non_empty_docs[0]])
    elif len(non_empty_docs) >= 2:
        for doc_a, doc_b in combinations(non_empty_docs, 2):
            vals_a = [c.value for c in by_doc[doc_a] if c.value is not None]
            vals_b = [c.value for c in by_doc[doc_b] if c.value is not None]
            if not any(
                values_agree(kind, va, vb, settings) for va in vals_a for vb in vals_b
            ):
                agreement = False
                break
        value = _first_non_null_overall(candidates)
        if not agreement:
            conflict_detail = _conflict_detail(by_doc, non_empty_docs)

    return CanonicalFieldResult(
        name=name,
        value=value,
        agreement=agreement,
        kind=kind,
        candidates=[_candidate_info(c) for c in candidates],
        conflict_detail=conflict_detail,
        citations=_citations(name, by_doc, non_empty_docs),
    )


def _first_non_null(cands: list[Candidate]) -> object:
    """First non-null value in a document's candidate list."""
    for c in cands:
        if c.value is not None:
            return c.value
    return None


def _first_non_null_overall(candidates: list[Candidate]) -> object:
    """First non-null candidate value in document order (the reconciled value)."""
    for c in candidates:
        if c.value is not None:
            return c.value
    return None


def _conflict_detail(by_doc: dict[str, list[Candidate]], docs: list[str]) -> str:
    """A human-readable listing of each conflicting document's value(s)."""
    parts: list[str] = []
    for doc in docs:
        cands = by_doc[doc]
        label = cands[0].doc_type or doc
        vals = [str(c.value) for c in cands if c.value is not None]
        parts.append(f"{label}: {', '.join(vals)}")
    return "; ".join(parts)


def _citations(name: str, by_doc: dict[str, list[Candidate]], docs: list[str]) -> list[Citation]:
    """One citation per contributing document, with ``document_id`` set."""
    out: list[Citation] = []
    for doc in docs:
        cand = next((c for c in by_doc[doc] if c.value is not None), None)
        page = cand.grounding.page if cand is not None and cand.grounding is not None else None
        source = f"page {page}" if page is not None else ""
        out.append(Citation(field=name, source=source, document_id=doc))
    return out


def _candidate_info(c: Candidate) -> CandidateInfo:
    """Project a :class:`Candidate` into its API :class:`CandidateInfo`."""
    page = c.grounding.page if c.grounding is not None else None
    return CandidateInfo(
        document_id=c.document_id,
        doc_type=c.doc_type,
        field_path=c.field_path,
        value=c.value,
        confidence=c.confidence,
        page=page,
    )
