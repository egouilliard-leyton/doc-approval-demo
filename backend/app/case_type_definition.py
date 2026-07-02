"""Declarative case-type definitions and their dict⇄dataclass helpers.

A :class:`CaseTypeDefinition` describes a case type as data — a list of
:class:`CaseTypeMemberDef` (each naming an expected member doc-type with min/max
cardinality) and an opaque ``canonical_fields`` mapping. Unlike a doc-type definition,
a case-type definition carries no callables, so it round-trips JSON losslessly via
:func:`to_dict` / :func:`from_dict` and is stored verbatim on a
:class:`~app.models.CaseTypeDefinitionRow`.

``canonical_fields``, ``min_count`` and ``max_count`` are carried-but-not-enforced in
Phase 1: they are persisted and returned, but the reconciler that consumes them lands in
Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CaseTypeMemberDef:
    """One expected member doc-type of a case type, with its cardinality.

    ``min_count`` / ``max_count`` express 1:1 vs 1:N expectations (``max_count=None``
    means unbounded). Both are placeholders in Phase 1 — carried, not enforced.
    """

    doc_type: str
    min_count: int = 1
    max_count: int | None = 1
    label: str = ""


@dataclass
class CaseTypeDefinition:
    """A case type expressed declaratively, ready to persist / return.

    ``canonical_fields`` is an opaque placeholder consumed by the Phase 2 reconciler; it
    is carried through the schema unchanged in Phase 1.
    """

    name: str
    label: str
    icon: str = ""
    members: list[CaseTypeMemberDef] = field(default_factory=list)
    canonical_fields: dict = field(default_factory=dict)


def member_to_dict(member: CaseTypeMemberDef) -> dict:
    """Serialize one member definition to a plain JSON-friendly dict."""
    return {
        "doc_type": member.doc_type,
        "min_count": member.min_count,
        "max_count": member.max_count,
        "label": member.label,
    }


def member_from_dict(data: dict) -> CaseTypeMemberDef:
    """Rebuild one member definition from its serialized dict."""
    return CaseTypeMemberDef(
        doc_type=data["doc_type"],
        min_count=data.get("min_count", 1),
        max_count=data.get("max_count", 1),
        label=data.get("label", ""),
    )


def to_dict(defn: CaseTypeDefinition) -> dict:
    """Serialize a case-type definition to a JSON-friendly dict."""
    return {
        "name": defn.name,
        "label": defn.label,
        "icon": defn.icon,
        "members": [member_to_dict(m) for m in defn.members],
        "canonical_fields": dict(defn.canonical_fields),
    }


def from_dict(data: dict) -> CaseTypeDefinition:
    """Rebuild a case-type definition from its serialized dict."""
    return CaseTypeDefinition(
        name=data["name"],
        label=data.get("label", ""),
        icon=data.get("icon", ""),
        members=[member_from_dict(m) for m in data.get("members", [])],
        canonical_fields=dict(data.get("canonical_fields") or {}),
    )


# The one built-in case type: an AP 3-way (optionally 4-way) match. Resolved from this
# constant and mirrored to a DB row on startup for the future UI/CRUD layer.
AP_MATCH_DEFINITION = CaseTypeDefinition(
    name="ap_match",
    label="AP 3-Way Match",
    icon="",
    members=[
        CaseTypeMemberDef(doc_type="invoice", min_count=1, max_count=1, label="Invoice"),
        CaseTypeMemberDef(doc_type="po", min_count=1, max_count=1, label="Purchase Order"),
        CaseTypeMemberDef(doc_type="contract", min_count=0, max_count=1, label="Contract"),
        CaseTypeMemberDef(
            doc_type="delivery_note", min_count=0, max_count=1, label="Delivery Note"
        ),
    ],
    # Canonical fields the Phase 2 reconciler fills from the members. Each entry maps a
    # canonical name to the per-doc-type source paths that feed it (a bag of grounded
    # candidates). Deliberately omits any date field: an invoice date and a contract
    # effective date are DIFFERENT facts and would fire a false conflict every time.
    canonical_fields={
        "total_amount": [
            {"doc_type": "invoice", "field_path": "total"},
            {"doc_type": "po", "field_path": "total"},
            {"doc_type": "contract", "field_path": "total_value"},
        ],
        "vendor_name": [
            {"doc_type": "invoice", "field_path": "vendor"},
            {"doc_type": "po", "field_path": "vendor"},
            {"doc_type": "contract", "field_path": "parties"},
        ],
        "po_number": [
            {"doc_type": "invoice", "field_path": "po_number"},
            {"doc_type": "po", "field_path": "po_number"},
        ],
    },
)
