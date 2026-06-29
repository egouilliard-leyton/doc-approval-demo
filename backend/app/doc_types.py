"""In-memory document-type registry serving both built-in and custom types.

This is the keystone of the configurable-doc-type design. Built-in types (invoice,
contract) keep their definitions IN CODE — they carry non-serializable
:class:`~app.rules.definition.CodedRuleDef` callables — and are resolved here directly
from the code modules. Custom types (Wave 2) live as JSON rows in the DB and are rebuilt
from their serialized definitions. Both flavours land in a single ``_REGISTRY`` keyed by
the document type's plain string name, so the pipeline only ever asks this module for a
spec / ruleset / citation paths regardless of where the type came from.

Cycle-avoidance: the built-ins are populated LAZILY via :func:`_ensure_builtins` (guarded
by a module flag and called at the top of every public function), and every import of an
``app.extraction.*`` / ``app.rules.*`` module is done INSIDE a function body — never at
module top level. This keeps ``import app.doc_types`` from triggering the
extraction/rules package ``__init__`` mid-construction, which is what would otherwise
create a circular import.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class _RegistryEntry:
    """One resolved document type: its runnable spec, ruleset, and metadata."""

    spec: object
    ruleset: object
    citation_paths: list[str]
    builtin: bool
    version: int


_REGISTRY: dict[str, _RegistryEntry] = {}
_BUILTINS_LOADED = False

# The two built-in types, resolved from code (their CodedRuleDefs can't round-trip JSON).
_BUILTIN_NAMES = ("invoice", "contract")


def _ensure_builtins() -> None:
    """Idempotently register the in-code built-in types. Cycle-proof (lazy imports)."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return

    from app.extraction.contract import SPEC as CON_SPEC
    from app.extraction.invoice import SPEC as INV_SPEC
    from app.rules.contract import CONTRACT_RULE_DEFINITION
    from app.rules.definition import build_ruleset
    from app.rules.invoice import INVOICE_RULE_DEFINITION

    _REGISTRY["invoice"] = _RegistryEntry(
        spec=INV_SPEC,
        ruleset=build_ruleset(INVOICE_RULE_DEFINITION),
        citation_paths=INVOICE_RULE_DEFINITION.citation_paths,
        builtin=True,
        version=0,
    )
    _REGISTRY["contract"] = _RegistryEntry(
        spec=CON_SPEC,
        ruleset=build_ruleset(CONTRACT_RULE_DEFINITION),
        citation_paths=CONTRACT_RULE_DEFINITION.citation_paths,
        builtin=True,
        version=0,
    )
    _BUILTINS_LOADED = True


# --- lookups ------------------------------------------------------------------


def get_spec(name: str):
    """Return the extraction spec for ``name``, or raise ``ValueError`` if unknown."""
    _ensure_builtins()
    try:
        return _REGISTRY[name].spec
    except KeyError:
        raise ValueError(f"No extraction spec for doc_type {name!r}.") from None


def get_ruleset(name: str):
    """Return the rule set for ``name``, or raise ``ValueError`` if unknown."""
    _ensure_builtins()
    try:
        return _REGISTRY[name].ruleset
    except KeyError:
        raise ValueError(f"No rule set for doc_type {name!r}.") from None


def get_citation_paths(name: str) -> list[str]:
    """Field paths to cite for ``name`` (empty list for an unknown type)."""
    _ensure_builtins()
    entry = _REGISTRY.get(name)
    return entry.citation_paths if entry is not None else []


def is_registered(name: str) -> bool:
    """Whether ``name`` resolves to a registered document type."""
    _ensure_builtins()
    return name in _REGISTRY


def list_names() -> list[str]:
    """All registered document-type names."""
    _ensure_builtins()
    return list(_REGISTRY)


# --- custom-type (DB-backed) registration -------------------------------------


def register_from_row(row) -> None:
    """Build and register a custom type from a ``DocTypeDefinitionRow``.

    Any failure building the spec/ruleset is re-raised as ``ValueError`` so the caller
    (a CRUD route in Wave 2) can map it to a 422.
    """
    from app.extraction.definition import build_spec
    from app.rules.definition import build_ruleset
    from app.serialization import dict_to_extraction_defn, dict_to_rule_defn

    try:
        spec = build_spec(dict_to_extraction_defn(row.extraction_definition))
        ruleset = build_ruleset(dict_to_rule_defn(row.rule_definition))
    except Exception as exc:  # noqa: BLE001 — surface as a ValueError for the caller
        raise ValueError(f"Could not build doc type {row.name!r}: {exc}") from exc

    _REGISTRY[row.name] = _RegistryEntry(
        spec=spec,
        ruleset=ruleset,
        citation_paths=list(row.citation_paths),
        builtin=row.builtin,
        version=row.version,
    )


def invalidate(name: str) -> None:
    """Drop ``name`` from the registry (so a later lookup reloads it)."""
    _REGISTRY.pop(name, None)


# --- startup seeding / loading ------------------------------------------------


def seed_builtins(session) -> None:
    """Idempotently persist a DB row for each built-in type (for the future UI/CRUD).

    The stored rows are informational: built-ins always resolve from code, so the two
    ``CodedRuleDef`` rules that don't serialize being dropped from the stored
    ``rule_definition`` is fine.
    """
    _ensure_builtins()

    from app.extraction.contract import CONTRACT_DEFINITION
    from app.extraction.invoice import INVOICE_DEFINITION
    from app.models import DocTypeDefinitionRow
    from app.rules.contract import CONTRACT_RULE_DEFINITION
    from app.rules.invoice import INVOICE_RULE_DEFINITION
    from app.serialization import extraction_defn_to_dict, rule_defn_to_dict

    extraction_defns = {"invoice": INVOICE_DEFINITION, "contract": CONTRACT_DEFINITION}
    rule_defns = {"invoice": INVOICE_RULE_DEFINITION, "contract": CONTRACT_RULE_DEFINITION}

    for name in _BUILTIN_NAMES:
        if session.get(DocTypeDefinitionRow, name) is not None:
            continue  # idempotent: never overwrite an existing row
        row = DocTypeDefinitionRow(
            name=name,
            label=name.capitalize(),
            extraction_definition=extraction_defn_to_dict(extraction_defns[name]),
            rule_definition=rule_defn_to_dict(rule_defns[name]),
            citation_paths=list(_REGISTRY[name].citation_paths),
            builtin=True,
            version=1,
        )
        session.add(row)
    session.commit()


def load_custom_types(session) -> None:
    """Register every custom (non-built-in) DB row, logging and skipping bad ones."""
    from sqlmodel import select

    from app.models import DocTypeDefinitionRow

    rows = session.exec(
        select(DocTypeDefinitionRow).where(DocTypeDefinitionRow.builtin == False)  # noqa: E712
    ).all()
    for row in rows:
        try:
            register_from_row(row)
        except Exception as exc:  # noqa: BLE001 — never crash startup over one bad type
            logger.warning("Skipping custom doc type %r: %s", row.name, exc)


__all__ = [
    "get_spec",
    "get_ruleset",
    "get_citation_paths",
    "is_registered",
    "list_names",
    "register_from_row",
    "invalidate",
    "seed_builtins",
    "load_custom_types",
]
