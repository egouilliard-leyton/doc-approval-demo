"""Pure (de)serialization between the in-code declarative dataclasses and JSON dicts.

This module has NO database or FastAPI imports — it only knows how to turn a
:class:`~app.extraction.definition.DocTypeDefinition` /
:class:`~app.rules.definition.DocTypeRuleDefinition` into a plain ``dict`` (for storage
in the DB definition registry) and back. The two ``validate_*`` functions are Wave 1
stubs that Wave 2 fills in once the CRUD layer needs them.

The rule primitives are tagged with a ``"kind"`` discriminator on the way out (and the
discriminator is consumed on the way back). :class:`~app.rules.definition.CodedRuleDef`
has no serializable kind — it carries a Python callable — so it is silently skipped:
the built-in types that use it always resolve from code, never from their stored JSON.
"""

from __future__ import annotations

import dataclasses
import re
from datetime import date

from app.extraction.definition import (
    DocTypeDefinition,
    ExampleData,
    ExampleExtraction,
    FieldDef,
    SubFieldDef,
)
from app.rules.definition import (
    ArithmeticIdentityRuleDef,
    CodedRuleDef,
    DateConstraintRuleDef,
    DocTypeRuleDefinition,
    EqualityRuleDef,
    FieldDependencyRuleDef,
    LlmAdvisoryRuleDef,
    PresenceRuleDef,
    SetMembershipRuleDef,
    ThresholdCompareRuleDef,
    UniquenessVsHistoryRuleDef,
)


# --- extraction definition <-> dict -------------------------------------------


def extraction_defn_to_dict(defn: DocTypeDefinition) -> dict:
    """Serialize a :class:`DocTypeDefinition` to a JSON-safe dict (verbatim asdict)."""
    return dataclasses.asdict(defn)


def dict_to_extraction_defn(d: dict) -> DocTypeDefinition:
    """Rebuild a :class:`DocTypeDefinition` from its serialized dict form."""
    fields = [
        FieldDef(
            name=f["name"],
            kind=f["kind"],
            cls=f["cls"],
            coerce=f.get("coerce", "text"),
            is_core=f.get("is_core", False),
            sub_fields=[
                SubFieldDef(
                    name=sf["name"],
                    source=sf["source"],
                    coerce=sf.get("coerce", "text"),
                    attr_key=sf.get("attr_key"),
                )
                for sf in f.get("sub_fields", [])
            ],
        )
        for f in d.get("fields", [])
    ]
    examples = [
        ExampleData(
            text=ex["text"],
            extractions=[
                ExampleExtraction(
                    cls=e["cls"],
                    text=e["text"],
                    attributes=e.get("attributes", {}) or {},
                )
                for e in ex.get("extractions", [])
            ],
        )
        for ex in d.get("examples", [])
    ]
    return DocTypeDefinition(
        name=d["name"],
        fields=fields,
        core_paths=list(d.get("core_paths", [])),
        prompt=d.get("prompt", ""),
        examples=examples,
    )


# --- rule definition <-> dict -------------------------------------------------

# Each serializable rule primitive <-> its stable "kind" discriminator. CodedRuleDef is
# intentionally absent: it carries a Python callable and cannot round-trip through JSON.
_KIND_MAP: dict[type, str] = {
    PresenceRuleDef: "presence",
    ThresholdCompareRuleDef: "threshold",
    ArithmeticIdentityRuleDef: "arithmetic",
    SetMembershipRuleDef: "set_membership",
    FieldDependencyRuleDef: "field_dependency",
    UniquenessVsHistoryRuleDef: "uniqueness",
    EqualityRuleDef: "equality",
    DateConstraintRuleDef: "date_constraint",
    LlmAdvisoryRuleDef: "llm_advisory",
}

_BUILDER_MAP: dict[str, type] = {kind: cls for cls, kind in _KIND_MAP.items()}


def rule_defn_to_dict(defn: DocTypeRuleDefinition) -> dict:
    """Serialize a :class:`DocTypeRuleDefinition`, skipping coded (callable) rules.

    Each kept rule is dumped via ``dataclasses.asdict``; any private key (e.g.
    ``_test_fn``) is dropped and a ``"kind"`` discriminator is injected.
    """
    rules: list[dict] = []
    for rule in defn.rules:
        kind = _KIND_MAP.get(type(rule))
        if kind is None:  # CodedRuleDef (or any other non-serializable rule) -> skip
            continue
        raw = dataclasses.asdict(rule)
        clean = {k: v for k, v in raw.items() if not k.startswith("_")}
        clean["kind"] = kind
        rules.append(clean)
    return {
        "name": defn.name,
        "rules": rules,
        "citation_paths": list(defn.citation_paths),
    }


def dict_to_rule_defn(d: dict) -> DocTypeRuleDefinition:
    """Rebuild a :class:`DocTypeRuleDefinition` from its serialized dict form.

    Unknown ``kind`` values are skipped defensively rather than raising.
    """
    rules: list = []
    for raw in d.get("rules", []):
        params = dict(raw)
        kind = params.pop("kind", None)
        params = {k: v for k, v in params.items() if not k.startswith("_")}
        builder = _BUILDER_MAP.get(kind)
        if builder is None:
            continue  # unknown / non-serializable kind -> skip defensively
        rules.append(builder(**params))
    return DocTypeRuleDefinition(
        name=d["name"],
        rules=rules,
        citation_paths=list(d.get("citation_paths", [])),
    )


# --- validation (Wave 2) ------------------------------------------------------

# The field kinds the interpreter understands (mirrors FieldDef.kind). ``signature``
# is a spatially-detected list[FieldValue] filled by the post-pass, not the LLM.
_VALID_FIELD_KINDS = {
    "scalar", "presence", "list_scalar", "list_composite", "composite", "signature"
}
# Kinds that REQUIRE a non-empty sub_fields list (and only those).
_COMPOSITE_KINDS = {"composite", "list_composite"}
# Both top-level fields and sub-fields coerce via this closed set.
_VALID_COERCE = {"text", "number"}
# Where a sub-field reads its value from.
_VALID_SUBFIELD_SOURCES = {"span", "attribute"}
# Severities the rule interpreter accepts (mirrors schemas.Severity).
_VALID_SEVERITIES = {"advisory", "review", "hard"}
# Serializable rule kinds (the keys are the discriminators carried in JSON). Anything
# not here — most importantly a would-be "coded" rule — is rejected: custom types must
# NEVER carry code.
_VALID_RULE_KINDS = set(_BUILDER_MAP)


def validate_custom_extraction_dict(d: dict) -> list[str]:
    """Validate a serialized extraction definition, returning human-readable errors.

    An empty list means the definition is structurally sound. Checks:

    * ``name`` is a string and ``fields`` / ``core_paths`` are lists.
    * each field has a unique non-empty string ``name``, a ``kind`` in the five valid
      kinds, and a ``coerce`` in ``{text, number}``;
    * ``sub_fields`` is non-empty IFF ``kind`` is composite/list_composite, and each
      sub-field has a ``name``, a ``source`` in ``{span, attribute}``, and a valid
      ``coerce``;
    * every ``core_paths`` entry references a declared top-level field name.

    Pure: no DB / FastAPI imports.
    """
    errors: list[str] = []

    if not isinstance(d.get("name"), str) or not d.get("name"):
        errors.append("extraction definition: 'name' must be a non-empty string")
    fields = d.get("fields")
    if not isinstance(fields, list):
        errors.append("extraction definition: 'fields' must be a list")
        fields = []
    core_paths = d.get("core_paths")
    if not isinstance(core_paths, list):
        errors.append("extraction definition: 'core_paths' must be a list")
        core_paths = []

    field_names: set[str] = set()
    for i, f in enumerate(fields):
        where = f"field #{i}"
        if not isinstance(f, dict):
            errors.append(f"{where}: must be an object")
            continue
        name = f.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"{where}: 'name' must be a non-empty string")
        else:
            where = f"field '{name}'"
            if name in field_names:
                errors.append(f"{where}: duplicate field name")
            field_names.add(name)

        kind = f.get("kind")
        if kind not in _VALID_FIELD_KINDS:
            errors.append(
                f"{where}: 'kind' must be one of {sorted(_VALID_FIELD_KINDS)} (got {kind!r})"
            )
        coerce = f.get("coerce", "text")
        if coerce not in _VALID_COERCE:
            errors.append(
                f"{where}: 'coerce' must be one of {sorted(_VALID_COERCE)} (got {coerce!r})"
            )

        sub_fields = f.get("sub_fields") or []
        if not isinstance(sub_fields, list):
            errors.append(f"{where}: 'sub_fields' must be a list")
            sub_fields = []
        if kind in _COMPOSITE_KINDS and not sub_fields:
            errors.append(f"{where}: kind {kind!r} requires a non-empty 'sub_fields'")
        if kind not in _COMPOSITE_KINDS and sub_fields:
            errors.append(f"{where}: 'sub_fields' is only allowed for composite kinds")

        for j, sf in enumerate(sub_fields):
            sub_where = f"{where} sub_field #{j}"
            if not isinstance(sf, dict):
                errors.append(f"{sub_where}: must be an object")
                continue
            if not isinstance(sf.get("name"), str) or not sf.get("name"):
                errors.append(f"{sub_where}: 'name' must be a non-empty string")
            if sf.get("source") not in _VALID_SUBFIELD_SOURCES:
                errors.append(
                    f"{sub_where}: 'source' must be one of "
                    f"{sorted(_VALID_SUBFIELD_SOURCES)} (got {sf.get('source')!r})"
                )
            sub_coerce = sf.get("coerce", "text")
            if sub_coerce not in _VALID_COERCE:
                errors.append(
                    f"{sub_where}: 'coerce' must be one of "
                    f"{sorted(_VALID_COERCE)} (got {sub_coerce!r})"
                )

    for path in core_paths:
        base = str(path).split(".", 1)[0]
        if base not in field_names:
            errors.append(
                f"core_paths entry {path!r} references undeclared field {base!r}"
            )

    return errors


def validate_custom_rule_dict(d: dict, declared_field_names: set[str]) -> list[str]:
    """Validate a serialized rule definition against the declared extraction fields.

    An empty list means the rule set is structurally sound. Checks:

    * ``name`` is a string and ``rules`` / ``citation_paths`` are lists;
    * every rule has a ``kind`` in the serializable set — anything else (notably a
      would-be coded rule) is rejected so custom types can never carry code;
    * ``severity`` (when present) is in ``{advisory, review, hard}`` — except for
      ``llm_advisory``, whose severity the UI may set freely (it is forced to "review"
      at runtime);
    * ``threshold`` rules set exactly one of ``threshold`` / ``threshold_setting``;
    * ``set_membership`` rules set exactly one of ``allowed_list`` /
      ``allowed_list_setting``;
    * ``arithmetic`` rules carry ``result_path`` / ``addend_a_path`` / ``addend_b_path``;
    * every ``*_path`` a rule references resolves (by its base field name, the part
      before any ``.``) to a declared extraction field.

    Pure: no DB / FastAPI imports.
    """
    errors: list[str] = []

    if not isinstance(d.get("name"), str) or not d.get("name"):
        errors.append("rule definition: 'name' must be a non-empty string")
    rules = d.get("rules")
    if not isinstance(rules, list):
        errors.append("rule definition: 'rules' must be a list")
        rules = []
    if not isinstance(d.get("citation_paths", []), list):
        errors.append("rule definition: 'citation_paths' must be a list")

    for i, rule in enumerate(rules):
        name = rule.get("name") if isinstance(rule, dict) else None
        where = f"rule '{name}'" if name else f"rule #{i}"
        if not isinstance(rule, dict):
            errors.append(f"{where}: must be an object")
            continue

        kind = rule.get("kind")
        if kind not in _VALID_RULE_KINDS:
            errors.append(
                f"{where}: 'kind' must be one of {sorted(_VALID_RULE_KINDS)} (got {kind!r}); "
                "custom types may not carry code"
            )
            # Unknown kind: don't try to interpret its remaining fields.
            continue

        # Severity: validated for every kind EXCEPT llm_advisory (forced to review).
        if kind != "llm_advisory" and "severity" in rule:
            if rule["severity"] not in _VALID_SEVERITIES:
                errors.append(
                    f"{where}: 'severity' must be one of "
                    f"{sorted(_VALID_SEVERITIES)} (got {rule['severity']!r})"
                )

        if kind == "threshold":
            has_literal = rule.get("threshold") is not None
            has_setting = rule.get("threshold_setting") is not None
            if has_literal == has_setting:
                errors.append(
                    f"{where}: set exactly one of 'threshold' / 'threshold_setting'"
                )
            if rule.get("op") not in {"lte", "gte", "lt", "gt"}:
                errors.append(
                    f"{where}: 'op' must be one of ['gt','gte','lt','lte'] (got {rule.get('op')!r})"
                )
        elif kind == "set_membership":
            has_list = rule.get("allowed_list") is not None
            has_setting = rule.get("allowed_list_setting") is not None
            if has_list == has_setting:
                errors.append(
                    f"{where}: set exactly one of 'allowed_list' / 'allowed_list_setting'"
                )
        elif kind == "arithmetic":
            for key in ("result_path", "addend_a_path", "addend_b_path"):
                if not rule.get(key):
                    errors.append(f"{where}: 'arithmetic' requires '{key}'")
        elif kind == "equality":
            has_literal = rule.get("expected") is not None
            has_setting = rule.get("expected_field_path") is not None
            if has_literal == has_setting:
                errors.append(
                    f"{where}: set exactly one of 'expected' / 'expected_field_path'"
                )
            if "match_mode" in rule and rule["match_mode"] not in {
                "exact", "normalized", "regex", "fuzzy"
            }:
                errors.append(
                    f"{where}: 'match_mode' must be one of "
                    f"['exact','normalized','regex','fuzzy'] (got {rule['match_mode']!r})"
                )
            if rule.get("match_mode") == "regex" and isinstance(rule.get("expected"), str):
                try:
                    re.compile(rule["expected"])
                except re.error:
                    errors.append(f"{where}: 'expected' is not a valid regex pattern")
            if "fuzzy_threshold" in rule:
                value = rule["fuzzy_threshold"]
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not (0.0 <= value <= 1.0)
                ):
                    errors.append(
                        f"{where}: 'fuzzy_threshold' must be a number between 0 and 1"
                    )
        elif kind == "date_constraint":
            # Truthiness (not ``is not None``): the UI writes an empty string for a
            # cleared input, and the interpreter treats "" as absent (``if rule.min:``).
            # A date can never legitimately be "" — so mirror the interpreter and the
            # ``arithmetic`` branch's convention rather than ``equality``'s (where the
            # empty-string literal ``expected: ""`` is a valid comparison value).
            has_constraint = (
                bool(rule.get("not_future"))
                or bool(rule.get("min"))
                or bool(rule.get("max"))
                or bool(rule.get("before_field_path"))
                or bool(rule.get("after_field_path"))
            )
            if not has_constraint:
                errors.append(f"{where}: date_constraint requires at least one constraint")
            for key in ("min", "max"):
                value = rule.get(key)
                if value:
                    try:
                        date.fromisoformat(value)
                    except (ValueError, TypeError):
                        errors.append(
                            f"{where}: '{key}' must be an ISO date string YYYY-MM-DD"
                        )

        # Every referenced field path must resolve to a declared field (by base name).
        for key, value in rule.items():
            if key.endswith("_path") and isinstance(value, str) and value:
                base = value.split(".", 1)[0]
                if base not in declared_field_names:
                    errors.append(
                        f"{where}: '{key}' references undeclared field {base!r}"
                    )

    return errors


__all__ = [
    "extraction_defn_to_dict",
    "dict_to_extraction_defn",
    "rule_defn_to_dict",
    "dict_to_rule_defn",
    "validate_custom_extraction_dict",
    "validate_custom_rule_dict",
]
