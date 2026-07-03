"""In-memory case-type registry serving both built-in and custom types.

Parallels :mod:`app.doc_types`, but simpler: a :class:`CaseTypeDefinition` is fully
JSON-serializable (no callables), so there is no code-vs-DB resolution split — both
built-in and custom types resolve from a single deserialized definition. The one
built-in type (``ap_match``) is defined in code as
:data:`~app.case_type_definition.AP_MATCH_DEFINITION` and mirrored to a DB row on
startup for the future UI/CRUD layer.

The built-in is populated LAZILY via :func:`_ensure_builtins` (guarded by a module flag
and called at the top of every public function) so importing this module never triggers
side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.case_type_definition import (
    AP_MATCH_DEFINITION,
    CaseTypeDefinition,
    from_dict,
)

logger = logging.getLogger(__name__)


@dataclass
class _RegistryEntry:
    """One resolved case type: its definition plus metadata."""

    definition: CaseTypeDefinition
    builtin: bool
    version: int


_REGISTRY: dict[str, _RegistryEntry] = {}
_BUILTINS_LOADED = False

# The one built-in case type, resolved from code.
_BUILTIN_NAMES = ("ap_match",)


def _ensure_builtins() -> None:
    """Idempotently register the in-code built-in case type(s)."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    _REGISTRY["ap_match"] = _RegistryEntry(
        definition=AP_MATCH_DEFINITION,
        builtin=True,
        version=0,
    )
    _BUILTINS_LOADED = True


# --- lookups ------------------------------------------------------------------


def get_definition(name: str) -> CaseTypeDefinition:
    """Return the definition for ``name``, or raise ``ValueError`` if unknown."""
    _ensure_builtins()
    try:
        return _REGISTRY[name].definition
    except KeyError:
        raise ValueError(f"No case type {name!r}.") from None


def is_registered(name: str) -> bool:
    """Whether ``name`` resolves to a registered case type."""
    _ensure_builtins()
    return name in _REGISTRY


def list_names() -> list[str]:
    """All registered case-type names."""
    _ensure_builtins()
    return list(_REGISTRY)


# --- custom-type (DB-backed) registration -------------------------------------


def register_from_row(row) -> None:
    """Build and register a case type from a ``CaseTypeDefinitionRow``."""
    definition = from_dict(
        {
            "name": row.name,
            "label": row.label,
            "icon": row.icon,
            "members": list(row.members),
            "canonical_fields": dict(row.canonical_fields),
        }
    )
    _REGISTRY[row.name] = _RegistryEntry(
        definition=definition,
        builtin=row.builtin,
        version=row.version,
    )


def invalidate(name: str) -> None:
    """Drop ``name`` from the registry (so a later lookup reloads it)."""
    _REGISTRY.pop(name, None)


# --- startup seeding / loading ------------------------------------------------


def seed_builtins(session) -> None:
    """Idempotently upsert a DB row for each built-in case type (for the UI/CRUD)."""
    _ensure_builtins()

    from app.case_type_definition import member_to_dict
    from app.models import CaseTypeDefinitionRow

    for name in _BUILTIN_NAMES:
        if session.get(CaseTypeDefinitionRow, name) is not None:
            continue  # idempotent: never overwrite an existing row
        defn = _REGISTRY[name].definition
        row = CaseTypeDefinitionRow(
            name=name,
            label=defn.label,
            icon=defn.icon,
            members=[member_to_dict(m) for m in defn.members],
            canonical_fields=dict(defn.canonical_fields),
            builtin=True,
            version=1,
        )
        session.add(row)
    session.commit()


def load_custom_types(session) -> None:
    """Register every custom (non-built-in) DB row, logging and skipping bad ones."""
    from sqlmodel import select

    from app.models import CaseTypeDefinitionRow

    rows = session.exec(
        select(CaseTypeDefinitionRow).where(CaseTypeDefinitionRow.builtin == False)  # noqa: E712
    ).all()
    for row in rows:
        try:
            register_from_row(row)
        except Exception as exc:  # noqa: BLE001 — never crash startup over one bad type
            logger.warning("Skipping custom case type %r: %s", row.name, exc)


__all__ = [
    "get_definition",
    "is_registered",
    "list_names",
    "register_from_row",
    "invalidate",
    "seed_builtins",
    "load_custom_types",
]
