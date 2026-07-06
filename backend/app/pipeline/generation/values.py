"""Flatten a structured ``fields`` blob into dotted-path -> value, for form-fill.

Mirrors ``app/pipeline/structuring.py::_flatten_grounding``'s traversal, but keeps the
leaf ``FieldValue``'s ``value`` instead of its grounding. The result is the flat map a
template's ``form_field_map`` binds against (``total`` -> 1234.56, ``line_items.0.amount``
-> ...). ``resolve_path`` does the same lookup for a single dotted path without building
the whole map, returning ``None`` on any miss rather than raising.
"""

from __future__ import annotations


def _is_field_value(node: object) -> bool:
    """A dumped :class:`~app.schemas.FieldValue` leaf (has a ``value`` key)."""
    return isinstance(node, dict) and "value" in node and "confidence" in node


def flatten_field_values(
    fields: object, prefix: str = "", out: dict[str, object] | None = None
) -> dict[str, object]:
    """Flatten every leaf field into dotted-path -> its extracted value.

    Numeric index segments address list items (``line_items.0.amount``), matching the
    paths :func:`app.pipeline.generation.catalogue.field_catalogue` produces.
    """
    if out is None:
        out = {}
    if _is_field_value(fields):
        out[prefix] = fields["value"]  # type: ignore[index]
        return out
    if isinstance(fields, list):
        for i, item in enumerate(fields):
            flatten_field_values(item, f"{prefix}.{i}" if prefix else str(i), out)
    elif isinstance(fields, dict):
        for key, value in fields.items():
            flatten_field_values(value, f"{prefix}.{key}" if prefix else key, out)
    return out


def resolve_path(fields: object, path: str) -> object | None:
    """Walk a dotted path into ``fields``, returning the leaf value or ``None``.

    A numeric segment indexes a list; any missing key, out-of-range index, or wrong
    node type yields ``None`` rather than raising. A resolved :class:`FieldValue` leaf
    is unwrapped to its ``value``.
    """
    node: object = fields
    for segment in path.split("."):
        if isinstance(node, list):
            if not segment.isdigit():
                return None
            index = int(segment)
            if index >= len(node):
                return None
            node = node[index]
        elif isinstance(node, dict):
            if segment not in node:
                return None
            node = node[segment]
        else:
            return None
    if _is_field_value(node):
        return node["value"]  # type: ignore[index]
    return node
