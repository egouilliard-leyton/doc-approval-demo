"""Exhaustive tests for the sandboxed formula evaluator (``app.rules.expression``).

The evaluator is the security boundary for user-authored formula rules, so the bulk of
this file is adversarial: known sandbox-escape strings must ALL be rejected by
``parse_and_check`` and evaluate to ``None``. The remainder exercises every allowed node
type, every helper (happy path + fail-soft ``None`` path), the short-circuit ``BoolOp``
semantics, the DoS caps, ``validate_expression`` and a few end-to-end formulas.

Mirrors the ``fv(value, conf, page)`` FieldValue-node helper from
``test_rules_definition.py``.
"""

from datetime import date, timedelta

import pytest

from app.rules.expression import (
    ExpressionError,
    aggregate_list,
    evaluate_expression,
    list_items,
    parse_and_check,
    validate_expression,
)


def fv(value, conf=0.9, page: int | None = 1) -> dict:
    """A FieldValue node as it appears in a dumped StructuredResult.fields."""
    grounding = (
        {"page": page, "char_start": 0, "char_end": 1, "snippet": str(value), "alignment": "exact"}
        if page is not None
        else None
    )
    return {"value": value, "confidence": conf, "grounding": grounding}


# Realistic composite (line_items) + scalar (amounts/parties) fixtures.
LINE_ITEMS = {
    "line_items": [
        {"desc": fv("Widget"), "amount": fv(125.0)},
        {"desc": fv("Gadget"), "amount": fv(10.0)},
    ]
}
SCALAR_LIST = {"amounts": [fv(5.0), fv(15.0)], "parties": [fv("Acme"), fv("Globex")]}


def ev(expr, fields=None):
    return evaluate_expression(expr, fields if fields is not None else {})


# --- sandbox escapes: MUST raise in parse_and_check AND evaluate to None -------

SANDBOX_ESCAPES = [
    "().__class__.__bases__[0].__subclasses__()",
    "__import__('os').system('x')",
    "x.__class__",
    "x[0]",
    "lambda: 1",
    "[i for i in range(9)]",
    "{k: 1 for k in x}",
    "{1, 2, 3}",
    "{'a': 1}",
    "f'{x}'",
    "2 ** 999999999",
    "a if b else c",
    "_x",
    "_x + 1",
    "x.attr",
    "x and _y",
    "obj.method()",
    "5 // 2",
    "5 | 2",
    "5 & 2",
    "5 << 2",
    "~5",
    "*x",
    "sum_of(*args)",
    "abs(x=1)",
]


@pytest.mark.parametrize("expr", SANDBOX_ESCAPES)
def test_sandbox_escape_rejected_by_parse(expr):
    with pytest.raises(ExpressionError):
        parse_and_check(expr)


@pytest.mark.parametrize("expr", SANDBOX_ESCAPES)
def test_sandbox_escape_evaluates_to_none(expr):
    assert evaluate_expression(expr, {"x": fv("v"), "b": fv(True), "args": fv(1)}) is None


def test_none_and_bytes_constants_rejected():
    with pytest.raises(ExpressionError):
        parse_and_check("None")
    with pytest.raises(ExpressionError):
        parse_and_check("b'bytes'")
    with pytest.raises(ExpressionError):
        parse_and_check("1j")


def test_syntax_error_is_wrapped():
    with pytest.raises(ExpressionError):
        parse_and_check("1 +")


# --- allowed node types -------------------------------------------------------


def test_arithmetic_operators():
    assert ev("2 + 3 * 4") == 14
    assert ev("10 - 4") == 6
    assert ev("10 / 4") == 2.5
    assert ev("10 % 3") == 1


def test_comparisons_and_chained():
    assert ev("5 > 3") is True
    assert ev("3 >= 3") is True
    assert ev("2 == 2") is True
    assert ev("2 != 3") is True
    assert ev("1 < 2 < 3") is True
    assert ev("1 < 2 < 1") is False


def test_boolean_and_or():
    assert ev("True and True") is True
    assert ev("True and False") is False
    assert ev("False or True") is True
    assert ev("False or False") is False


def test_in_and_not_in_literal_list():
    assert ev("'EUR' in ['EUR', 'USD']") is True
    assert ev("'GBP' in ['EUR', 'USD']") is False
    assert ev("'GBP' not in ['EUR', 'USD']") is True
    assert ev("2 in (1, 2, 3)") is True


def test_unary_not_and_neg():
    assert ev("not False") is True
    assert ev("not True") is False
    assert ev("-5 < 0") is True
    assert ev("+5 == 5") is True


def test_bare_name_resolves_scalar_and_never_leaks_containers():
    assert ev("total", {"total": fv(42.0)}) == 42.0
    # A top-level list resolves to None (the raw list can never enter the expression).
    assert ev("line_items", LINE_ITEMS) is None
    # A composite/dict node (no "value" key) also resolves to None.
    assert ev("clause", {"clause": {"notice": fv("30d")}}) is None


# --- helpers: list aggregation ------------------------------------------------


def test_sum_of_composite_and_absent():
    assert ev("sum_of('line_items', 'amount')", LINE_ITEMS) == 135.0
    assert ev("sum_of('missing', 'amount')", LINE_ITEMS) is None  # absent -> None


def test_count_of_composite_present_empty_and_absent():
    assert ev("count('line_items')", LINE_ITEMS) == 2
    assert ev("count('line_items')", {"line_items": []}) == 0  # present-but-empty -> 0
    assert ev("count('missing')", LINE_ITEMS) is None  # absent -> None


def test_min_max_avg_of_composite():
    assert ev("min_of('line_items', 'amount')", LINE_ITEMS) == 10.0
    assert ev("max_of('line_items', 'amount')", LINE_ITEMS) == 125.0
    assert ev("avg_of('line_items', 'amount')", LINE_ITEMS) == 67.5


def test_min_max_avg_none_over_zero_numeric_values():
    empty = {"line_items": []}
    assert ev("min_of('line_items', 'amount')", empty) is None
    assert ev("max_of('line_items', 'amount')", empty) is None
    assert ev("avg_of('line_items', 'amount')", empty) is None
    # present but empty list still sums to 0.0
    assert ev("sum_of('line_items', 'amount')", empty) == 0.0


def test_scalar_list_count_and_sum_without_sub_field():
    assert ev("count('amounts')", SCALAR_LIST) == 2
    assert ev("sum_of('amounts')", SCALAR_LIST) == 20.0
    # scalar rows that are non-numeric contribute no numbers -> sum 0.0
    assert ev("sum_of('parties')", SCALAR_LIST) == 0.0
    assert ev("count('parties')", SCALAR_LIST) == 2


def test_list_items_and_aggregate_list_direct():
    assert list_items(LINE_ITEMS, "line_items") is not None
    assert list_items(LINE_ITEMS, "total") is None  # not a list
    assert list_items({"a": {"b": [fv(1.0)]}}, "a.b") == [fv(1.0)]
    assert aggregate_list(LINE_ITEMS, "line_items", "sum", "amount") == 135.0
    assert aggregate_list(LINE_ITEMS, "missing", "count") is None


# --- helpers: numeric ---------------------------------------------------------


def test_abs_happy_and_fail_soft():
    assert ev("abs(-5)") == 5.0
    assert ev("abs(x)", {"x": fv(-3.0)}) == 3.0
    assert ev("abs(x)", {"x": fv("not-a-number")}) is None


def test_round_happy_clamp_and_fail_soft():
    assert ev("round(3.14159, 2)") == 3.14
    assert ev("round(3.7)") == 4  # ndigits defaults to 0
    assert ev("round(1.123456789, 10)") == round(1.123456789, 6)  # clamp to 6
    assert ev("round(x)", {"x": fv("nope")}) is None


# --- helpers: string ----------------------------------------------------------


def test_len_is_string_length_and_none_input():
    assert ev("len('hello')") == 5
    assert ev("len(x)", {"x": fv(12345)}) == 5  # len(str(12345))
    assert ev("len(x)", {"x": fv(None)}) is None
    assert ev("len(missing)", {}) is None


def test_lower_upper_trim():
    assert ev("lower('HeLLo')") == "hello"
    assert ev("upper('HeLLo')") == "HELLO"
    assert ev("trim('  hi  ')") == "hi"
    assert ev("lower(x)", {"x": fv(None)}) is None
    assert ev("upper(missing)", {}) is None


def test_matches_happy_nonmatch_bad_pattern_and_none():
    assert ev("matches('INV-123', 'INV-\\\\d+')", {}) is True
    assert ev("matches('PO-9', 'INV-\\\\d+')", {}) is False
    assert ev("matches('abc', '(')", {}) is None  # re.error -> None
    assert ev("matches(x, 'a+')", {"x": fv(None)}) is None


# --- helpers: date ------------------------------------------------------------


def test_days_between_absolute_and_fail_soft():
    assert ev("days_between('2026-01-01', '2026-01-11')") == 10
    assert ev("days_between('2026-01-11', '2026-01-01')") == 10  # order-independent
    assert ev("days_between('nope', '2026-01-01')") is None


def test_today_returns_iso_string():
    assert ev("today()") == date.today().isoformat()


def test_to_date_normalizes_and_enables_plain_compare():
    assert ev("to_date('2026-01-02')") == "2026-01-02"
    assert ev("to_date(x)", {"x": fv("garbage")}) is None
    # normalization makes </>/== work on plain strings
    assert ev("to_date('2026-01-02') < to_date('2026-02-01')") is True


# --- helpers: presence / field escape hatch -----------------------------------


def test_is_present_is_total():
    assert ev("is_present('total')", {"total": fv(1.0)}) is True
    assert ev("is_present('total')", {}) is False  # never None


def test_field_escape_hatch():
    assert ev("field('clause.notice')", {"clause": {"notice": fv("30 days")}}) == "30 days"
    assert ev("field('missing')", {}) is None


# --- short-circuit BoolOp semantics -------------------------------------------


def test_and_short_circuits_to_false_not_skip():
    # is_present guard is False -> decisive False WITHOUT touching field(...)>0.
    assert ev("is_present('absent') and field('absent') > 0", {}) is False


def test_or_short_circuits_to_true():
    fields = {"present_field": fv("hi")}
    assert ev("is_present('present_field') or field('absent') > 0", fields) is True


def test_and_true_path_uses_second_operand():
    fields = {"total": fv(50.0)}
    assert ev("is_present('total') and total > 10", fields) is True
    assert ev("is_present('total') and total > 100", fields) is False


def test_skip_propagates_through_comparison():
    # a referenced field is absent -> the whole comparison skips to None.
    assert ev("gross == net + tax", {"gross": fv(110.0), "tax": fv(10.0)}) is None


# --- DoS caps -----------------------------------------------------------------


def test_max_length_cap():
    expr = "0 + " * 110 + "0"  # ~441 chars > 400
    assert len(expr) > 400
    with pytest.raises(ExpressionError):
        parse_and_check(expr)
    assert evaluate_expression(expr, {}) is None


def test_max_depth_cap():
    expr = "not " * 20 + "x"  # ~depth 21 > 16, but few nodes and short
    assert len(expr) < 400
    with pytest.raises(ExpressionError):
        parse_and_check(expr)


def test_max_nodes_cap():
    expr = "x in [" + "9," * 150 + "]"  # ~307 chars, shallow, but >150 nodes
    assert len(expr) < 400
    with pytest.raises(ExpressionError):
        parse_and_check(expr)


# --- validate_expression ------------------------------------------------------


def test_validate_unknown_bare_field():
    errs = validate_expression("foo + 1", {"bar"})
    assert errs and any("foo" in e for e in errs)


def test_validate_unknown_literal_path_field():
    errs = validate_expression("is_present('nope')", {"total"})
    assert errs and any("nope" in e for e in errs)


def test_validate_unknown_function():
    errs = validate_expression("nope(x)", {"x"})
    assert errs and any("nope" in e for e in errs)


def test_validate_disallowed_syntax():
    errs = validate_expression("x.y", {"x"})
    assert errs  # rejected structurally


def test_validate_never_raises_on_garbage():
    assert validate_expression("1 +", set()) != []  # returns errors, does not raise


def test_validate_valid_formula_returns_empty():
    assert validate_expression("gross == net + tax", {"gross", "net", "tax"}) == []
    assert validate_expression("is_present('total') and total > 0", {"total"}) == []
    assert validate_expression(
        "sum_of('line_items', 'amount') > 0", {"line_items", "amount"}
    ) == []


# --- end-to-end formulas ------------------------------------------------------


def test_end_to_end_identity_true_and_false():
    true_fields = {"gross": fv(110.0), "net": fv(100.0), "tax": fv(10.0)}
    assert ev("gross == net + tax", true_fields) is True
    false_fields = {"gross": fv(999.0), "net": fv(100.0), "tax": fv(10.0)}
    assert ev("gross == net + tax", false_fields) is False


def test_end_to_end_line_item_reconciliation():
    fields = dict(LINE_ITEMS, total=fv(135.0))
    assert ev("abs(total - sum_of('line_items', 'amount')) <= 0.01", fields) is True
    off = dict(LINE_ITEMS, total=fv(200.0))
    assert ev("abs(total - sum_of('line_items', 'amount')) <= 0.01", off) is False


def test_end_to_end_skip_on_absent_field():
    # net absent -> arithmetic skips -> comparison skips -> None (no flag).
    assert ev("gross == net + tax", {"gross": fv(110.0), "tax": fv(10.0)}) is None


def test_end_to_end_date_ordering():
    fields = {
        "issued": fv((date.today() - timedelta(days=5)).isoformat()),
        "due": fv((date.today() + timedelta(days=25)).isoformat()),
    }
    assert ev("to_date(issued) < to_date(due)", fields) is True
    assert ev("days_between(issued, due) == 30", fields) is True
