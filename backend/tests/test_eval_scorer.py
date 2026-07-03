"""Pure unit tests for the evaluation scorer (no DB / HTTP / pipeline).

Mirrors the direct-call style of tests/test_rules_definition.py: each scorer primitive
is exercised on hand-built ``fields``-shaped dicts. The value comparators are reused from
the reconciler, so the exact/normalized split matches its money/date/string tolerance.
"""

import pytest

from app.evaluation.golden import GoldenCase, get_golden, load_goldens
from app.evaluation.scorer import (
    align_collection,
    infer_field_kind,
    resolve_path,
    score_extraction,
    score_scalar_fields,
    values_match,
)


def _fv(value, confidence: float = 1.0) -> dict:
    """A dumped FieldValue node."""
    return {"value": value, "confidence": confidence, "grounding": None}


def _row(**cols) -> dict:
    """A list_composite actual row: each column wrapped as a FieldValue node."""
    return {name: _fv(v) for name, v in cols.items()}


_LINE_COLUMNS = ["desc", "qty", "unit_price", "amount"]


# --- resolve_path -------------------------------------------------------------


def test_resolve_path_scalar_and_composite():
    fields = {
        "total": _fv(658.80),
        "termination_clause": {"text": _fv("blah"), "notice_period": _fv("30 days")},
    }
    assert resolve_path(fields, "total") == 658.80
    assert resolve_path(fields, "termination_clause.notice_period") == "30 days"
    assert resolve_path(fields, "missing") is None
    assert resolve_path(fields, "termination_clause.nope") is None


# --- values_match -------------------------------------------------------------


def test_values_match_none_semantics():
    assert values_match(None, None, "string") == (True, True)
    assert values_match(None, "x", "string") == (False, False)
    assert values_match("x", None, "string") == (False, False)


def test_values_match_number_epsilon_is_exact():
    # 658.8 == 658.80 under the 1e-9 epsilon -> exact (and therefore normalized).
    assert values_match(658.8, 658.80, "money") == (True, True)


def test_exact_vs_normalized_divergence():
    # A currency-prefixed string vs. a float: exact coercion does NOT strip "$", and the
    # reused money comparator can't parse "$135.00", so this is a genuine non-match.
    assert values_match(135.0, "$135.00", "money") == (False, False)

    # Real divergences: exact fails but the kind-tolerant comparator agrees.
    assert values_match(658.80, 658.79, "money") == (False, True)  # within 0.01 abs tol
    assert values_match("Acme Ltd", "Acme Limited", "string") == (False, True)  # legal suffix
    assert values_match("2026-04-02", "2026-04-03", "date") == (False, True)  # within 3 days


def test_infer_field_kind_wraps_reconciler():
    assert infer_field_kind("total", 658.80) == "money"
    assert infer_field_kind("invoice_date", "2026-04-02") == "date"
    assert infer_field_kind("vendor", "NORTHWIND LTD.") == "string"


# --- score_scalar_fields ------------------------------------------------------


def test_score_scalar_fields_perfect_and_none():
    expected = {"vendor": "NORTHWIND LTD.", "po_number": None, "total": 658.80}
    actual = {"vendor": _fv("NORTHWIND LTD."), "po_number": _fv(None), "total": _fv(658.80)}
    rows = {r["path"]: r for r in score_scalar_fields(expected, actual)}
    assert rows["vendor"]["exact_match"] and rows["vendor"]["normalized_match"]
    assert rows["po_number"]["exact_match"] and rows["po_number"]["normalized_match"]
    assert rows["total"]["exact_match"]


# --- align_collection ---------------------------------------------------------


def _clean_line_items() -> list:
    return [
        {"desc": "A4 paper", "qty": 20, "unit_price": 6.50, "amount": 130.00},
        {"desc": "Toner cartridge", "qty": 4, "unit_price": 89.00, "amount": 356.00},
        {"desc": "Desk organizer", "qty": 10, "unit_price": 12.40, "amount": 124.00},
    ]


def _clean_actual_rows() -> list:
    return [
        _row(desc="A4 paper", qty=20, unit_price=6.50, amount=130.00),
        _row(desc="Toner cartridge", qty=4, unit_price=89.00, amount=356.00),
        _row(desc="Desk organizer", qty=10, unit_price=12.40, amount=124.00),
    ]


def test_align_collection_perfect():
    res = align_collection(_clean_line_items(), _clean_actual_rows(), _LINE_COLUMNS)
    assert res["matched"] == 3
    assert res["row_precision"] == 1.0
    assert res["row_recall"] == 1.0
    assert res["row_f1"] == 1.0
    assert res["cell_accuracy"] == 1.0
    assert res["line_item_score"] == 1.0


def test_align_collection_missing_row():
    actual = _clean_actual_rows()[:2]  # drop the third expected row
    res = align_collection(_clean_line_items(), actual, _LINE_COLUMNS)
    assert res["matched"] == 2
    assert res["n_expected"] == 3
    assert res["row_precision"] == 1.0
    assert round(res["row_recall"], 4) == round(2 / 3, 4)
    assert res["cell_accuracy"] == 1.0


def test_align_collection_extra_row():
    actual = _clean_actual_rows() + [_row(desc="Phantom", qty=1, unit_price=1.0, amount=1.0)]
    res = align_collection(_clean_line_items(), actual, _LINE_COLUMNS)
    assert res["matched"] == 3
    assert res["n_actual"] == 4
    assert round(res["row_precision"], 4) == round(3 / 4, 4)
    assert res["row_recall"] == 1.0


def test_align_collection_shuffled_still_aligns():
    shuffled = list(reversed(_clean_actual_rows()))
    res = align_collection(_clean_line_items(), shuffled, _LINE_COLUMNS)
    assert res["matched"] == 3
    assert res["cell_accuracy"] == 1.0
    # The greedy match pairs each expected row with its shuffled twin.
    for pair in res["detail"]:
        assert pair["expected"]["desc"] == pair["actual"]["desc"]


def test_align_collection_both_empty():
    res = align_collection([], [], ["key_dates"])
    assert res["matched"] == 0
    assert res["row_precision"] == 1.0
    assert res["row_recall"] == 1.0
    assert res["cell_accuracy"] == 1.0


def test_align_collection_list_scalar_parties():
    expected = ["Acme Robotics Inc.", "Globex Industrial LLC"]
    actual = [_fv("Acme Robotics Inc."), _fv("Globex Industrial LLC")]
    res = align_collection(expected, actual, ["parties"])
    assert res["matched"] == 2
    assert res["cell_accuracy"] == 1.0
    assert res["line_item_score"] == 1.0


def test_align_collection_list_scalar_fuzzy_agrees():
    # "Acme Ltd" vs "Acme Limited" agree under the string comparator -> matched.
    res = align_collection(["Acme Ltd"], [_fv("Acme Limited")], ["parties"])
    assert res["matched"] == 1
    assert res["cell_accuracy"] == 1.0


# --- score_extraction ---------------------------------------------------------


def test_score_extraction_perfect():
    golden = GoldenCase(
        id="t",
        sample_file="x.pdf",
        doc_type="invoice",
        expected_fields={"vendor": "NORTHWIND LTD.", "total": 658.80, "po_number": None},
        expected_collections={"line_items": _clean_line_items()},
    )
    actual_fields = {
        "vendor": _fv("NORTHWIND LTD."),
        "total": _fv(658.80),
        "po_number": _fv(None),
        "line_items": _clean_actual_rows(),
    }
    res = score_extraction(golden, actual_fields)
    assert res["overall_score"] == 1.0
    assert res["field_accuracy_exact"] == 1.0
    assert res["field_accuracy_normalized"] == 1.0
    assert res["collection_scores"]["line_items"]["line_item_score"] == 1.0


def test_score_extraction_empty_collections():
    golden = GoldenCase(
        id="t",
        sample_file="x.pdf",
        doc_type="invoice",
        expected_fields={"vendor": "NORTHWIND LTD.", "total": 658.80},
        expected_collections={},
    )
    actual_fields = {"vendor": _fv("NORTHWIND LTD."), "total": _fv(658.80)}
    res = score_extraction(golden, actual_fields)
    assert res["overall_score"] == 1.0
    assert res["collection_scores"] == {}


def test_score_extraction_pools_misses_not_extras():
    # One scalar wrong, one line item missing, one extra actual row.
    golden = GoldenCase(
        id="t",
        sample_file="x.pdf",
        doc_type="invoice",
        expected_fields={"vendor": "NORTHWIND LTD.", "total": 658.80},
        expected_collections={"line_items": _clean_line_items()},
    )
    actual_fields = {
        "vendor": _fv("WRONG VENDOR"),
        "total": _fv(658.80),
        "line_items": _clean_actual_rows()[:2]
        + [_row(desc="Phantom", qty=9, unit_price=9.0, amount=9.0)],
    }
    res = score_extraction(golden, actual_fields)
    # Pool = 2 scalar leaves (1 hit) + 3 expected rows x 4 cols (2 matched rows fully hit,
    # 1 missed row all zero) = (1 + 8) / (2 + 12) = 9/14. The extra actual row is excluded.
    assert res["overall_score"] == pytest.approx(9 / 14, rel=1e-6)


# --- golden loading -----------------------------------------------------------


def test_load_goldens_and_get():
    cases = {c.id for c in load_goldens()}
    assert {"invoice-clean", "invoice-mismatch", "contract-standard", "mock-baseline"} <= cases
    assert get_golden("mock-baseline").doc_type == "invoice"
    with pytest.raises(KeyError):
        get_golden("does-not-exist")
