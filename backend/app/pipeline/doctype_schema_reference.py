"""Machine-schema reference for the doc-type design wizard's system prompt.

The wizard's LLM can only author what its prompt teaches it. Hand-maintaining that list
let it fall years behind the real schema (7 of 23 rule kinds, no signature fields). This
module DERIVES the reference from the exact same dataclasses the save-time validator uses
(``serialization._KIND_MAP`` for rules, ``extraction.definition.FieldDef`` for fields,
``rules.expression._HELPERS`` for the formula DSL), so every new primitive appears in the
prompt automatically and the wizard can never drift from
``serialization.validate_custom_*`` again.

Introspection only: required-ness comes from dataclass defaults, enum values from
``Literal`` args, and each kind's one-line description from its dataclass docstring.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Literal, Union, get_args, get_origin, get_type_hints

from app.extraction.definition import FieldDef, SubFieldDef
from app.rules.expression import _HELPERS
from app.rules.formats import FORMAT_KEYS
from app.serialization import _KIND_MAP

# Params carried by (almost) every rule — described once in the preamble and omitted from
# each kind's per-rule param list to keep the catalogue readable.
_COMMON_RULE_PARAMS = {"name", "severity", "detail_pass", "detail_fail"}

# Kind-specific notes introspection can't recover (closed value sets held as plain `str`,
# cross-param constraints). Keyed by the rule's "kind" discriminator.
_RULE_NOTES: dict[str, str] = {
    "threshold": "set exactly one of `threshold` (a number) or `threshold_setting` (a settings name).",
    "set_membership": "set exactly one of `allowed_list` or `allowed_list_setting`.",
    "equality": "set exactly one of `expected` (a literal) or `expected_field_path` (another field).",
    "aggregate": "set exactly one of `compare_value` or `compare_field_path`.",
    "format": f"`format` must be one of: {', '.join(FORMAT_KEYS)}.",
    "expression": "`expression` is a formula in the DSL described below.",
    "llm_advisory": "takes NO `severity` (forced to \"review\"); the only param is `question`.",
    "numeric_range": "at least one of `min` / `max` is required.",
    "date_constraint": "configure at least one of `not_future` / `min` / `max` / `before_field_path` / `after_field_path`.",
    "length_bounds": "at least one of `min_length` / `max_length` is required.",
}


def _render_hint(hint: object) -> str:
    """Render a resolved type hint the way the JSON author should think of it."""
    origin = get_origin(hint)
    if origin is Literal:
        return " | ".join(f'"{a}"' if isinstance(a, str) else str(a) for a in get_args(hint))
    if origin is Union or origin is types.UnionType:  # typing.Optional and `X | None`
        parts = [a for a in get_args(hint) if a is not type(None)]
        rendered = " | ".join(_render_hint(p) for p in parts)
        return f"{rendered} | null" if len(parts) != len(get_args(hint)) else rendered
    if origin in (list, tuple):
        args = get_args(hint)
        inner = _render_hint(args[0]) if args else "string"
        return f"[{inner}, ...]"
    return {int: "number", float: "number", str: "string", bool: "true|false"}.get(
        hint, getattr(hint, "__name__", str(hint))
    )


def _describe_params(cls: type, skip: set[str]) -> list[str]:
    """One ``name: type (required|default …)`` string per non-skipped dataclass field."""
    hints = get_type_hints(cls)
    out: list[str] = []
    for f in dataclasses.fields(cls):
        if f.name.startswith("_") or f.name in skip:
            continue
        type_str = _render_hint(hints[f.name])
        if f.default is not dataclasses.MISSING:
            marker = f"optional, default {f.default!r}"
        elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
            marker = "optional"
        else:
            marker = "required"
        out.append(f"`{f.name}`: {type_str} ({marker})")
    return out


def _summary(cls: type) -> str:
    """The dataclass docstring's first line, with RST double-backticks flattened."""
    first_line = next(
        (ln.strip() for ln in (cls.__doc__ or "").splitlines() if ln.strip()), ""
    )
    return first_line.replace("``", "`")


def _rule_catalogue() -> str:
    lines = [
        "Every rule object is `{\"kind\": <one below>, \"name\": <label>, "
        '"severity": "hard" | "review" | "advisory", ...kind-specific params...}`.',
        '- `severity`: "hard" forces a flag (the LLM can never override it); "review" '
        "caps the decision at needs_review; \"advisory\" is a note only.",
        "- Every rule also accepts optional `detail_pass` / `detail_fail`: short message "
        "templates shown when the check passes / fails (may reference a field with `{field_name}`).",
        "- Most value rules SKIP (emit no check) when the field they read is absent — they "
        "never manufacture a failure from missing data; use the presence/cardinality kinds to require a field.",
        "",
        "The rule kinds (each lists only its kind-specific params):",
    ]
    for cls, kind in _KIND_MAP.items():
        params = _describe_params(cls, _COMMON_RULE_PARAMS)
        lines.append(f'- `"{kind}"` — {_summary(cls)}')
        if params:
            lines.append("    params: " + "; ".join(params))
        if kind in _RULE_NOTES:
            lines.append(f"    note: {_RULE_NOTES[kind]}")
    return "\n".join(lines)


def _field_catalogue() -> str:
    kinds = get_args(get_type_hints(FieldDef)["kind"])
    field_params = _describe_params(FieldDef, {"name", "kind", "cls", "sub_fields"})
    sub_params = _describe_params(SubFieldDef, set())
    return "\n".join(
        [
            'Each extraction field is `{"name", "kind", "cls", "coerce", "is_core", '
            '"sub_fields", "dedup"}`:',
            "- `kind` is one of: " + ", ".join(f'"{k}"' for k in kinds) + ".",
            "- other field params: " + "; ".join(field_params) + ".",
            "- `cls` is the extraction class the model emits — a singular PascalCase token "
            "derived from the field name (line_items → LineItem, invoice_no → InvoiceNo, "
            "vendor → Vendor, total → Total).",
            "- `sub_fields` MUST be non-empty IF AND ONLY IF `kind` is \"composite\" or "
            '"list_composite"; for every other kind it MUST be empty/omitted.',
            "- Each sub-field is {" + ", ".join(sub_params) + "} "
            '(`source="span"` reads the parent\'s verbatim text; `source="attribute"` reads '
            "a named column, optionally overridden by `attr_key`).",
            '- `kind="signature"` declares a signature field: leave `sub_fields` empty and set '
            "`cls` to a label like \"Signature\" — the values are filled by a spatial signature "
            "detector, NOT emitted by the model. Pair it with the `signature_presence` rule.",
            '- `dedup` is only meaningful for `kind="list_scalar"`: it collapses duplicate '
            "items repeated across large multi-section documents.",
        ]
    )


def _expression_dsl() -> str:
    helpers = ", ".join(f"`{name}`" for name in _HELPERS)
    return "\n".join(
        [
            "The `expression` rule evaluates a small sandboxed formula that must be truthy "
            "(it is NOT Python — a fixed allow-list, never `eval`). Use it for checks no "
            "dedicated kind covers.",
            "- A bare field name resolves to that field's value; `field(\"a.b\")` reads a "
            "composite sub-field; list fields are reachable ONLY through the helpers below.",
            "- Helpers: " + helpers + ".",
            "- Operators: `+ - * / %`, comparisons, `and/or/not`, `in [..]`.",
            "- Examples: `gross == net + tax` · "
            '`abs(total - sum_of("line_items", "amount")) <= 0.01` · `end_date > start_date` · '
            '`days_between(today(), doc_date) <= 90` · `value in ["EUR", "USD"]`.',
        ]
    )


def build_schema_reference() -> str:
    """The full field + rule + DSL reference block for the assistant's system prompt."""
    return "\n\n".join(
        [
            "## Extraction fields\n" + _field_catalogue(),
            "## Approval rule kinds\n" + _rule_catalogue(),
            "## Expression DSL\n" + _expression_dsl(),
        ]
    )


__all__ = ["build_schema_reference"]
