"""Per-kind value comparison: do two candidate values for a canonical field agree?

Reconciliation compares candidates drawn from different documents, which never match
byte-for-byte (``$135.00`` vs ``135.0``, ``Acme Ltd`` vs ``Acme Limited``, an invoice date
one day off a PO date). So a canonical field is assigned a KIND — money / date / string —
and comparisons run under a kind-specific tolerance. The kind is inferred once per field
from its name + sample values; :func:`values_agree` then decides each pair.

The date-name regex and ``as_date`` are reused from ``app.rules.base`` so date parsing is
identical to the single-doc rule engine.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.rules.base import as_date

# Field-name hints that a field carries a date (vs a plain string).
_DATE_NAME = re.compile(r"date|_dt|effective|expiry|due|renewal", re.IGNORECASE)


def _is_number(value: object) -> bool:
    """A real numeric value (bools are NOT numbers here — they're presence flags)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize(value: object) -> str:
    """String normalization key: casefold -> collapse whitespace -> strip.

    Mirrors the casefold/collapse/strip approach of the codebase's other normalizers
    (``structuring._normalize_for_dedup`` / ``rules.definition._normalize_equality_value``),
    kept minimal here: exact-equality after this key means the two strings agree.
    """
    return " ".join(str(value).casefold().split()).strip()


def infer_kind(field_path: str, sample_values: list) -> str:
    """Infer a canonical field's comparison kind: ``"money"`` | ``"date"`` | ``"string"``.

    Numeric samples -> money. Otherwise a date-ish field name OR a sample that ``as_date``
    can parse -> date. Everything else -> string.
    """
    non_null = [v for v in sample_values if v is not None]
    if non_null and all(_is_number(v) for v in non_null):
        return "money"
    if _DATE_NAME.search(field_path):
        return "date"
    if any(as_date(v) is not None for v in non_null):
        return "date"
    return "string"


def _money_agree(a: object, b: object, settings) -> bool:
    """Money agreement: absolute OR percentage tolerance (0 == 0 agrees)."""
    try:
        fa, fb = float(a), float(b)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    tol = max(
        settings.reconcile_money_abs_tolerance,
        settings.reconcile_money_pct_tolerance * max(abs(fa), abs(fb)),
    )
    return abs(fa - fb) <= tol


def _string_agree(a: object, b: object, settings) -> bool:
    """String agreement: normalized equality OR a fuzzy ratio at/above the threshold."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= settings.reconcile_string_fuzzy_threshold


def values_agree(kind: str, a: object, b: object, settings) -> bool:
    """Whether two non-null candidate values agree under the field's ``kind``."""
    if kind == "money":
        return _money_agree(a, b, settings)
    if kind == "date":
        da, db = as_date(a), as_date(b)
        if da is None or db is None:
            return _string_agree(a, b, settings)  # unparsable -> fall back to string rule
        return abs((da - db).days) <= settings.reconcile_date_tolerance_days
    return _string_agree(a, b, settings)
